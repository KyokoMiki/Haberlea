"""Base classes for Haberlea plugins.

This module defines the abstract base classes that all modules and extensions
must implement to be compatible with the Haberlea plugin system.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from haberlea.utils.models import (
        AlbumInfo,
        ArtistInfo,
        CodecOptions,
        CoverInfo,
        CoverOptions,
        CreditsInfo,
        DownloadTypeEnum,
        LyricsInfo,
        ModuleController,
        PlaylistInfo,
        QualityEnum,
        SearchResult,
        TrackDownloadInfo,
        TrackInfo,
    )


class ModuleBase(ABC):
    """Abstract base class for music service modules.

    All modules must inherit from this class to be compatible with Haberlea.
    Modules handle authentication, metadata retrieval, and track downloading
    from music streaming services.
    """

    def __init__(self, module_controller: "ModuleController") -> None:
        """Initialize the module.

        Args:
            module_controller: Controller providing access to settings and resources.
        """
        self.module_controller = module_controller

    async def close(self) -> None:
        """Close the module and release resources."""
        return None

    async def login(self, email: str, password: str) -> None:
        """Authenticate with the music service.

        Args:
            email: User email or username.
            password: User password.
        """
        return None

    @abstractmethod
    async def get_track_info(
        self,
        track_id: str,
        quality_tier: "QualityEnum",
        codec_options: "CodecOptions",
        data: dict[str, Any] | None = None,
    ) -> "TrackInfo":
        """Get track metadata and streaming information.

        Args:
            track_id: Unique identifier for the track.
            quality_tier: Desired audio quality.
            codec_options: Codec preference options.
            data: Optional pre-fetched track data.

        Returns:
            TrackInfo containing metadata and download information.
        """
        ...

    @abstractmethod
    async def get_track_download(
        self,
        target_path: str,
        url: str = "",
        data: "dict | None" = None,
    ) -> "TrackDownloadInfo":
        """Get download information for a track.

        Args:
            target_path: Target file path for direct download.
            url: The URL to download the track from.
            data: Optional extra data for download (e.g., audio_track, file_url).

        Returns:
            TrackDownloadInfo with download URL or file path.
        """
        ...

    async def search(
        self,
        query_type: "DownloadTypeEnum",
        query: str,
        track_info: "TrackInfo | None" = None,
        limit: int = 10,
    ) -> "list[SearchResult]":
        """Search for content on the service.

        Args:
            query_type: Type of content to search for.
            query: Search query string.
            track_info: Optional track info for ISRC-based search.
            limit: Maximum number of results.

        Returns:
            List of search results.
        """
        return []

    def custom_url_parse(self, url: str) -> Any:
        """Parse a custom URL format for this service.

        Args:
            url: The URL to parse.

        Returns:
            MediaIdentification or similar object with parsed media info.
        """
        return None

    async def get_album_info(
        self, album_id: str, data: dict[str, Any] | None = None
    ) -> "AlbumInfo":
        """Get album metadata and track list.

        Args:
            album_id: Unique identifier for the album.
            data: Optional pre-fetched album data.

        Returns:
            AlbumInfo containing metadata and track list.
        """
        raise NotImplementedError

    async def get_playlist_info(self, playlist_id: str) -> "PlaylistInfo":
        """Get playlist metadata and track list.

        Args:
            playlist_id: Unique identifier for the playlist.

        Returns:
            PlaylistInfo containing metadata and track list.
        """
        raise NotImplementedError

    async def get_artist_info(
        self, artist_id: str, get_credited_albums: bool = False
    ) -> "ArtistInfo":
        """Get artist metadata and discography.

        Args:
            artist_id: Unique identifier for the artist.
            get_credited_albums: Whether to include albums where artist is credited.

        Returns:
            ArtistInfo containing metadata and album/track lists.
        """
        raise NotImplementedError

    async def get_track_cover(
        self,
        track_id: str,
        cover_options: "CoverOptions",
        data: dict[str, Any] | None = None,
    ) -> "CoverInfo":
        """Get track cover image information.

        Args:
            track_id: Unique identifier for the track.
            cover_options: Cover image options (resolution, format, etc.).
            data: Optional pre-fetched data.

        Returns:
            CoverInfo with cover URL and file type.
        """
        raise NotImplementedError

    async def get_track_lyrics(
        self, track_id: str, data: dict[str, Any] | None = None
    ) -> "LyricsInfo":
        """Get track lyrics.

        Args:
            track_id: Unique identifier for the track.
            data: Optional pre-fetched data.

        Returns:
            LyricsInfo with embedded and/or synced lyrics.
        """
        raise NotImplementedError

    async def get_track_credits(
        self, track_id: str, data: dict[str, Any] | None = None
    ) -> "list[CreditsInfo]":
        """Get track credits information.

        Args:
            track_id: Unique identifier for the track.
            data: Optional pre-fetched data.

        Returns:
            List of CreditsInfo with contributor information.
        """
        return []


class ExtensionBase(ABC):
    """Abstract base class for post-download extensions."""

    def __init__(self, settings: dict[str, Any]) -> None:
        """Initialize the extension.

        Args:
            settings: Extension-specific configuration dictionary.
        """
        self.settings = settings

    @abstractmethod
    async def call_extension(self, download_path: str) -> None:
        """Execute the extension for a completed album/playlist download.

        Args:
            download_path: Path to the downloaded album/playlist directory.
        """
        ...

    async def finalize(self) -> None:
        """Finalize the extension after all downloads are complete.

        This method is called once after all download tasks and per-album extension
        calls have finished. Useful for batch operations like uploading all
        downloaded files together.
        """
        return None
