"""Search page for Haberlea WebUI."""

from typing import Any

from nicegui import ui

from ...core import Haberlea
from ...utils.models import DownloadTypeEnum, ModuleFlags
from ...utils.settings import settings
from ..state import add_download_task


class SearchPage:
    """Search page component for searching music across services."""

    def __init__(self) -> None:
        """Initializes the search page."""
        self.search_input: ui.input | None = None
        self.results_container: ui.column | None = None
        self.selected_service: str = ""
        self.selected_type: str = "album"
        self.search_results: list[Any] = []

    def render(self) -> None:
        """Renders the search page."""
        with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
            ui.label("音乐搜索").classes("text-2xl font-bold")

            # Search form
            with (
                ui.card().classes("w-full"),
                ui.row().classes("w-full gap-4 items-end flex-wrap"),
            ):
                # Service selector
                services = self._get_available_services()
                self.selected_service = services[0] if services else ""
                ui.select(
                    label="服务",
                    options=services,
                    value=self.selected_service,
                    on_change=lambda e: setattr(self, "selected_service", e.value),
                ).classes("w-40")

                # Type selector
                ui.select(
                    label="类型",
                    options=["track", "album", "artist", "playlist"],
                    value=self.selected_type,
                    on_change=lambda e: setattr(self, "selected_type", e.value),
                ).classes("w-32")

                # Search input
                self.search_input = (
                    ui.input(
                        label="搜索关键词",
                        placeholder="输入艺术家、专辑或歌曲名称...",
                    )
                    .classes("flex-grow")
                    .props("clearable")
                )

                # Search button
                ui.button("搜索", icon="search", on_click=self._do_search).props(
                    "color=primary"
                )

            # Results
            with ui.card().classes("w-full"):
                ui.label("搜索结果").classes("text-lg font-semibold mb-2")
                self._render_results()

    def _get_available_services(self) -> list[str]:
        """Gets list of available music services.

        Returns:
            List of service names.
        """
        try:
            haberlea = Haberlea()
            return [
                m
                for m in haberlea.module_list
                if (
                    haberlea.module_settings[m].flags is None
                    or not (haberlea.module_settings[m].flags & ModuleFlags.hidden)
                )
            ]
        except Exception:
            # Return configured modules from settings
            modules = settings.modules
            return list(modules.keys()) if modules else ["qobuz", "tidal", "deezer"]

    async def _do_search(self) -> None:
        """Performs the search operation."""
        if not self.search_input or not self.search_input.value:
            ui.notify("请输入搜索关键词", type="warning")
            return

        if not self.selected_service:
            ui.notify("请选择服务", type="warning")
            return

        query = self.search_input.value.strip()
        ui.notify(f"正在搜索: {query}", type="info")

        try:
            haberlea = Haberlea()
            module = await haberlea.load_module(self.selected_service)

            query_type = DownloadTypeEnum[self.selected_type]
            limit = settings.global_settings.general.search_limit

            self.search_results = await module.search(query_type, query, limit=limit)
            self._render_results.refresh()

        except Exception as e:
            ui.notify(f"搜索失败: {e}", type="negative")
            self.search_results = []
            self._render_results.refresh()

    @ui.refreshable_method
    def _render_results(self) -> None:
        """Renders search results."""
        if not self.search_results:
            ui.label("输入关键词开始搜索").classes("text-gray-500 py-4")
            return

        for item in self.search_results:
            with (
                ui.card().classes("w-full p-3 hover:bg-gray-50 cursor-pointer"),
                ui.row().classes("w-full items-center gap-4"),
            ):
                # Cover placeholder
                ui.icon("album", size="xl").classes("text-gray-400")

                # Info
                with ui.column().classes("flex-grow min-w-0"):
                    ui.label(item.name or "Unknown").classes("font-semibold truncate")
                    if item.artists:
                        artists = (
                            ", ".join(item.artists)
                            if isinstance(item.artists, list)
                            else item.artists
                        )
                        ui.label(artists).classes("text-sm text-gray-600 truncate")
                    with ui.row().classes("gap-2 text-xs text-gray-500"):
                        if item.year:
                            ui.label(f"📅 {item.year}")
                        if item.duration:
                            minutes = item.duration // 60
                            seconds = item.duration % 60
                            ui.label(f"⏱ {minutes}:{seconds:02d}")
                        if item.explicit:
                            ui.badge("E", color="red").props("dense")

                # Download button
                ui.button(
                    icon="download",
                    on_click=lambda i=item: self._download_item(i),
                ).props("flat round")

    def _download_item(self, item: Any) -> None:
        """Initiates download for a search result item.

        Args:
            item: The search result item to download.
        """
        # Create a pseudo-URL for the download task
        url = f"{self.selected_service}://{self.selected_type}/{item.result_id}"
        add_download_task(
            url=url,
            service=self.selected_service,
            media_type=self.selected_type,
            media_id=item.result_id,
            data=item.data if hasattr(item, "data") else None,
        )
        ui.notify(f"已添加到下载队列: {item.name}", type="positive")
        ui.navigate.to("/")
