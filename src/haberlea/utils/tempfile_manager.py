"""Modern temporary file management for Haberlea.

This module provides a centralized, type-safe, and context-managed approach
to temporary file handling using anyio for native async support.

Features:
- Native async temporary file/directory operations via anyio
- Automatic cleanup via async context managers
- pathlib.Path integration
- Proper resource management
- Configurable base directory from settings
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from anyio import NamedTemporaryFile, TemporaryDirectory

from .settings import settings
from .utils import delete_path, download_file


class TempFileManager:
    """Centralized temporary file manager with automatic cleanup.

    This class provides a modern, async-native approach to temporary file
    handling using anyio. All temporary files created through this manager
    are tracked and automatically cleaned up when the manager exits its context.

    Example:
        ```python
        async with TempFileManager() as tmp:
            # Temporary file with auto-cleanup via context manager
            async with tmp.file(suffix=".flac") as path:
                await download_file(url, str(path))
                process_file(path)
            # File is automatically deleted when exiting inner context

            # Temporary directory with auto-cleanup
            async with tmp.dir() as dir_path:
                file1 = dir_path / "segment_001.mp4"
                file2 = dir_path / "segment_002.mp4"
            # Directory and contents are automatically deleted

            # Download directly to temp (tracked for cleanup)
            cover_path = await tmp.download(url, suffix=".jpg")
            # ... use cover_path ...
        # All remaining tracked files are cleaned up on exit
        ```
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        prefix: str = "haberlea_",
    ) -> None:
        """Initialize the temporary file manager.

        Args:
            base_dir: Base directory for temporary files. If None, uses the
                temp_path from settings, or system temp directory if not configured.
            prefix: Prefix for temporary file/directory names.
        """
        if base_dir:
            self._base_dir = Path(base_dir)
        else:
            # Use temp_path from settings if configured, otherwise system temp
            temp_path = settings.global_settings.general.temp_path
            self._base_dir = Path(temp_path) if temp_path else Path(gettempdir())
        
        # Ensure base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)
        
        self._prefix = prefix
        self._tracked_paths: set[Path] = set()

    async def __aenter__(self) -> "TempFileManager":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager and cleanup all tracked resources."""
        await self.cleanup()

    @asynccontextmanager
    async def file(
        self,
        suffix: str = "",
        prefix: str | None = None,
    ) -> AsyncIterator[Path]:
        """Create a temporary file with automatic cleanup.

        Args:
            suffix: File suffix (e.g., ".flac", ".jpg").
            prefix: File prefix. Defaults to manager's prefix.

        Yields:
            Path to the temporary file.
        """
        file_prefix = prefix or self._prefix
        async with NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            prefix=file_prefix,
            dir=str(self._base_dir),
            delete=False,
        ) as f:
            path = Path(str(f.name))
            self._tracked_paths.add(path)
            try:
                yield path
            finally:
                await delete_path(path)
                self._tracked_paths.discard(path)

    @asynccontextmanager
    async def dir(
        self,
        suffix: str = "",
        prefix: str | None = None,
    ) -> AsyncIterator[Path]:
        """Create a temporary directory with automatic cleanup.

        Args:
            suffix: Directory suffix.
            prefix: Directory prefix. Defaults to manager's prefix.

        Yields:
            Path to the temporary directory.
        """
        dir_prefix = prefix or self._prefix
        async with TemporaryDirectory(
            suffix=suffix,
            prefix=dir_prefix,
            dir=str(self._base_dir),
        ) as temp_dir_path:
            path = Path(str(temp_dir_path))
            self._tracked_paths.add(path)
            try:
                yield path
            finally:
                self._tracked_paths.discard(path)

    async def path(self, suffix: str = "", prefix: str | None = None) -> Path:
        """Create a temporary file path without creating the file.

        The caller is responsible for cleanup via remove().

        Args:
            suffix: File suffix.
            prefix: File prefix. Defaults to manager's prefix.

        Returns:
            Path to a non-existent temporary file location.
        """
        file_prefix = prefix or self._prefix
        # Use UUID4 for guaranteed uniqueness
        unique_id = uuid.uuid4().hex
        filename = f"{file_prefix}{unique_id}{suffix}"
        path = self._base_dir / filename

        self._tracked_paths.add(path)
        return path

    async def save(
        self,
        data: bytes,
        suffix: str = "",
        prefix: str | None = None,
    ) -> Path:
        """Save bytes to a temporary file.

        Args:
            data: Bytes to save.
            suffix: File suffix.
            prefix: File prefix.

        Returns:
            Path to the temporary file containing the data.
        """
        file_prefix = prefix or self._prefix
        async with NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            prefix=file_prefix,
            dir=str(self._base_dir),
            delete=False,
        ) as f:
            await f.write(data)
            path = Path(str(f.name))
            self._tracked_paths.add(path)
            return path

    async def download(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        suffix: str = "",
        session: Any = None,
        task_id: str | None = None,
    ) -> Path:
        """Download a file to a temporary location.

        Args:
            url: URL to download from.
            headers: Optional HTTP headers.
            suffix: File suffix (e.g., ".jpg", ".flac").
            session: Optional aiohttp session to reuse.
            task_id: Optional task ID for progress reporting.

        Returns:
            Path to the downloaded temporary file.
        """
        path = await self.path(suffix=suffix)
        await download_file(
            url,
            str(path),
            headers=headers,
            session=session,
            task_id=task_id,
        )
        return path

    def get_temp_filename(self, suffix: str = "", prefix: str | None = None) -> Path:
        """Generate a temporary file path without tracking or creating the file.

        The caller is responsible for creating and cleaning up the file.
        This method does not track the path for automatic cleanup.

        Args:
            suffix: File suffix (e.g., ".flac", ".jpg").
            prefix: File prefix. Defaults to manager's prefix.

        Returns:
            Path to a non-existent temporary file location.
        """
        file_prefix = prefix or self._prefix
        unique_id = uuid.uuid4().hex
        filename = f"{file_prefix}{unique_id}{suffix}"
        return self._base_dir / filename

    def get_temp_dirname(self, suffix: str = "", prefix: str | None = None) -> Path:
        """Generate a temporary directory path without tracking or creating it.

        The caller is responsible for creating and cleaning up the directory.
        This method does not track the path for automatic cleanup.

        Args:
            suffix: Directory suffix.
            prefix: Directory prefix. Defaults to manager's prefix.

        Returns:
            Path to a non-existent temporary directory location.
        """
        dir_prefix = prefix or self._prefix
        unique_id = uuid.uuid4().hex
        dirname = f"{dir_prefix}{unique_id}{suffix}"
        return self._base_dir / dirname

    async def cleanup(self) -> None:
        """Clean up all tracked temporary files and directories."""
        for path in list(self._tracked_paths):
            await delete_path(path)
        self._tracked_paths.clear()
