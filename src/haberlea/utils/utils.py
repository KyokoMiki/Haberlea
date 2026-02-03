"""Utility functions for Haberlea.

This module provides common utility functions used throughout the application,
including file operations, HTTP session management, and image processing.
"""

import errno
import hashlib
import logging
import math
import operator
import os
import re
import shutil
import zipfile
from collections.abc import Callable
from functools import reduce
from pathlib import Path
from typing import Any

import aiohttp
import anyio
import msgspec
from asyncer import asyncify
from PIL import Image, ImageChops
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import InvalidHashTypeError, TemporarySettingsError
from .progress import ProgressMode, advance, get_current_task, reset, update

logger = logging.getLogger(__name__)


def hash_string(input_str: str, hash_type: str = "BLAKE2B") -> str:
    """Hashes a string using the specified hash algorithm.

    Args:
        input_str: The string to hash.
        hash_type: The hash algorithm to use. Defaults to "BLAKE2B".
            Supported: "BLAKE2B" (recommended, fast & secure),
                      "MD5" (legacy, platform requirement).

    Returns:
        The hexadecimal digest of the hash.

    Raises:
        InvalidHashTypeError: If an invalid hash type is selected.
    """
    hash_type_upper = hash_type.upper()
    if hash_type_upper == "BLAKE2B":
        return hashlib.blake2b(input_str.encode("utf-8")).hexdigest()
    elif hash_type_upper == "MD5":
        # MD5 is insecure but kept for platform API compatibility (e.g., Qobuz)
        return hashlib.md5(input_str.encode("utf-8")).hexdigest()
    else:
        raise InvalidHashTypeError(hash_type, supported_types=["BLAKE2B", "MD5"])


def create_aiohttp_session(
    timeout: int = 30,
    connector_limit: int = 100,
    read_bufsize: int = 2**20,
) -> aiohttp.ClientSession:
    """Creates an aiohttp ClientSession with connection pool settings.

    Args:
        timeout: Socket read timeout in seconds (time to wait for data chunks).
        connector_limit: Maximum number of concurrent connections.
        read_bufsize: Size of the read buffer in bytes. Defaults to 1 MiB.

    Returns:
        A configured aiohttp ClientSession.
    """
    timeout_config = aiohttp.ClientTimeout(total=None, sock_read=timeout)
    connector = aiohttp.TCPConnector(
        limit=connector_limit,
        ssl=False,
        enable_cleanup_closed=True,
    )
    return aiohttp.ClientSession(
        timeout=timeout_config,
        connector=connector,
        read_bufsize=read_bufsize,
    )


def sanitise_name(name: str | None) -> str:
    """Sanitizes a filename by removing or replacing invalid characters.

    Args:
        name: The filename to sanitize.

    Returns:
        The sanitized filename.
    """
    return (
        re.sub(
            r"[:]",
            "_",
            re.sub(r'[\\/*?",<>|$]', "_", re.sub(r"[ \t]+$", "", str(name).rstrip())),
        )
        if name
        else ""
    )


def fix_byte_limit(path: str, byte_limit: int = 250) -> str:
    """Truncates a file path to fit within a byte limit.

    Args:
        path: The file path to truncate.
        byte_limit: Maximum byte size for the filename.

    Returns:
        The truncated file path.
    """
    rel_path = os.path.abspath(path).replace("\\", "/")
    directory, filename = os.path.split(rel_path)
    filename_bytes = filename.encode("utf-8")
    fixed_bytes = filename_bytes[:byte_limit]
    fixed_filename = fixed_bytes.decode("utf-8", "ignore")
    return directory + "/" + fixed_filename


def _process_artwork(file_location: str, artwork_settings: dict[str, Any]) -> None:
    """Process and resize artwork image.

    Args:
        file_location: Path to the image file.
        artwork_settings: Settings for resizing artwork.
    """
    if not artwork_settings.get("should_resize", False):
        return

    new_resolution = artwork_settings.get("resolution", 1400)
    new_format = artwork_settings.get("format", "jpeg")
    if new_format == "jpg":
        new_format = "jpeg"

    new_compression = artwork_settings.get("compression", "low")
    if new_compression == "low":
        new_compression = 90
    elif new_compression == "high":
        new_compression = 70

    if new_format == "png":
        new_compression = None

    with Image.open(file_location) as im:
        im = im.resize((new_resolution, new_resolution), Image.Resampling.BICUBIC)
        im.save(file_location, new_format, quality=new_compression)


@retry(
    retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=0.4, min=0.4, max=60),
    reraise=True,
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _download_with_retry(
    url: str,
    file_location: str,
    headers: dict[str, str],
    session: aiohttp.ClientSession,
    task_id: str | None,
    chunk_processor: Callable[[bytes, int], bytes] | None = None,
    chunk_size: int = 1048576,
) -> None:
    """Download file with retry logic.

    Args:
        url: URL to download from.
        file_location: Local file path.
        headers: HTTP headers.
        session: aiohttp session.
        task_id: Task ID for progress reporting.
        chunk_processor: Optional callback to process each chunk before writing.
            Useful for streaming decryption during download.
        chunk_size: Size of chunks to download. Defaults to 1 MiB.
    """
    logger.debug("Starting download attempt for: %s", url)
    async with session.get(url, headers=headers, ssl=False) as response:
        response.raise_for_status()
        total = response.content_length or 0

        async with await anyio.open_file(file_location, "wb") as f:
            chunk_index = 0
            async for chunk in response.content.iter_chunked(chunk_size):
                if chunk:
                    original_len = len(chunk)
                    if chunk_processor:
                        # Run CPU-intensive decryption in thread pool
                        chunk = await asyncify(chunk_processor)(chunk, chunk_index)
                    await f.write(chunk)
                    chunk_index += 1
                    if task_id and total > 0:
                        await advance(task_id, original_len, total)


async def download_file(
    url: str,
    file_location: str,
    headers: dict[str, str] | None = None,
    artwork_settings: dict[str, Any] | None = None,
    session: aiohttp.ClientSession | None = None,
    task_id: str | None = None,
    chunk_processor: Callable[[bytes, int], bytes] | None = None,
    chunk_size: int = 1048576,
) -> None:
    """Downloads a file asynchronously using aiohttp with automatic retry.

    Progress is automatically reported through the global progress callback.
    If called within a progress context, updates are sent to that task.

    Args:
        url: The URL to download from.
        file_location: The local path to save the file.
        headers: Optional HTTP headers for the request.
        artwork_settings: Optional settings for resizing artwork.
        session: Optional aiohttp session to reuse.
        task_id: Optional task ID for progress reporting.
        chunk_processor: Optional callback to process each chunk before writing.
            Signature: (chunk: bytes, chunk_index: int) -> bytes.
            Useful for streaming decryption during download.
        chunk_size: Size of chunks to download in bytes. Defaults to 1 MiB.
            Set to match decryption block size when using chunk_processor.

    Raises:
        KeyboardInterrupt: If the download is interrupted by the user.
        aiohttp.ClientError: If the download fails after all retries.
    """
    if headers is None:
        headers = {}
    if os.path.isfile(file_location):
        return

    # Ensure parent directory exists
    parent_dir = os.path.dirname(file_location)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    close_session = False
    if session is None:
        session = create_aiohttp_session()
        close_session = True

    # Get task ID from context or parameter
    effective_task_id = task_id or get_current_task()
    if effective_task_id:
        reset(effective_task_id)
        await update(effective_task_id, mode=ProgressMode.BYTES)

    try:
        await _download_with_retry(
            url,
            file_location,
            headers,
            session,
            effective_task_id,
            chunk_processor,
            chunk_size,
        )

        if artwork_settings:
            _process_artwork(file_location, artwork_settings)
    except KeyboardInterrupt:
        if os.path.isfile(file_location):
            logger.warning('Deleting partially downloaded file "%s"', file_location)
            silentremove(file_location)
        raise KeyboardInterrupt from None
    finally:
        if close_session:
            await session.close()


def compare_images(image_1: str, image_2: str) -> float:
    """Compares two images using root mean square difference.

    Args:
        image_1: Path to the first image.
        image_2: Path to the second image.

    Returns:
        The RMS difference between the two images.
    """
    with Image.open(image_1) as im1, Image.open(image_2) as im2:
        h = ImageChops.difference(im1, im2).convert("L").histogram()
        return math.sqrt(
            reduce(operator.add, map(lambda h, i: h * (i**2), h, range(256)))
            / (float(im1.size[0]) * im1.size[1])
        )


def get_image_resolution(image_location: str) -> int:
    """Gets the width resolution of an image.

    Args:
        image_location: Path to the image file.

    Returns:
        The width of the image in pixels.
    """
    with Image.open(image_location) as img:
        return img.size[0]


def silentremove(filename: str) -> None:
    """Removes a file silently, ignoring errors if the file doesn't exist.

    Args:
        filename: Path to the file to remove.
    """
    try:
        os.remove(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def _get_module_session(
    temporary_settings: dict,
    module: str,
    global_mode: bool = False,
    session_name: str | None = None,
    create_if_missing: bool = False,
) -> dict | None:
    """Gets the session for a module from temporary settings.

    Args:
        temporary_settings: The full temporary settings dictionary.
        module: The module name.
        global_mode: Whether to use global mode.
        session_name: Specific session name to use (for multi-account support).
            If None, uses the "selected" session.
        create_if_missing: Whether to create the session if it doesn't exist.

    Returns:
        The session dictionary, or None if not found and not creating.
    """
    module_settings = temporary_settings["modules"].get(module, None)

    if module_settings:
        if global_mode:
            return module_settings
        else:
            target_session = session_name or module_settings["selected"]
            session = module_settings["sessions"].get(target_session)
            if session is None and (session_name and create_if_missing):
                module_settings["sessions"][session_name] = {}
                session = module_settings["sessions"][session_name]
            return session
    else:
        return None


def read_temporary_setting(
    settings_location: str,
    module: str,
    root_setting: str | None = None,
    setting: str | None = None,
    global_mode: bool = False,
    session_name: str | None = None,
) -> Any:
    """Reads a temporary setting from a JSON file.

    Args:
        settings_location: Path to the settings JSON file.
        module: The module name.
        root_setting: The root setting key.
        setting: The specific setting key within root_setting.
        global_mode: Whether to use global mode.
        session_name: Specific session name to use (for multi-account support).
            If None, uses the "selected" session.

    Returns:
        The setting value.

    Raises:
        TemporarySettingsError: If the module does not use temporary settings.
    """
    with open(settings_location, "rb") as f:
        temporary_settings = msgspec.json.decode(f.read())

    session = _get_module_session(
        temporary_settings, module, global_mode, session_name, create_if_missing=True
    )

    if session and root_setting:
        if setting:
            return (
                session[root_setting][setting]
                if root_setting in session and setting in session[root_setting]
                else None
            )
        else:
            return session.get(root_setting, None)
    elif root_setting and not session:
        raise TemporarySettingsError(module)
    else:
        return session


def set_temporary_setting(
    settings_location: str,
    module: str,
    root_setting: str,
    setting: str | None = None,
    value: Any = None,
    global_mode: bool = False,
    session_name: str | None = None,
) -> None:
    """Sets a temporary setting in a JSON file.

    Args:
        settings_location: Path to the settings JSON file.
        module: The module name.
        root_setting: The root setting key.
        setting: The specific setting key within root_setting.
        value: The value to set.
        global_mode: Whether to use global mode.
        session_name: Specific session name to use (for multi-account support).
            If None, uses the "selected" session.

    Raises:
        TemporarySettingsError: If the module does not use temporary settings.
    """
    with open(settings_location, "rb") as f:
        temporary_settings = msgspec.json.decode(f.read())

    session = _get_module_session(
        temporary_settings, module, global_mode, session_name, create_if_missing=True
    )

    if not session:
        raise TemporarySettingsError(module)
    if setting:
        if root_setting not in session:
            session[root_setting] = {}
        session[root_setting][setting] = value
    else:
        session[root_setting] = value
    with open(settings_location, "wb") as f:
        f.write(msgspec.json.encode(temporary_settings))


async def delete_path(path: Path) -> None:
    """Delete a file or directory asynchronously.

    Args:
        path: Path to delete (file or directory).
    """
    try:
        if path.is_dir():
            await asyncify(shutil.rmtree)(str(path))
            logger.debug("Deleted directory: %s", path)
        else:
            await anyio.Path(path).unlink(missing_ok=True)
            logger.debug("Deleted file: %s", path)
    except OSError:
        logger.exception("Failed to delete %s", path)


async def move_file(src: str | Path, dst: str | Path) -> None:
    """Move a file or directory asynchronously.

    This is an async wrapper around shutil.move that runs in a thread pool
    to avoid blocking the event loop. Handles both same-filesystem moves
    (which are instant) and cross-filesystem moves (which require copying).

    If source and destination are the same, this function does nothing.

    Args:
        src: Source path (file or directory).
        dst: Destination path.

    Raises:
        OSError: If the move operation fails.
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()

    # Skip if source and destination are the same
    if src_path == dst_path:
        logger.debug("Source and destination are the same, skipping move: %s", src)
        return

    await asyncify(shutil.move)(str(src), str(dst))
    logger.debug("Moved %s to %s", src, dst)


def compress_to_zip(
    source_paths: list[Path],
    archive_path: Path,
    compression_level: int = 0,
) -> None:
    """Compress files/directories into a ZIP archive.

    Args:
        source_paths: List of source directories/files to compress.
        archive_path: Output archive path.
        compression_level: Compression level (0-9, 0=store, 9=best). Defaults to 0.
    """
    compress_level = max(0, min(9, compression_level))
    compression = zipfile.ZIP_STORED if compress_level == 0 else zipfile.ZIP_DEFLATED

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=compression,
        compresslevel=compress_level if compress_level > 0 else None,
    ) as zf:
        for source_path in source_paths:
            if source_path.is_file():
                # Single file: add with just the filename
                zf.write(source_path, source_path.name)
            elif source_path.is_dir():
                # Directory: add all files recursively
                for file_path in source_path.rglob("*"):
                    if file_path.is_file():
                        # Preserve directory structure relative to source
                        arcname = Path(source_path.name) / file_path.relative_to(
                            source_path
                        )
                        zf.write(file_path, arcname)
