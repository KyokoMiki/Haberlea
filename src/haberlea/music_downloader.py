"""Modern music downloader with global concurrent queue.

This module provides a high-performance music downloading system using a
global queue that collects all tracks and downloads them concurrently,
regardless of their source (album, playlist, artist, or single track).
"""

import asyncio
import logging
import os
import shutil
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from time import gmtime, strftime
from typing import Any

import aiofiles
import aiohttp
import msgspec
from rich import print
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .download_queue import (
    DownloadQueue,
    MediaType,
    TrackTask,
)
from .plugins.base import ModuleBase
from .tagging import tag_file
from .utils.exceptions import (
    ConversionError,
    InvalidTrackError,
    TagSavingFailure,
    TrackDownloadError,
)
from .utils.m3u import M3UPlaylistWriter
from .utils.models import (
    AlbumInfo,
    ArtistInfo,
    CodecEnum,
    CodecOptions,
    ContainerEnum,
    CoverCompressionEnum,
    CoverOptions,
    DownloadEnum,
    DownloadTypeEnum,
    ImageFileTypeEnum,
    LyricsInfo,
    ModuleFlags,
    ModuleModes,
    PlaylistInfo,
    QualityEnum,
    SearchResult,
    TrackDownloadInfo,
    TrackInfo,
)
from .utils.path_builder import PathBuilder
from .utils.progress import ProgressStatus, set_current_task
from .utils.settings import settings
from .utils.tempfile_manager import TempFileManager
from .utils.transcoder import ConversionResult, transcode
from .utils.utils import (
    compare_images,
    download_file,
    get_image_resolution,
    sanitise_name,
)

logger = logging.getLogger(__name__)


class ModuleControls(msgspec.Struct, frozen=True):
    """Immutable container for module control dependencies.

    Attributes:
        module_list: List of available module names.
        module_settings: Module settings dictionary.
        loaded_modules: Cache of loaded module instances.
        module_loader: Async function to load a module with account index.
    """

    module_list: list[str]
    module_settings: dict[str, Any]
    loaded_modules: dict[str, ModuleBase]
    module_loader: Callable[[str, int], Coroutine[Any, Any, ModuleBase]]


class ArtworkSettings(msgspec.Struct, frozen=True):
    """Artwork download settings."""

    should_resize: bool
    resolution: int
    compression: str
    format: str


def format_duration(seconds: int) -> str:
    """Formats seconds into a human-readable time string.

    Args:
        seconds: The number of seconds to format.

    Returns:
        A formatted time string (e.g., "1d:02h:30m:45s").
    """
    time_data = gmtime(seconds)
    time_format = "%Mm:%Ss"

    if time_data.tm_hour > 0:
        time_format = "%Hh:" + time_format

    if seconds >= 86400:
        days = seconds // 86400
        time_format = f"{days}d:" + time_format

    return strftime(time_format, time_data)


class Downloader:
    """Music downloader with global concurrent queue support."""

    def __init__(
        self,
        module_controls: ModuleControls,
        path: str,
        queue: DownloadQueue,
        third_party_modules: dict[ModuleModes, str],
    ) -> None:
        """Initialize the downloader.

        Args:
            module_controls: Module control container.
            path: Base download path.
            queue: Global download queue.
            third_party_modules: Third-party module mappings.
        """
        self._module_list = module_controls.module_list
        self._module_settings = module_controls.module_settings
        self._loaded_modules = module_controls.loaded_modules
        self._load_module = module_controls.module_loader

        self._queue = queue
        self._third_party_modules = third_party_modules
        self._temp = TempFileManager()
        self._path_builder = PathBuilder(path)

        # Quality settings from global settings
        gs = settings.global_settings
        self._quality_tier = QualityEnum[gs.general.download_quality.upper()]
        self._codec_options = CodecOptions(
            spatial_codecs=gs.codecs.spatial_codecs,
            proprietary_codecs=gs.codecs.proprietary_codecs,
        )

    async def __aenter__(self) -> "Downloader":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager and cleanup resources."""
        await self._temp.cleanup()

    # ========================================================================
    # Queue Population Methods - Phase 1: Collect all tracks
    # ========================================================================

    async def queue_track(
        self,
        track_id: str,
        module_name: str,
        module: ModuleBase,
        original_url: str = "",
        track_data: dict[str, Any] | None = None,
    ) -> str:
        """Queues a single track for download.

        Args:
            track_id: The track identifier.
            module_name: The module name.
            module: The loaded module instance.
            original_url: The original URL that initiated this download.
            track_data: Pre-fetched track data.

        Returns:
            The job ID for this download.
        """
        # Create job for this single track
        job_id = await self._queue.create_job(
            original_url=original_url or f"{module_name}:track:{track_id}",
            media_type=MediaType.TRACK,
            media_id=track_id,
            module_name=module_name,
            download_path=self._path_builder.base_path,
        )

        task = TrackTask(
            track_id=track_id,
            job_id=job_id,
            module_name=module_name,
            module=module,
            download_path=self._path_builder.base_path,
            track_data=track_data,
        )
        await self._queue.add_track(job_id, task)
        print(f"Queued track: {track_id}")
        return job_id

    async def queue_album(
        self,
        album_id: str,
        module_name: str,
        module: ModuleBase,
        original_url: str = "",
        artist_name: str = "",
        base_path: str = "",
        album_data: dict[str, Any] | None = None,
        parent_job_id: str | None = None,
    ) -> tuple[AlbumInfo | None, str | None]:
        """Queues an album's tracks for download.

        Args:
            album_id: The album identifier.
            module_name: The module name.
            module: The loaded module instance.
            original_url: The original URL that initiated this download.
            artist_name: Artist name for path building.
            base_path: Base path override.
            album_data: Pre-fetched album data.
            parent_job_id: Parent job ID if this album is part of an artist download.

        Returns:
            Tuple of (AlbumInfo if successful, job_id or None).
        """
        album_info = await module.get_album_info(album_id, data=album_data)
        if not album_info:
            print(f"Failed to get album info: {album_id}")
            return None, None

        # Build album path
        album_path = self._path_builder.build_album_path(album_id, album_info)
        if base_path:
            album_path = base_path + album_path.split("/")[-2] + "/"

        # Create job for this album (unless part of artist download)
        job_id = parent_job_id
        if not job_id:
            job_id = await self._queue.create_job(
                original_url=original_url or f"{module_name}:album:{album_id}",
                media_type=MediaType.ALBUM,
                media_id=album_id,
                module_name=module_name,
                name=album_info.name,
                artist=artist_name or album_info.artist,
                download_path=album_path,
                cover_url=album_info.cover_url or "",
            )

        # Print album info
        print(f"=== Album: {album_info.name} ({album_id}) ===")
        print(f"Artist: {album_info.artist}")
        if album_info.release_year:
            print(f"Year: {album_info.release_year}")
        print(f"Tracks: {len(album_info.tracks)}")

        # Download album-level assets
        await self._download_album_assets(album_path, album_info, module_name)

        # Pre-download cover for all tracks
        cover_temp: Path | None = None
        if album_info.all_track_cover_jpg_url:
            cover_temp = await self._temp.download(album_info.all_track_cover_jpg_url)

        # Queue all tracks
        for index, track_id in enumerate(album_info.tracks, start=1):
            task = TrackTask(
                track_id=track_id,
                job_id=job_id,
                module_name=module_name,
                module=module,
                download_path=album_path,
                track_index=index,
                total_tracks=len(album_info.tracks),
                main_artist=artist_name or album_info.artist,
                cover_temp_location=cover_temp,
                track_data=album_info.track_data,
                album_info=album_info,
            )
            await self._queue.add_track(job_id, task)

        print(f"Queued {len(album_info.tracks)} tracks from album")
        return album_info, job_id

    async def queue_playlist(
        self,
        playlist_id: str,
        module_name: str,
        module: ModuleBase,
        original_url: str = "",
        custom_module_name: str | None = None,
        custom_module: ModuleBase | None = None,
    ) -> tuple[PlaylistInfo | None, str | None]:
        """Queues a playlist's tracks for download.

        Args:
            playlist_id: The playlist identifier.
            module_name: The module name.
            module: The loaded module instance.
            original_url: The original URL that initiated this download.
            custom_module_name: Optional different module for downloading.
            custom_module: Optional different module instance.

        Returns:
            Tuple of (PlaylistInfo if successful, job_id or None).
        """
        playlist_info = await module.get_playlist_info(playlist_id)
        if not playlist_info:
            print(f"Failed to get playlist info: {playlist_id}")
            return None, None

        # Build playlist path
        playlist_path = self._path_builder.build_playlist_path(playlist_info)

        # Determine which module to use for downloading
        dl_module = custom_module or module
        dl_module_name = custom_module_name or module_name

        # Create job for this playlist
        job_id = await self._queue.create_job(
            original_url=original_url or f"{module_name}:playlist:{playlist_id}",
            media_type=MediaType.PLAYLIST,
            media_id=playlist_id,
            module_name=dl_module_name,
            name=playlist_info.name,
            artist=playlist_info.creator,
            download_path=playlist_path,
            cover_url=playlist_info.cover_url or "",
        )

        # Print playlist info
        print(f"=== Playlist: {playlist_info.name} ({playlist_id}) ===")
        print(f"Creator: {playlist_info.creator}")
        if playlist_info.duration:
            print(f"Duration: {format_duration(playlist_info.duration)}")
        print(f"Tracks: {len(playlist_info.tracks)}")

        # Download playlist-level assets
        await self._download_playlist_assets(playlist_path, playlist_info, module_name)

        # Setup M3U if enabled
        m3u_path = await self._setup_m3u_playlist(playlist_info, playlist_path)

        # Queue all tracks
        for index, track_id in enumerate(playlist_info.tracks, start=1):
            task = TrackTask(
                track_id=track_id,
                job_id=job_id,
                module_name=dl_module_name,
                module=dl_module,
                download_path=playlist_path,
                track_index=index,
                total_tracks=len(playlist_info.tracks),
                track_data=playlist_info.track_data,
                playlist_info=playlist_info,
                m3u_playlist=m3u_path,
            )
            await self._queue.add_track(job_id, task)

        print(f"Queued {len(playlist_info.tracks)} tracks from playlist")
        return playlist_info, job_id

    async def queue_artist(
        self,
        artist_id: str,
        module_name: str,
        module: ModuleBase,
        original_url: str = "",
    ) -> tuple[ArtistInfo | None, str | None]:
        """Queues an artist's albums and tracks for download.

        Args:
            artist_id: The artist identifier.
            module_name: The module name.
            module: The loaded module instance.
            original_url: The original URL that initiated this download.

        Returns:
            Tuple of (ArtistInfo if successful, job_id or None).
        """
        artist_info = await module.get_artist_info(
            artist_id,
            settings.global_settings.artist_downloading.return_credited_albums,
        )
        if not artist_info:
            print(f"Failed to get artist info: {artist_id}")
            return None, None

        artist_name = artist_info.name
        artist_path = self._path_builder.base_path + sanitise_name(artist_name) + "/"

        # Create job for this artist (all albums/tracks belong to this job)
        job_id = await self._queue.create_job(
            original_url=original_url or f"{module_name}:artist:{artist_id}",
            media_type=MediaType.ARTIST,
            media_id=artist_id,
            module_name=module_name,
            name=artist_name,
            artist=artist_name,
            download_path=artist_path,
        )

        # Print artist info
        print(f"=== Artist: {artist_name} ({artist_id}) ===")
        if artist_info.albums:
            print(f"Albums: {len(artist_info.albums)}")
        if artist_info.tracks:
            print(f"Tracks: {len(artist_info.tracks)}")

        # Queue all albums (they share the same job_id)
        for album_id in artist_info.albums:
            await self.queue_album(
                album_id,
                module_name,
                module,
                artist_name=artist_name,
                base_path=artist_path,
                album_data=artist_info.album_data,
                parent_job_id=job_id,
            )

        # Queue standalone tracks
        for track_id in artist_info.tracks:
            task = TrackTask(
                track_id=track_id,
                job_id=job_id,
                module_name=module_name,
                module=module,
                download_path=artist_path,
                main_artist=artist_name,
                track_data=artist_info.track_data,
            )
            await self._queue.add_track(job_id, task)

        return artist_info, job_id

    # ========================================================================
    # Queue Processing - Phase 2: Download all tracks concurrently
    # ========================================================================

    async def process_queue(self) -> tuple[list[str], list[tuple[str, str]]]:
        """Processes all queued tracks concurrently.

        Progress is reported through the global callback in utils.progress.

        Returns:
            Tuple of (completed track IDs, failed track IDs with errors).
        """
        tasks = self._queue.get_all_track_tasks()
        if not tasks:
            print("No tracks in queue")
            return [], []

        print(f"\n=== Processing {len(tasks)} tracks ===\n")

        async with asyncio.TaskGroup() as tg:
            for task in tasks:
                tg.create_task(self._download_track_task(task))

        return self._queue.get_results()

    async def _download_track_task(self, task: TrackTask) -> None:
        """Downloads a single track with semaphore control.

        Args:
            task: The track task to download.
        """
        track_id = task.track_id

        async with self._queue._semaphore:
            # Keep PENDING status while fetching track info
            await self._queue.update_progress(track_id, message="获取曲目信息...")
            try:
                result = await self._download_track(task)
                # result is (track_location, status)
                # - (path, COMPLETED) for successful download
                # - (path, SKIPPED) for skipped (file exists)
                # - (None, SKIPPED) for skipped (different artist)
                track_location, final_status = result

                await self._queue.update_progress(
                    track_id,
                    status=final_status,
                    progress=1.0,
                    message="下载完成"
                    if final_status == ProgressStatus.COMPLETED
                    else "已跳过",
                )
                await self._queue.mark_track_complete(track_id, final_status)
            except Exception as e:
                logger.exception("Track download failed: %s", track_id)
                await self._queue.update_progress(
                    track_id,
                    status=ProgressStatus.FAILED,
                    message=str(e),
                )
                await self._queue.mark_track_complete(track_id, ProgressStatus.FAILED)
                if settings.global_settings.advanced.abort_download_when_single_failed:
                    raise

    @retry(
        retry=retry_if_exception_type(
            (aiohttp.ClientError, TimeoutError, OSError, asyncio.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _download_track(
        self, task: TrackTask
    ) -> tuple[str | None, ProgressStatus]:
        """Downloads a single track.

        Args:
            task: The track task containing all download information.

        Returns:
            Tuple of (track file path or None, final status).
        """
        track_id = task.track_id
        module = task.module
        module_name = task.module_name

        # Get track info
        track_info = await module.get_track_info(
            track_id,
            self._quality_tier,
            self._codec_options,
            data=task.track_data,
        )

        if track_info is None:
            raise InvalidTrackError(track_id, "Track info is None")

        # Now set status to DOWNLOADING with track info
        await self._queue.update_progress(
            track_id,
            status=ProgressStatus.DOWNLOADING,
            name=track_info.name,
            artist=", ".join(track_info.artists),
            album=track_info.album,
            message="",
        )

        # Check artist filter
        if (
            task.main_artist
            and task.main_artist.lower() not in [a.lower() for a in track_info.artists]
            and settings.global_settings.advanced.ignore_different_artists
        ):
            print(f"Skipping {track_info.name}: different artist")
            return None, ProgressStatus.SKIPPED

        # Update track numbering if needed
        if not settings.global_settings.formatting.force_album_format:
            if task.track_index:
                track_info.tags.track_number = task.track_index
            if task.total_tracks:
                track_info.tags.total_tracks = task.total_tracks

        # Print track info
        print(f"=== Track: {track_info.name} ({track_id}) ===")
        if track_info.album:
            print(f"Album: {track_info.album}")
        print(f"Artists: {', '.join(track_info.artists)}")
        print(f"Codec: {track_info.codec.pretty_name}")

        if track_info.error:
            raise InvalidTrackError(track_id, track_info.error)

        # Prepare file location
        download_location = task.download_path.replace("\\", "/")
        track_location_name, download_location = await self._prepare_track_location(
            track_info, download_location, module, module_name
        )

        codec = track_info.codec
        container = codec.container
        track_location = f"{track_location_name}.{container.name}"

        # Check if file exists
        conversions = self._get_codec_conversions()
        check_codec = conversions.get(codec, codec)
        check_location = f"{track_location_name}.{check_codec.container.name}"

        if (
            os.path.isfile(check_location)
            and settings.global_settings.advanced.ignore_existing_files
        ):
            print("Track already exists, skipping")
            if task.m3u_playlist:
                await self._add_to_m3u(task.m3u_playlist, track_info, track_location)
            return check_location, ProgressStatus.SKIPPED

        # Download track file
        print("Downloading track file")
        await self._queue.update_progress(track_id, message="下载音频文件")
        result = await self._download_track_file(
            track_id,
            track_info,
            track_location,
            track_location_name,
            codec,
            container,
            module,
        )
        if result[0] is None:
            return None, ProgressStatus.FAILED
        track_location = result[0]
        codec = result[1]
        container = result[2]

        # Download cover
        cover_temp = task.cover_temp_location
        if not cover_temp:
            print("Downloading artwork")
            await self._queue.update_progress(track_id, message="下载封面")
            cover_temp = await self._download_cover(
                track_info, track_location_name, module_name
            )

        # Get lyrics
        await self._queue.update_progress(track_id, message="获取歌词")
        embedded_lyrics, synced_lyrics = await self._get_lyrics(
            track_id, track_info, module_name, module
        )
        if synced_lyrics and settings.global_settings.lyrics.save_synced_lyrics:
            lrc_location = f"{track_location_name}.lrc"
            if not os.path.isfile(lrc_location):
                async with aiofiles.open(lrc_location, "w", encoding="utf-8") as f:
                    await f.write(synced_lyrics)

        # Get credits
        credits_list = await self._get_credits(
            track_id, track_info, module_name, module
        )

        # Convert if needed
        conversion_result = await self._convert_if_needed(
            track_location, track_location_name, codec, container
        )
        track_location = conversion_result.track_location
        container = conversion_result.container

        # Add to M3U
        if task.m3u_playlist:
            await self._add_to_m3u(task.m3u_playlist, track_info, track_location)

        # Tag file
        print("Tagging file")
        await self._queue.update_progress(track_id, message="写入标签")
        cover_path_str = str(cover_temp) if cover_temp else None
        try:
            tag_file(
                track_location,
                cover_path_str if settings.global_settings.covers.embed_cover else None,
                track_info,
                credits_list,
                embedded_lyrics,
                container,
            )
        except TagSavingFailure:
            print("Tagging failed")

        print(f"=== Track {track_id} completed ===")
        return track_location, ProgressStatus.COMPLETED

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _get_artwork_settings(
        self, module_name: str, is_external: bool = False
    ) -> ArtworkSettings:
        """Get artwork settings for cover downloading."""
        module_flags = self._module_settings[module_name].flags
        should_resize = bool(
            module_flags is not None and (module_flags & ModuleFlags.needs_cover_resize)
        )
        if is_external:
            return ArtworkSettings(
                should_resize=should_resize,
                resolution=settings.global_settings.covers.external_resolution,
                compression=settings.global_settings.covers.external_compression,
                format=settings.global_settings.covers.external_format,
            )
        return ArtworkSettings(
            should_resize=should_resize,
            resolution=settings.global_settings.covers.main_resolution,
            compression=settings.global_settings.covers.main_compression,
            format="jpg",
        )

    def _get_codec_conversions(self) -> dict[CodecEnum, CodecEnum]:
        """Get codec conversion mappings."""
        try:
            return {
                CodecEnum[k.upper()]: CodecEnum[v.upper()]
                for k, v in settings.global_settings.advanced.codec_conversions.items()
            }
        except KeyError:
            print("Warning: codec_conversions setting is invalid!")
            return {}

    async def _download_album_assets(
        self, album_path: str, album_info: AlbumInfo, module_name: str
    ) -> None:
        """Download album cover and related files."""
        os.makedirs(album_path, exist_ok=True)

        if album_info.cover_url:
            cover_path = f"{album_path}cover.{album_info.cover_type.name}"
            if not os.path.exists(cover_path):
                artwork_settings = self._get_artwork_settings(module_name)
                await download_file(
                    album_info.cover_url,
                    cover_path,
                    artwork_settings=msgspec.structs.asdict(artwork_settings),
                )

        if album_info.booklet_url:
            booklet_path = f"{album_path}Booklet.pdf"
            if not os.path.exists(booklet_path):
                await download_file(album_info.booklet_url, booklet_path)

        if album_info.description:
            desc_path = f"{album_path}description.txt"
            if not os.path.exists(desc_path):
                async with aiofiles.open(desc_path, "w", encoding="utf-8") as f:
                    await f.write(album_info.description)

    async def _download_playlist_assets(
        self, playlist_path: str, playlist_info: PlaylistInfo, module_name: str
    ) -> None:
        """Download playlist cover and related files."""
        os.makedirs(playlist_path, exist_ok=True)

        if playlist_info.cover_url:
            cover_path = f"{playlist_path}cover.{playlist_info.cover_type.name}"
            if not os.path.exists(cover_path):
                artwork_settings = self._get_artwork_settings(module_name)
                await download_file(
                    playlist_info.cover_url,
                    cover_path,
                    artwork_settings=msgspec.structs.asdict(artwork_settings),
                )

        if playlist_info.description:
            desc_path = f"{playlist_path}description.txt"
            if not os.path.exists(desc_path):
                async with aiofiles.open(desc_path, "w", encoding="utf-8") as f:
                    await f.write(playlist_info.description)

    async def _setup_m3u_playlist(
        self, playlist_info: PlaylistInfo, playlist_path: str
    ) -> str | None:
        """Setup M3U playlist file if enabled."""
        if not settings.global_settings.playlist.save_m3u:
            return None

        playlist_tags = {
            k: sanitise_name(v)
            for k, v in msgspec.structs.asdict(playlist_info).items()
        }
        m3u_path = f"{playlist_path}{playlist_tags['name']}.m3u"

        m3u_writer = M3UPlaylistWriter(
            extended=settings.global_settings.playlist.extended_m3u,
            path_mode=settings.global_settings.playlist.paths_m3u,
        )
        await m3u_writer.create(m3u_path)
        return m3u_path

    async def _add_to_m3u(
        self, m3u_path: str, track_info: TrackInfo, track_location: str
    ) -> None:
        """Add track to M3U playlist."""
        m3u_writer = M3UPlaylistWriter(
            extended=settings.global_settings.playlist.extended_m3u,
            path_mode=settings.global_settings.playlist.paths_m3u,
        )
        await m3u_writer.add_track(m3u_path, track_info, track_location)

    async def _prepare_track_location(
        self,
        track_info: TrackInfo,
        download_location: str,
        module: ModuleBase,
        module_name: str,
    ) -> tuple[str, str]:
        """Prepare track file location."""
        if settings.global_settings.formatting.force_album_format:
            album_info = await module.get_album_info(track_info.album_id)
            if album_info:
                download_location = self._path_builder.build_album_path(
                    track_info.album_id, album_info
                )
                await self._download_album_assets(
                    download_location, album_info, module_name
                )

        track_location_name = self._path_builder.build_track_path(
            track_info, download_location, DownloadTypeEnum.track
        )
        return track_location_name, download_location

    async def _download_track_file(
        self,
        track_id: str,
        track_info: TrackInfo,
        track_location: str,
        track_location_name: str,
        codec: CodecEnum,
        container: ContainerEnum,
        module: ModuleBase,
    ) -> tuple[str | None, CodecEnum, ContainerEnum]:
        """Download the actual track file."""
        # Set current task for progress reporting
        set_current_task(track_id)
        try:
            download_info: TrackDownloadInfo = await module.get_track_download(
                target_path=track_location,
                url=track_info.download_url or "",
                data=track_info.download_data,
            )

            match download_info.download_type:
                case DownloadEnum.URL:
                    assert download_info.file_url is not None
                    await download_file(
                        download_info.file_url,
                        track_location,
                        headers=download_info.file_url_headers,
                        task_id=track_id,
                    )
                case DownloadEnum.TEMP_FILE_PATH:
                    assert download_info.temp_file_path is not None
                    shutil.move(download_info.temp_file_path, track_location)
                case DownloadEnum.DIRECT:
                    pass

            if download_info.different_codec:
                codec = download_info.different_codec
                container = codec.container
                old_location = track_location
                track_location = f"{track_location_name}.{container.name}"
                shutil.move(old_location, track_location)

            return track_location, codec, container

        except KeyboardInterrupt:
            print("^C pressed, exiting")
            sys.exit(0)
        except Exception as e:
            if settings.global_settings.advanced.debug_mode:
                raise
            if settings.global_settings.advanced.abort_download_when_single_failed:
                raise TrackDownloadError(track_id, str(e)) from e
            print(f"Warning: Track download failed: {e}")
            return None, codec, container
        finally:
            set_current_task(None)

    async def _download_cover(
        self, track_info: TrackInfo, track_location_name: str, module_name: str
    ) -> Path | None:
        """Download track cover art."""
        cover_temp = await self._temp.path()
        third_party = self._third_party_modules.get(ModuleModes.covers)

        if third_party and third_party != module_name:
            return await self._download_cover_third_party(
                track_info, track_location_name, third_party, cover_temp
            )

        artwork_settings = self._get_artwork_settings(module_name)
        await download_file(
            track_info.cover_url,
            str(cover_temp),
            artwork_settings=msgspec.structs.asdict(artwork_settings),
        )
        return cover_temp

    async def _download_cover_third_party(
        self,
        track_info: TrackInfo,
        track_location_name: str,
        module_name: str,
        cover_temp: Path,
    ) -> Path:
        """Download cover using third-party module."""
        default_temp = await self._temp.download(track_info.cover_url)
        test_options = CoverOptions(
            file_type=ImageFileTypeEnum.jpg,
            resolution=get_image_resolution(str(default_temp)),
            compression=CoverCompressionEnum.high,
        )

        cover_module = self._loaded_modules[module_name]
        rms_threshold = settings.global_settings.advanced.cover_variance_threshold
        results = await self._search_by_tags(module_name, track_info)

        for result in results:
            test_cover = await cover_module.get_track_cover(
                result.result_id, test_options, data=result.data
            )
            test_temp = await self._temp.download(test_cover.url)
            rms = compare_images(str(default_temp), str(test_temp))

            if rms < rms_threshold:
                jpg_options = CoverOptions(
                    file_type=ImageFileTypeEnum.jpg,
                    resolution=settings.global_settings.covers.main_resolution,
                    compression=CoverCompressionEnum[
                        settings.global_settings.covers.main_compression.lower()
                    ],
                )
                jpg_cover = await cover_module.get_track_cover(
                    result.result_id, jpg_options, data=result.data
                )
                artwork_settings = self._get_artwork_settings(module_name)
                await download_file(
                    jpg_cover.url,
                    str(cover_temp),
                    artwork_settings=msgspec.structs.asdict(artwork_settings),
                )
                return cover_temp

        # Fallback to default cover
        shutil.move(str(default_temp), str(cover_temp))
        return cover_temp

    async def _search_by_tags(
        self, module_name: str, track_info: TrackInfo
    ) -> list[SearchResult]:
        """Search for a track by its tags."""
        query = f"{track_info.name} {' '.join(track_info.artists)}"
        module = await self._get_module_by_name(module_name)
        return await module.search(DownloadTypeEnum.track, query, track_info=track_info)

    async def _get_module_by_name(self, module_name: str) -> ModuleBase:
        """Get a module instance by name, loading if necessary.

        Args:
            module_name: The module name.

        Returns:
            The module instance.
        """
        # Try to find existing loaded module with any account index
        for key, module in self._loaded_modules.items():
            if key.startswith(f"{module_name}:"):
                return module
        # Load module with default account index 0
        return await self._load_module(module_name, 0)

    async def _get_lyrics(
        self,
        track_id: str,
        track_info: TrackInfo,
        module_name: str,
        module: ModuleBase,
    ) -> tuple[str, str | None]:
        """Retrieve lyrics for a track.

        Args:
            track_id: Track identifier.
            track_info: Track metadata.
            module_name: Name of the module.
            module: The module instance to use.

        Returns:
            Tuple of (embedded lyrics, synced lyrics).
        """
        if not (
            settings.global_settings.lyrics.embed_lyrics
            or settings.global_settings.lyrics.save_synced_lyrics
        ):
            return "", None

        lyrics_info = LyricsInfo()
        third_party = self._third_party_modules.get(ModuleModes.lyrics)

        if third_party and third_party != module_name:
            results = await self._search_by_tags(third_party, track_info)
            if results:
                third_party_module = await self._get_module_by_name(third_party)
                lyrics_info = await third_party_module.get_track_lyrics(
                    results[0].result_id, data=results[0].data
                )
        elif (
            ModuleModes.lyrics
            in self._module_settings[module_name].module_supported_modes
        ):
            lyrics_info = await module.get_track_lyrics(
                track_id, data=track_info.lyrics_data
            )

        embedded = ""
        if lyrics_info.embedded and settings.global_settings.lyrics.embed_lyrics:
            embedded = lyrics_info.embedded
        if (
            lyrics_info.synced
            and settings.global_settings.lyrics.embed_lyrics
            and settings.global_settings.lyrics.embed_synced_lyrics
        ):
            embedded = lyrics_info.synced

        return embedded, lyrics_info.synced

    async def _get_credits(
        self,
        track_id: str,
        track_info: TrackInfo,
        module_name: str,
        module: ModuleBase,
    ) -> list[Any]:
        """Retrieve credits for a track.

        Args:
            track_id: Track identifier.
            track_info: Track metadata.
            module_name: Name of the module.
            module: The module instance to use.

        Returns:
            List of CreditsInfo objects.
        """
        third_party = self._third_party_modules.get(ModuleModes.credits)

        if third_party and third_party != module_name:
            results = await self._search_by_tags(third_party, track_info)
            if results:
                third_party_module = await self._get_module_by_name(third_party)
                return await third_party_module.get_track_credits(
                    results[0].result_id, data=results[0].data
                )
            return []

        if (
            ModuleModes.credits
            in self._module_settings[module_name].module_supported_modes
        ):
            return await module.get_track_credits(
                track_id, data=track_info.credits_data
            )
        return []

    async def _convert_if_needed(
        self,
        track_location: str,
        track_location_name: str,
        codec: CodecEnum,
        container: ContainerEnum,
    ) -> ConversionResult:
        """Convert track if conversion is configured."""
        conversions = self._get_codec_conversions()

        if codec not in conversions:
            return ConversionResult(track_location=track_location, container=container)

        new_codec = conversions[codec]
        print(f"Converting to {new_codec.pretty_name}")

        # Validate conversion
        if codec.spatial or new_codec.spatial:
            print("Warning: converting spatial formats not allowed")
            return ConversionResult(track_location=track_location, container=container)

        if (
            not codec.lossless
            and new_codec.lossless
            and not settings.global_settings.advanced.enable_undesirable_conversions
        ):
            print("Warning: lossy-to-lossless conversion skipped")
            return ConversionResult(track_location=track_location, container=container)

        # Get conversion flags
        try:
            conversion_flags = {
                CodecEnum[k.upper()]: v
                for k, v in settings.global_settings.advanced.conversion_flags.items()
            }
        except KeyError:
            conversion_flags = {}

        conv_flags = conversion_flags.get(new_codec, {})
        new_track_location = f"{track_location_name}.{new_codec.container.name}"

        async with self._temp.file(suffix=f".{new_codec.container.name}") as temp_path:
            try:
                await asyncio.to_thread(
                    transcode, track_location, str(temp_path), new_codec, conv_flags
                )
            except Exception as e:
                raise ConversionError(codec.name, new_codec.name, str(e)) from e
            shutil.copy2(str(temp_path), new_track_location)

        if (
            not settings.global_settings.advanced.conversion_keep_original
            and track_location != new_track_location
        ):
            Path(track_location).unlink(missing_ok=True)

        return ConversionResult(
            track_location=new_track_location,
            container=new_codec.container,
        )
