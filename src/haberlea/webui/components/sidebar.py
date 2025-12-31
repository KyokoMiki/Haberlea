"""Sidebar component for Haberlea WebUI."""

from nicegui import ui


def create_sidebar() -> ui.left_drawer:
    """Creates the application sidebar with navigation menu.

    Returns:
        The left drawer element.
    """
    with ui.left_drawer(value=True).classes("bg-gray-100") as drawer:
        ui.label("导航").classes("text-lg font-bold mb-4")

        with ui.column().classes("gap-2 w-full"):
            with ui.button(on_click=lambda: ui.navigate.to("/")).classes(
                "w-full justify-start"
            ):
                ui.icon("download").classes("mr-2")
                ui.label("下载")

            with ui.button(on_click=lambda: ui.navigate.to("/search")).classes(
                "w-full justify-start"
            ):
                ui.icon("search").classes("mr-2")
                ui.label("搜索")

            with ui.button(on_click=lambda: ui.navigate.to("/settings")).classes(
                "w-full justify-start"
            ):
                ui.icon("settings").classes("mr-2")
                ui.label("设置")

            with ui.button(on_click=lambda: ui.navigate.to("/logs")).classes(
                "w-full justify-start"
            ):
                ui.icon("article").classes("mr-2")
                ui.label("日志")

    return drawer
