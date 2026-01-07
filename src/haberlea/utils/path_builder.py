"""Path building utilities for music downloads.

This module provides path construction functionality for organizing
downloaded music files into appropriate directory structures.
"""

import unicodedata
from typing import Any

import msgspec

from .models import AlbumInfo, DownloadTypeEnum, PlaylistInfo, TrackInfo
from .settings import settings
from .utils import fix_byte_limit, sanitise_name


def get_artist_initials(artist_name: str) -> str:
    """Extract artist initials for folder organization.

    Args:
        artist_name: The artist name.

    Returns:
        Single character initial (uppercase letter or '#').
    """
    initial = artist_name.lower()
    if initial.startswith("the "):
        initial = initial[4:]

    if not initial:
        return "#"

    # Normalize unicode characters
    initial = (
        unicodedata.normalize("NFKD", initial[0])
        .encode("ascii", "ignore")
        .decode("utf-8")
    )

    return initial.upper() if initial.isalpha() else "#"


def build_track_tags(
    track_info: TrackInfo,
    zfill_enabled: bool,
    zfill_number: int,
) -> dict[str, Any]:
    """Build sanitized track tags for path formatting.

    Args:
        track_info: Track information.
        zfill_enabled: Whether to zero-fill numeric fields.
        zfill_number: Number of digits for zero-filling.

    Returns:
        Dictionary of sanitized tags.
    """
    zfill_fields = {"track_number", "total_tracks", "disc_number", "total_discs"}

    def process_value(key: str, value: Any) -> Any:
        if value is None:
            return None
        if zfill_enabled and key in zfill_fields:
            return sanitise_name(str(value)).zfill(zfill_number)
        # Convert non-string values to string before sanitizing
        if not isinstance(value, str):
            value = str(value)
        return sanitise_name(value)

    tags = {
        k: process_value(k, v) for k, v in msgspec.structs.asdict(track_info).items()
    }
    # Merge Tags fields directly
    tags.update(
        {
            k: process_value(k, v)
            for k, v in msgspec.structs.asdict(track_info.tags).items()
        }
    )
    tags["explicit"] = " [E]" if track_info.explicit else ""
    tags["artist"] = (
        sanitise_name(track_info.artists[0]) if track_info.artists else "Unknown Artist"
    )
    return tags


class PathBuilder:
    """Handles path construction for downloads."""

    def __init__(self, base_path: str) -> None:
        """Initialize path builder.

        Args:
            base_path: Base download path.
        """
        self._base_path = base_path if base_path.endswith("/") else base_path + "/"

    @property
    def base_path(self) -> str:
        """Get the base download path."""
        return self._base_path

    def build_album_path(self, album_id: str, album_info: AlbumInfo) -> str:
        """Build album directory path.

        Args:
            album_id: Album identifier.
            album_info: Album information.

        Returns:
            Full album directory path.
        """
        album_tags = {
            k: sanitise_name(v) for k, v in msgspec.structs.asdict(album_info).items()
        }
        album_tags["id"] = str(album_id)
        album_tags["quality"] = f" [{album_info.quality}]" if album_info.quality else ""
        album_tags["explicit"] = " [E]" if album_info.explicit else ""
        album_tags["artist_initials"] = get_artist_initials(album_info.artist)

        try:
            album_path = (
                f"{self._base_path}"
                f"{settings.global_settings.formatting.album_format.format(**album_tags)}"
            )
        except (KeyError, ValueError):
            # Fallback to safe default format if user format has missing keys
            album_path = (
                f"{self._base_path}{album_tags['artist']}/"
                f"{album_tags['name']}{album_tags['explicit']}"
            )
        album_path = fix_byte_limit(album_path) + "/"

        return album_path

    def build_playlist_path(self, playlist_info: PlaylistInfo) -> str:
        """Build playlist directory path.

        Args:
            playlist_info: Playlist information.

        Returns:
            Full playlist directory path.
        """
        playlist_tags = {
            k: sanitise_name(v)
            for k, v in msgspec.structs.asdict(playlist_info).items()
        }
        playlist_tags["explicit"] = " [E]" if playlist_info.explicit else ""

        try:
            playlist_path = (
                f"{self._base_path}"
                f"{settings.global_settings.formatting.playlist_format.format(**playlist_tags)}"
            )
        except (KeyError, ValueError):
            # Fallback to safe default format
            playlist_path = (
                f"{self._base_path}{playlist_tags['name']}{playlist_tags['explicit']}"
            )
        playlist_path = fix_byte_limit(playlist_path) + "/"

        return playlist_path

    def build_track_path(
        self,
        track_info: TrackInfo,
        album_location: str,
        download_mode: DownloadTypeEnum,
    ) -> str:
        """Build track file path (without extension).

        Args:
            track_info: Track information.
            album_location: Album directory path.
            download_mode: Current download mode.

        Returns:
            Full track file path without extension.
        """
        zfill_number = (
            len(str(track_info.tags.total_tracks))
            if download_mode is not DownloadTypeEnum.track
            else 1
        )
        track_tags = build_track_tags(
            track_info,
            settings.global_settings.formatting.enable_zfill,
            zfill_number,
        )

        if (
            download_mode is DownloadTypeEnum.track
            and not settings.global_settings.formatting.force_album_format
        ):
            try:
                single_fmt = settings.global_settings.formatting.single_full_path_format
                track_location_name = (
                    f"{self._base_path}{single_fmt.format(**track_tags)}"
                )
            except (KeyError, ValueError):
                # Fallback to safe default format
                track_location_name = (
                    f"{self._base_path}{track_tags['artist']}/{track_tags['name']}"
                    f"{track_tags['explicit']}"
                )
        elif (
            track_info.tags.total_tracks == 1
            and not settings.global_settings.formatting.force_album_format
        ):
            try:
                single_fmt = settings.global_settings.formatting.single_full_path_format
                track_location_name = (
                    f"{album_location}{single_fmt.format(**track_tags)}"
                )
            except (KeyError, ValueError):
                # Fallback to safe default format
                track_location_name = (
                    f"{album_location}{track_tags['name']}{track_tags['explicit']}"
                )
        else:
            location = album_location
            if track_info.tags.total_discs and track_info.tags.total_discs > 1:
                location += f"CD {track_info.tags.disc_number}/"
            try:
                track_location_name = (
                    f"{location}"
                    f"{settings.global_settings.formatting.track_filename_format.format(**track_tags)}"
                )
            except (KeyError, ValueError):
                # Fallback to safe default format
                track_location_name = (
                    f"{location}{track_tags['track_number']} - "
                    f"{track_tags['name']}{track_tags['explicit']}"
                )

        track_location_name = fix_byte_limit(track_location_name)

        return track_location_name
