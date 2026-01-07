"""Global state management for Haberlea WebUI using NiceGUI app.storage and msgspec."""

from typing import TYPE_CHECKING, Any

import msgspec
from nicegui import app

if TYPE_CHECKING:
    from .pages.download import DownloadPage
    from .pages.logs import LogsPage
    from .pages.search import SearchPage
    from .pages.settings import SettingsPage


class DownloadTask(msgspec.Struct, kw_only=True, dict=True):
    """Represents a download task in the queue.

    Attributes:
        url: The download URL.
        status: Task status (pending, downloading, completed, failed).
        progress: Download progress from 0.0 to 1.0.
        message: Status message or error description.
        media_type: Type of media (track, album, playlist, artist).
        media_id: Media identifier.
        service: Service name (qobuz, tidal, etc.).
        data: Pre-fetched data for the download task.
    """

    url: str
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    media_type: str = ""
    media_id: str = ""
    service: str = ""
    data: dict[str, Any] | None = None


class UserPreferences(msgspec.Struct, kw_only=True, dict=True):
    """User preferences stored per browser session.

    Attributes:
        dark_mode: Whether dark mode is enabled.
        sidebar_open: Whether sidebar is expanded.
    """

    dark_mode: bool = False
    sidebar_open: bool = True


class AppStorage(msgspec.Struct, kw_only=True, dict=True):
    """Application-wide storage container.

    Attributes:
        download_queue: List of download tasks.
        logs: Application log messages.
        is_downloading: Whether a download is in progress.
    """

    download_queue: list[dict[str, Any]] = msgspec.field(default_factory=list)
    logs: list[str] = msgspec.field(default_factory=list)
    is_downloading: bool = False


def task_to_dict(task: DownloadTask) -> dict[str, Any]:
    """Converts a DownloadTask to a dictionary.

    Args:
        task: The DownloadTask instance.

    Returns:
        Dictionary representation of the task.
    """
    return msgspec.structs.asdict(task)


def dict_to_task(data: dict[str, Any]) -> DownloadTask:
    """Converts a dictionary to a DownloadTask.

    Args:
        data: Dictionary with task data.

    Returns:
        DownloadTask instance.
    """
    return msgspec.convert(data, DownloadTask)


def get_app_storage() -> dict[str, Any]:
    """Gets the application-wide storage from NiceGUI.

    Returns:
        The app.storage.general dictionary for persistent storage.
    """
    if "haberlea" not in app.storage.general:
        app.storage.general["haberlea"] = {
            "download_queue": [],
            "logs": [],
            "is_downloading": False,
        }
    return app.storage.general["haberlea"]


def get_user_storage() -> dict[str, Any]:
    """Gets the user-specific storage from NiceGUI.

    Returns:
        The app.storage.user dictionary for user-specific data.
    """
    if "preferences" not in app.storage.user:
        app.storage.user["preferences"] = {
            "dark_mode": False,
            "sidebar_open": True,
        }
    return app.storage.user["preferences"]


def create_download_task(
    url: str,
    service: str = "",
    media_type: str = "",
    media_id: str = "",
    data: dict[str, Any] | None = None,
) -> DownloadTask:
    """Creates a new DownloadTask instance.

    Args:
        url: The download URL.
        service: The service name.
        media_type: The media type (track, album, etc.).
        media_id: The media ID.
        data: Pre-fetched data for the download task.

    Returns:
        The created DownloadTask instance.
    """
    return DownloadTask(
        url=url,
        service=service,
        media_type=media_type,
        media_id=media_id,
        data=data,
    )


def add_download_task(
    url: str,
    service: str = "",
    media_type: str = "",
    media_id: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adds a new download task to the queue.

    Args:
        url: The download URL.
        service: The service name.
        media_type: The media type (track, album, etc.).
        media_id: The media ID.
        data: Pre-fetched data for the download task.

    Returns:
        The created task as a dictionary.
    """
    storage = get_app_storage()
    task = create_download_task(url, service, media_type, media_id, data)
    task_dict = task_to_dict(task)
    storage["download_queue"].append(task_dict)
    return task_dict


def get_task(index: int) -> DownloadTask | None:
    """Gets a download task by index.

    Args:
        index: The task index in the queue.

    Returns:
        The DownloadTask instance or None if not found.
    """
    storage = get_app_storage()
    if 0 <= index < len(storage["download_queue"]):
        return dict_to_task(storage["download_queue"][index])
    return None


def update_task_status(
    index: int,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
) -> None:
    """Updates a download task's status.

    Args:
        index: The task index in the queue.
        status: New status value.
        progress: New progress value (0.0-1.0).
        message: New message value.
    """
    storage = get_app_storage()
    if 0 <= index < len(storage["download_queue"]):
        task = storage["download_queue"][index]
        if status is not None:
            task["status"] = status
        if progress is not None:
            task["progress"] = progress
        if message is not None:
            task["message"] = message


def remove_task(index: int) -> None:
    """Removes a task from the download queue.

    Args:
        index: The task index to remove.
    """
    storage = get_app_storage()
    if 0 <= index < len(storage["download_queue"]):
        storage["download_queue"].pop(index)


def add_log(message: str) -> None:
    """Adds a log message.

    Args:
        message: The log message to add.
    """
    storage = get_app_storage()
    storage["logs"].append(message)
    # Keep only last 500 logs
    if len(storage["logs"]) > 500:
        storage["logs"] = storage["logs"][-500:]


def clear_logs() -> None:
    """Clears all log messages."""
    storage = get_app_storage()
    storage["logs"] = []


class PageInstances(msgspec.Struct):
    """Container for page instances with type hints.

    Core pages are typed explicitly, extension pages are stored in a dict.

    Attributes:
        download: The download page instance.
        search: The search page instance.
        settings: The settings page instance.
        logs: The logs page instance.
        extensions: Dictionary of extension page instances by page_id.
    """

    download: "DownloadPage | None" = None
    search: "SearchPage | None" = None
    settings: "SettingsPage | None" = None
    logs: "LogsPage | None" = None
    extensions: dict[str, Any] = msgspec.field(default_factory=dict)


# Page instances registry for cross-page communication
_pages = PageInstances()


def register_page(name: str, instance: Any) -> None:
    """Registers a page instance for cross-page access.

    Args:
        name: The page name identifier (download, search, settings, logs,
              or extension page_id).
        instance: The page instance.
    """
    if hasattr(_pages, name):
        object.__setattr__(_pages, name, instance)
    else:
        # Store extension pages in the extensions dict
        _pages.extensions[name] = instance


def get_pages() -> PageInstances:
    """Gets the page instances container.

    Returns:
        The PageInstances struct with all registered pages.
    """
    return _pages
