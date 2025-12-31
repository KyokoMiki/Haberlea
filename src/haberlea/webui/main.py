"""Main entry point for Haberlea WebUI."""

import logging
import sys
from typing import Any

from nicegui import app, ui

from haberlea.plugins.loader import discover_extensions

from .pages.download import DownloadPage
from .pages.logs import LogsPage
from .pages.search import SearchPage
from .pages.settings import SettingsPage
from .state import get_user_storage, register_page

logger = logging.getLogger(__name__)


def install_event_loop() -> None:
    """Installs the appropriate event loop for the current platform."""
    if sys.platform == "win32":
        import winloop  # type: ignore[import-not-found]

        winloop.install()
    else:
        import uvloop  # type: ignore[import-not-found]

        uvloop.install()


def _discover_extension_webui_pages() -> dict[str, type]:
    """Discover WebUI pages from installed extensions.

    Returns:
        Dictionary mapping extension names to their WebUI page classes.
    """
    pages: dict[str, type] = {}
    extensions = discover_extensions()

    for ext_name, ext_info in extensions.items():
        if ext_info.webui_page is not None:
            pages[ext_name] = ext_info.webui_page
            logger.debug(f"Discovered WebUI page from extension: {ext_name}")

    return pages


# Cache for extension page instances
_extension_pages: dict[str, Any] = {}


@ui.page("/")
def index_page() -> None:
    """Renders the main single-page application with tabs."""
    # Apply dark mode from user preferences
    prefs = get_user_storage()
    if prefs.get("dark_mode", False):
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()

    # Create core page instances
    download_page = DownloadPage()
    search_page = SearchPage()
    settings_page = SettingsPage()
    logs_page = LogsPage()

    # Register core pages for cross-page access
    register_page("download", download_page)
    register_page("search", search_page)
    register_page("settings", settings_page)
    register_page("logs", logs_page)

    # Discover and create extension pages
    extension_page_classes = _discover_extension_webui_pages()
    for ext_name, page_class in extension_page_classes.items():
        page_instance = page_class()
        page_id = getattr(page_class, "page_id", ext_name)
        _extension_pages[page_id] = page_instance
        register_page(page_id, page_instance)

    # Header
    with ui.header().classes("bg-primary text-white items-center justify-between"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("music_note", size="lg")
            ui.label("Haberlea").classes("text-xl font-bold")

        # Tab navigation in header
        tabs = ui.tabs().classes("text-white").props("inline-label")
        with tabs:
            ui.tab("download", label="下载", icon="download")
            ui.tab("search", label="搜索", icon="search")

            # Add extension tabs (sorted by page_order)
            sorted_ext_pages = sorted(
                _extension_pages.items(),
                key=lambda x: getattr(x[1], "page_order", 50),
            )
            for page_id, page_instance in sorted_ext_pages:
                label = getattr(page_instance, "page_label", page_id)
                icon = getattr(page_instance, "page_icon", "extension")
                ui.tab(page_id, label=label, icon=icon)

            ui.tab("settings", label="设置", icon="settings")
            ui.tab("logs", label="日志", icon="article")

    # Main content area
    with (
        ui.column().classes("w-full min-h-screen"),
        ui.tab_panels(tabs, value="download").classes("w-full"),
    ):
        with ui.tab_panel("download"):
            download_page.render()

        with ui.tab_panel("search"):
            search_page.render()

        # Render extension pages
        for page_id, page_instance in _extension_pages.items():
            with ui.tab_panel(page_id):
                page_instance.render()

        with ui.tab_panel("settings"):
            settings_page.render()

        with ui.tab_panel("logs"):
            logs_page.render()


def main() -> None:
    """Main entry point for the WebUI application."""
    # Install uvloop/winloop before starting
    install_event_loop()

    # Configure storage
    app.storage.general["haberlea"] = app.storage.general.get(
        "haberlea",
        {
            "download_queue": [],
            "logs": [],
            "is_downloading": False,
        },
    )

    ui.run(
        title="Haberlea - 音乐下载器",
        host="127.0.0.1",
        port=8080,
        reload=False,
        show=True,
        storage_secret="haberlea_secret_key_change_in_production",
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
