"""Settings page for Haberlea WebUI."""

from copy import deepcopy
from typing import Any

from nicegui import ui

from ...utils.settings import (
    AppSettings,
    _settings_path,
    reload_settings,
    save_settings,
    set_settings,
    settings,
)


class SettingsPage:
    """Settings page component for configuring application options.

    Uses a local copy of settings for editing. Changes are only applied
    to the global settings singleton when the user clicks save.
    """

    def __init__(self) -> None:
        """Initializes the settings page."""
        self._current_tab: str = "general"
        # Local copy of settings for editing (not affecting global until save)
        self._edit_settings: AppSettings
        # Store UI references for dynamic updates
        self._account_containers: dict[str, ui.column] = {}
        self._account_cards: dict[str, list[ui.card]] = {}
        self._module_expansions: dict[str, ui.expansion] = {}

    def _load_edit_settings(self) -> AppSettings:
        """Loads a deep copy of current settings for editing.

        Returns:
            A deep copy of the current AppSettings.
        """
        self._edit_settings = deepcopy(settings.current)
        return self._edit_settings

    def render(self) -> None:
        """Renders the settings page."""
        # Load a copy of settings for editing
        self._load_edit_settings()

        with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
            ui.label("设置").classes("text-2xl font-bold")

            with ui.tabs().classes("w-full") as tabs:
                ui.tab("general", label="常规", icon="settings")
                ui.tab("formatting", label="格式化", icon="text_format")
                ui.tab("codecs", label="编解码器", icon="audiotrack")
                ui.tab("covers", label="封面", icon="image")
                ui.tab("lyrics", label="歌词", icon="lyrics")
                ui.tab("advanced", label="高级", icon="tune")
                ui.tab("modules", label="模块", icon="extension")
                ui.tab("extensions", label="扩展", icon="power")

            with ui.tab_panels(tabs, value="general").classes("w-full"):
                with ui.tab_panel("general"):
                    self._render_general_settings()

                with ui.tab_panel("formatting"):
                    self._render_formatting_settings()

                with ui.tab_panel("codecs"):
                    self._render_codec_settings()

                with ui.tab_panel("covers"):
                    self._render_cover_settings()

                with ui.tab_panel("lyrics"):
                    self._render_lyrics_settings()

                with ui.tab_panel("advanced"):
                    self._render_advanced_settings()

                with ui.tab_panel("modules"):
                    self._render_module_settings()

                with ui.tab_panel("extensions"):
                    self._render_extension_settings()

            # Save button
            with ui.row().classes("w-full justify-end"):
                ui.button(
                    "重新加载", icon="refresh", on_click=self._reload_settings
                ).props("flat")
                ui.button("保存设置", icon="save", on_click=self._save_settings).props(
                    "color=primary"
                )

    def _render_general_settings(self) -> None:
        """Renders general settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("下载设置").classes("text-lg font-semibold mb-4")

            ui.input(
                label="下载路径",
                value=gs.general.download_path,
            ).classes("w-full mb-2").bind_value(gs.general, "download_path")

            ui.select(
                label="下载质量",
                options=["minimum", "low", "medium", "high", "lossless", "hifi"],
                value=gs.general.download_quality,
            ).classes("w-48 mb-2").bind_value(gs.general, "download_quality")

            ui.number(
                label="搜索结果数量",
                value=gs.general.search_limit,
                min=1,
                max=50,
            ).classes("w-48").bind_value(gs.general, "search_limit")

        with ui.card().classes("w-full mt-4"):
            ui.label("艺术家下载").classes("text-lg font-semibold mb-4")

            ui.checkbox(
                "返回参与专辑",
                value=gs.artist_downloading.return_credited_albums,
            ).bind_value(gs.artist_downloading, "return_credited_albums")

            ui.checkbox(
                "跳过已下载的单曲",
                value=gs.artist_downloading.separate_tracks_skip_downloaded,
            ).bind_value(gs.artist_downloading, "separate_tracks_skip_downloaded")

    def _render_formatting_settings(self) -> None:
        """Renders formatting settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("文件命名格式").classes("text-lg font-semibold mb-4")
            ui.label("可用变量: {name}, {artist}, {track_number}, ...").classes(
                "text-sm text-gray-500 mb-4"
            )

            ui.input(
                label="专辑文件夹格式",
                value=gs.formatting.album_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "album_format")

            ui.input(
                label="播放列表文件夹格式",
                value=gs.formatting.playlist_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "playlist_format")

            ui.input(
                label="曲目文件名格式",
                value=gs.formatting.track_filename_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "track_filename_format")

            ui.input(
                label="单曲完整路径格式",
                value=gs.formatting.single_full_path_format,
            ).classes("w-full mb-4").bind_value(
                gs.formatting, "single_full_path_format"
            )

            ui.checkbox(
                "启用数字补零",
                value=gs.formatting.enable_zfill,
            ).bind_value(gs.formatting, "enable_zfill")

            ui.checkbox(
                "强制使用专辑格式",
                value=gs.formatting.force_album_format,
            ).bind_value(gs.formatting, "force_album_format")

    def _render_codec_settings(self) -> None:
        """Renders codec settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("编解码器选项").classes("text-lg font-semibold mb-4")

            ui.checkbox(
                "启用专有编解码器 (MQA等)",
                value=gs.codecs.proprietary_codecs,
            ).bind_value(gs.codecs, "proprietary_codecs")

            ui.checkbox(
                "启用空间音频编解码器 (Dolby Atmos等)",
                value=gs.codecs.spatial_codecs,
            ).bind_value(gs.codecs, "spatial_codecs")

        with ui.card().classes("w-full mt-4"):
            ui.label("模块默认设置").classes("text-lg font-semibold mb-4")

            modules = self._get_available_modules()
            module_options = ["default"] + modules

            ui.select(
                label="歌词来源",
                options=module_options,
                value=gs.module_defaults.lyrics,
            ).classes("w-48 mb-2").bind_value(gs.module_defaults, "lyrics")

            ui.select(
                label="封面来源",
                options=module_options,
                value=gs.module_defaults.covers,
            ).classes("w-48 mb-2").bind_value(gs.module_defaults, "covers")

            ui.select(
                label="制作人员来源",
                options=module_options,
                value=gs.module_defaults.credits,
            ).classes("w-48").bind_value(gs.module_defaults, "credits")

    def _render_cover_settings(self) -> None:
        """Renders cover settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("封面设置").classes("text-lg font-semibold mb-4")

            ui.checkbox(
                "嵌入封面",
                value=gs.covers.embed_cover,
            ).bind_value(gs.covers, "embed_cover")

            ui.checkbox(
                "限制封面大小",
                value=gs.covers.restrict_cover_size,
            ).bind_value(gs.covers, "restrict_cover_size")

            ui.select(
                label="主封面压缩",
                options=["low", "high"],
                value=gs.covers.main_compression,
            ).classes("w-32 mb-2").bind_value(gs.covers, "main_compression")

            ui.number(
                label="主封面分辨率",
                value=gs.covers.main_resolution,
                min=100,
                max=5000,
            ).classes("w-48 mb-4").bind_value(gs.covers, "main_resolution")

            ui.checkbox(
                "保存外部封面",
                value=gs.covers.save_external,
            ).bind_value(gs.covers, "save_external")

            ui.select(
                label="外部封面格式",
                options=["jpg", "png", "webp"],
                value=gs.covers.external_format,
            ).classes("w-32 mb-2").bind_value(gs.covers, "external_format")

            ui.checkbox(
                "保存动态封面",
                value=gs.covers.save_animated_cover,
            ).bind_value(gs.covers, "save_animated_cover")

    def _render_lyrics_settings(self) -> None:
        """Renders lyrics settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("歌词设置").classes("text-lg font-semibold mb-4")

            ui.checkbox(
                "嵌入歌词",
                value=gs.lyrics.embed_lyrics,
            ).bind_value(gs.lyrics, "embed_lyrics")

            ui.checkbox(
                "嵌入同步歌词",
                value=gs.lyrics.embed_synced_lyrics,
            ).bind_value(gs.lyrics, "embed_synced_lyrics")

            ui.checkbox(
                "保存同步歌词文件 (.lrc)",
                value=gs.lyrics.save_synced_lyrics,
            ).bind_value(gs.lyrics, "save_synced_lyrics")

        with ui.card().classes("w-full mt-4"):
            ui.label("播放列表设置").classes("text-lg font-semibold mb-4")

            ui.checkbox(
                "保存 M3U 播放列表",
                value=gs.playlist.save_m3u,
            ).bind_value(gs.playlist, "save_m3u")

            ui.select(
                label="M3U 路径类型",
                options=["absolute", "relative"],
                value=gs.playlist.paths_m3u,
            ).classes("w-32 mb-2").bind_value(gs.playlist, "paths_m3u")

            ui.checkbox(
                "扩展 M3U 格式",
                value=gs.playlist.extended_m3u,
            ).bind_value(gs.playlist, "extended_m3u")

    def _render_advanced_settings(self) -> None:
        """Renders advanced settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label("高级设置").classes("text-lg font-semibold mb-4")

            ui.number(
                label="并发下载数",
                value=gs.advanced.concurrent_downloads,
                min=1,
                max=10,
            ).classes("w-48 mb-4").bind_value(gs.advanced, "concurrent_downloads")

            ui.checkbox(
                "调试模式",
                value=gs.advanced.debug_mode,
            ).bind_value(gs.advanced, "debug_mode")

            ui.checkbox(
                "忽略已存在文件",
                value=gs.advanced.ignore_existing_files,
            ).bind_value(gs.advanced, "ignore_existing_files")

            ui.checkbox(
                "忽略不同艺术家",
                value=gs.advanced.ignore_different_artists,
            ).bind_value(gs.advanced, "ignore_different_artists")

            ui.checkbox(
                "禁用订阅检查",
                value=gs.advanced.disable_subscription_checks,
            ).bind_value(gs.advanced, "disable_subscription_checks")

            ui.checkbox(
                "单曲失败时中止下载",
                value=gs.advanced.abort_download_when_single_failed,
            ).bind_value(gs.advanced, "abort_download_when_single_failed")

            ui.checkbox(
                "高级登录系统",
                value=gs.advanced.advanced_login_system,
            ).bind_value(gs.advanced, "advanced_login_system")

            ui.checkbox(
                "保留转换前原文件",
                value=gs.advanced.conversion_keep_original,
            ).bind_value(gs.advanced, "conversion_keep_original")

    def _render_module_settings(self) -> None:
        """Renders module-specific settings section.

        Supports multi-account structure where each module has a list of accounts.
        Provides add/delete account functionality with dynamic UI updates.
        """
        modules = self._edit_settings.modules

        if not modules:
            with ui.card().classes("w-full"):
                ui.label("没有配置的模块").classes("text-gray-500")
            return

        for module_name, accounts in modules.items():
            # Handle both old dict format and new list format for compatibility
            if isinstance(accounts, dict):
                accounts = [accounts]

            with ui.expansion(
                f"{module_name.upper()} ({len(accounts)} 个账号)",
                icon="extension",
            ).classes("w-full mb-2") as expansion:
                # Store expansion reference for updating title later
                self._module_expansions[module_name] = expansion

                # Container for account cards
                account_container = ui.column().classes("w-full")
                self._account_containers[module_name] = account_container
                self._account_cards[module_name] = []

                with account_container:
                    for account_index, account_config in enumerate(accounts):
                        self._create_account_card(
                            module_name, account_index, account_config
                        )

                # Add account button
                ui.button(
                    "添加账号",
                    icon="add",
                    on_click=lambda _, m=module_name: self._add_account(m),
                ).props("flat").classes("mt-2")

    def _render_account_fields(
        self, module_name: str, account_index: int, account_config: dict[str, Any]
    ) -> None:
        """Renders input fields for a single account configuration.

        Args:
            module_name: Name of the module.
            account_index: Index of the account in the accounts list.
            account_config: Account configuration dictionary.
        """
        for key, value in account_config.items():
            if isinstance(value, bool):
                ui.checkbox(
                    key,
                    value=value,
                    on_change=lambda e, m=module_name, idx=account_index, k=key: (
                        self._set_module_account_value(m, idx, k, e.value)
                    ),
                )
            elif isinstance(value, (int, float)):
                ui.number(
                    label=key,
                    value=value,
                    on_change=lambda e, m=module_name, idx=account_index, k=key: (
                        self._set_module_account_value(m, idx, k, e.value)
                    ),
                ).classes("w-full mb-2")
            else:
                # Password fields
                is_password = (
                    "password" in key.lower()
                    or "secret" in key.lower()
                    or "arl" in key.lower()
                )
                ui.input(
                    label=key,
                    value=str(value) if value else "",
                    password=is_password,
                    password_toggle_button=is_password,
                    on_change=lambda e, m=module_name, idx=account_index, k=key: (
                        self._set_module_account_value(m, idx, k, e.value)
                    ),
                ).classes("w-full mb-2")

    def _create_account_card(
        self, module_name: str, account_index: int, account_config: dict[str, Any]
    ) -> ui.card:
        """Creates a single account card with fields and delete button.

        Args:
            module_name: Name of the module.
            account_index: Index of the account in the accounts list.
            account_config: Account configuration dictionary.

        Returns:
            The created ui.card element.
        """
        card = ui.card().classes("w-full mb-2")
        with card:
            with ui.row().classes("w-full justify-between items-center"):
                ui.label(f"账号 {account_index + 1}").classes(
                    "text-sm font-semibold text-gray-600"
                )
                ui.button(
                    icon="delete",
                    on_click=lambda _, m=module_name, idx=account_index: (
                        self._delete_account(m, idx)
                    ),
                ).props("flat dense color=negative").tooltip("删除此账号")
            self._render_account_fields(module_name, account_index, account_config)

        self._account_cards[module_name].append(card)
        return card

    def _set_module_account_value(
        self, module_name: str, account_index: int, key: str, value: object
    ) -> None:
        """Sets a value in a module's account configuration.

        Args:
            module_name: Name of the module.
            account_index: Index of the account in the accounts list.
            key: Configuration key to set.
            value: Value to set.
        """
        modules = self._edit_settings.modules
        if module_name in modules and account_index < len(modules[module_name]):
            modules[module_name][account_index][key] = value

    def _add_account(self, module_name: str) -> None:
        """Adds a new empty account to the specified module.

        Dynamically creates a new account card without page reload.
        Only updates edit settings, does not save to file.

        Args:
            module_name: Name of the module to add account to.
        """
        modules = self._edit_settings.modules
        if module_name not in modules:
            return

        accounts = modules[module_name]
        if not accounts:
            return

        # Create new account with same keys as first account but empty values
        template = accounts[0]
        new_account: dict[str, object] = {}
        for key, value in template.items():
            if isinstance(value, bool):
                new_account[key] = False
            elif isinstance(value, (int, float)):
                new_account[key] = 0
            else:
                new_account[key] = ""

        accounts.append(new_account)
        new_index = len(accounts) - 1

        # Dynamically add new account card to the container
        container = self._account_containers.get(module_name)
        if container is not None:
            with container:
                self._create_account_card(module_name, new_index, new_account)

    def _delete_account(self, module_name: str, account_index: int) -> None:
        """Deletes an account from the specified module.

        Dynamically removes the account card without page reload.
        Only updates edit settings, does not save to file.

        Args:
            module_name: Name of the module.
            account_index: Index of the account to delete.
        """
        modules = self._edit_settings.modules
        if module_name not in modules:
            return

        accounts = modules[module_name]
        if len(accounts) <= 1:
            ui.notify("至少需要保留一个账号", type="warning")
            return

        if account_index < len(accounts):
            accounts.pop(account_index)

            # Remove the card from UI
            cards = self._account_cards.get(module_name, [])
            if account_index < len(cards):
                card = cards.pop(account_index)
                card.delete()

    def _get_available_modules(self) -> list[str]:
        """Gets list of available modules.

        Returns:
            List of module names.
        """
        return list(self._edit_settings.modules.keys())

    def _save_settings(self) -> None:
        """Saves edit settings to file and updates global singleton."""
        set_settings(self._edit_settings)
        save_settings(_settings_path, self._edit_settings)
        ui.notify("设置已保存", type="positive")

    def _reload_settings(self) -> None:
        """Reloads settings from file and refreshes the page."""
        reload_settings()
        ui.notify("设置已重新加载", type="info")
        ui.navigate.reload()

    def _render_extension_settings(self) -> None:
        """Renders extension settings section.

        Extensions are grouped by type (e.g., post_download).
        Each extension has its own settings card.
        """
        extensions = self._edit_settings.extensions

        if not extensions:
            with ui.card().classes("w-full"):
                ui.label("没有已安装的扩展").classes("text-gray-500")
            return

        for ext_type, ext_configs in extensions.items():
            if not ext_configs:
                continue

            # Extension type header
            type_labels: dict[str, str] = {
                "post_download": "下载后处理",
            }
            type_label: str = type_labels.get(ext_type) or ext_type

            ui.label(type_label).classes("text-lg font-semibold mt-4 mb-2")

            for ext_name, ext_settings in ext_configs.items():
                self._render_extension_card(ext_type, ext_name, ext_settings)

    def _render_extension_card(
        self, ext_type: str, ext_name: str, ext_settings: dict[str, Any]
    ) -> None:
        """Renders a single extension settings card.

        Args:
            ext_type: Extension type (e.g., post_download).
            ext_name: Extension name.
            ext_settings: Extension settings dictionary.
        """
        with (
            ui.expansion(
                f"{ext_name.upper()}",
                icon="power",
            ).classes("w-full mb-2"),
            ui.card().classes("w-full"),
        ):
            for key, value in ext_settings.items():
                self._render_extension_field(ext_type, ext_name, key, value)

    def _render_extension_field(
        self, ext_type: str, ext_name: str, key: str, value: object
    ) -> None:
        """Renders a single extension setting field.

        Args:
            ext_type: Extension type.
            ext_name: Extension name.
            key: Setting key.
            value: Setting value.
        """
        # Field labels
        field_labels = {
            "priority": "优先级",
            "rar_enabled": "启用 RAR 压缩",
            "rar_path": "RAR 可执行文件路径",
            "compression_level": "压缩级别 (0-5)",
            "delete_source": "压缩后删除源文件夹",
            "password": "压缩密码",
            "upload_enabled": "启用百度网盘上传",
            "baidupcs_path": "BaiduPCS-Go 路径",
            "upload_path": "上传目标路径",
        }
        label = field_labels.get(key, key)

        if isinstance(value, bool):
            ui.checkbox(
                label,
                value=value,
                on_change=lambda e, t=ext_type, n=ext_name, k=key: (
                    self._set_extension_value(t, n, k, e.value)
                ),
            )
        elif isinstance(value, int):
            ui.number(
                label=label,
                value=value,
                on_change=lambda e, t=ext_type, n=ext_name, k=key: (
                    self._set_extension_value(t, n, k, int(e.value))
                ),
            ).classes("w-full mb-2")
        else:
            is_password = "password" in key.lower()
            ui.input(
                label=label,
                value=str(value) if value else "",
                password=is_password,
                password_toggle_button=is_password,
                on_change=lambda e, t=ext_type, n=ext_name, k=key: (
                    self._set_extension_value(t, n, k, e.value)
                ),
            ).classes("w-full mb-2")

    def _set_extension_value(
        self, ext_type: str, ext_name: str, key: str, value: object
    ) -> None:
        """Sets a value in an extension's configuration.

        Args:
            ext_type: Extension type.
            ext_name: Extension name.
            key: Configuration key to set.
            value: Value to set.
        """
        extensions = self._edit_settings.extensions
        if ext_type in extensions and ext_name in extensions[ext_type]:
            extensions[ext_type][ext_name][key] = value
