"""M3U playlist file utilities.

This module provides functionality for creating and managing M3U playlist files.
"""

import os

import aiofiles

from .models import TrackInfo


class M3UPlaylistWriter:
    """Handles M3U playlist file operations."""

    def __init__(self, extended: bool, path_mode: str) -> None:
        """Initialize playlist writer.

        Args:
            extended: Whether to use extended M3U format.
            path_mode: Path mode ('absolute' or 'relative').
        """
        self.extended = extended
        self.path_mode = path_mode

    async def create(self, playlist_path: str) -> None:
        """Create empty playlist file with optional header.

        Args:
            playlist_path: Path to the playlist file.
        """
        async with aiofiles.open(playlist_path, "w", encoding="utf-8") as f:
            if self.extended:
                await f.write("#EXTM3U\n\n")
            else:
                await f.write("")

    async def add_track(
        self,
        playlist_path: str,
        track_info: TrackInfo,
        track_location: str,
    ) -> None:
        """Add a track entry to the playlist.

        Args:
            playlist_path: Path to the playlist file.
            track_info: Track information.
            track_location: Path to the track file.
        """
        async with aiofiles.open(playlist_path, "a", encoding="utf-8") as f:
            if self.extended:
                duration = track_info.duration or -1
                await f.write(
                    f"#EXTINF:{duration}, {track_info.artists[0]} - {track_info.name}\n"
                )

            match self.path_mode:
                case "absolute":
                    await f.write(f"{os.path.abspath(track_location)}\n")
                case "relative":
                    rel_path = os.path.relpath(
                        track_location, os.path.dirname(playlist_path)
                    )
                    await f.write(f"{rel_path}\n")

            if self.extended:
                await f.write("\n")
