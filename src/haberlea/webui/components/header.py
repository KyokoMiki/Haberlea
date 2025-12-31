"""Header component for Haberlea WebUI."""

from nicegui import ui


def create_header() -> None:
    """Creates the application header with navigation."""
    with ui.header().classes("bg-primary text-white items-center justify-between"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("music_note", size="lg")
            ui.label("Haberlea").classes("text-xl font-bold")

        with ui.row().classes("gap-2"):
            ui.button(
                "下载", icon="download", on_click=lambda: ui.navigate.to("/")
            ).props("flat color=white")
            ui.button(
                "搜索", icon="search", on_click=lambda: ui.navigate.to("/search")
            ).props("flat color=white")
            ui.button(
                "封面", icon="image", on_click=lambda: ui.navigate.to("/covers")
            ).props("flat color=white")
            ui.button(
                "设置", icon="settings", on_click=lambda: ui.navigate.to("/settings")
            ).props("flat color=white")
            ui.button(
                "日志", icon="article", on_click=lambda: ui.navigate.to("/logs")
            ).props("flat color=white")
