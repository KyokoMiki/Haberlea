"""Settings page for Haberlea WebUI."""

import logging
from copy import deepcopy
from typing import Any

from nicegui import ui

from ...core import Haberlea
from ...i18n import SUPPORTED_LANGUAGES, _, set_language
from ...utils.settings import (
    AppSettings,
    get_settings_path,
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
            ui.label(_("Settings")).classes("text-2xl font-bold")

            with ui.tabs().classes("w-full") as tabs:
                ui.tab("general", label=_("General"), icon="settings")
                ui.tab("formatting", label=_("Formatting"), icon="text_format")
                ui.tab("codecs", label=_("Codecs"), icon="audiotrack")
                ui.tab("covers", label=_("Covers"), icon="image")
                ui.tab("lyrics", label=_("Lyrics"), icon="lyrics")
                ui.tab("advanced", label=_("Advanced"), icon="tune")
                ui.tab("webui", label="WebUI", icon="web")
                ui.tab("modules", label=_("Modules"), icon="extension")
                ui.tab("extensions", label=_("Extensions"), icon="power")

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

                with ui.tab_panel("webui"):
                    self._render_webui_settings()

            # Save button
            with ui.row().classes("w-full justify-end"):
                ui.button(
                    _("Reload"), icon="refresh", on_click=self._reload_settings
                ).props("flat")
                ui.button(
                    _("Save Settings"), icon="save", on_click=self._save_settings
                ).props("color=primary")

    def _render_general_settings(self) -> None:
        """Renders general settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("Download Settings")).classes("text-lg font-semibold mb-4")

            ui.input(
                label=_("Download Path"),
                value=gs.general.download_path,
            ).classes("w-full mb-2").bind_value(gs.general, "download_path")

            ui.select(
                label=_("Download Quality"),
                options=["minimum", "low", "medium", "high", "lossless", "hifi"],
                value=gs.general.download_quality,
            ).classes("w-48 mb-2").bind_value(gs.general, "download_quality")

            ui.number(
                label=_("Search Results Limit"),
                value=gs.general.search_limit,
                min=1,
                max=50,
            ).classes("w-48").bind_value(gs.general, "search_limit")

        with ui.card().classes("w-full mt-4"):
            ui.label(_("Artist Downloading")).classes("text-lg font-semibold mb-4")

            ui.checkbox(
                _("Return Credited Albums"),
                value=gs.artist_downloading.return_credited_albums,
            ).bind_value(gs.artist_downloading, "return_credited_albums")

            ui.checkbox(
                _("Skip Downloaded Separate Tracks"),
                value=gs.artist_downloading.separate_tracks_skip_downloaded,
            ).bind_value(gs.artist_downloading, "separate_tracks_skip_downloaded")

            ui.checkbox(
                _("Ignore Different Artists"),
                value=gs.artist_downloading.ignore_different_artists,
            ).bind_value(gs.artist_downloading, "ignore_different_artists")

    def _render_formatting_settings(self) -> None:
        """Renders formatting settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("File Naming Format")).classes("text-lg font-semibold mb-4")
            ui.label(
                _("Available variables: {name}, {artist}, {track_number}, ...")
            ).classes("text-sm text-gray-500 mb-4")

            ui.input(
                label=_("Album Folder Format"),
                value=gs.formatting.album_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "album_format")

            ui.input(
                label=_("Playlist Folder Format"),
                value=gs.formatting.playlist_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "playlist_format")

            ui.input(
                label=_("Track Filename Format"),
                value=gs.formatting.track_filename_format,
            ).classes("w-full mb-2").bind_value(gs.formatting, "track_filename_format")

            ui.input(
                label=_("Single Full Path Format"),
                value=gs.formatting.single_full_path_format,
            ).classes("w-full mb-4").bind_value(
                gs.formatting, "single_full_path_format"
            )

            ui.checkbox(
                _("Enable Zero Padding"),
                value=gs.formatting.enable_zfill,
            ).bind_value(gs.formatting, "enable_zfill")

            ui.checkbox(
                _("Force Album Format"),
                value=gs.formatting.force_album_format,
            ).bind_value(gs.formatting, "force_album_format")

    def _render_codec_settings(self) -> None:
        """Renders codec settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("Codec Options")).classes("text-lg font-semibold mb-4")

            ui.checkbox(
                _("Enable Proprietary Codecs (MQA, etc.)"),
                value=gs.codecs.proprietary_codecs,
            ).bind_value(gs.codecs, "proprietary_codecs")

            ui.checkbox(
                _("Enable Spatial Audio Codecs (Dolby Atmos, etc.)"),
                value=gs.codecs.spatial_codecs,
            ).bind_value(gs.codecs, "spatial_codecs")

        with ui.card().classes("w-full mt-4"):
            ui.label(_("Module Defaults")).classes("text-lg font-semibold mb-4")

            modules = self._get_available_modules()
            module_options = ["default"] + modules

            ui.select(
                label=_("Lyrics Source"),
                options=module_options,
                value=gs.module_defaults.lyrics,
            ).classes("w-48 mb-2").bind_value(gs.module_defaults, "lyrics")

            ui.select(
                label=_("Covers Source"),
                options=module_options,
                value=gs.module_defaults.covers,
            ).classes("w-48 mb-2").bind_value(gs.module_defaults, "covers")

            ui.select(
                label=_("Credits Source"),
                options=module_options,
                value=gs.module_defaults.credits,
            ).classes("w-48").bind_value(gs.module_defaults, "credits")

    def _render_cover_settings(self) -> None:
        """Renders cover settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("Cover Settings")).classes("text-lg font-semibold mb-4")

            ui.checkbox(
                _("Embed Cover"),
                value=gs.covers.embed_cover,
            ).bind_value(gs.covers, "embed_cover")

            ui.checkbox(
                _("Restrict Cover Size"),
                value=gs.covers.restrict_cover_size,
            ).bind_value(gs.covers, "restrict_cover_size")

            ui.select(
                label=_("Main Cover Compression"),
                options=["low", "high"],
                value=gs.covers.main_compression,
            ).classes("w-32 mb-2").bind_value(gs.covers, "main_compression")

            ui.number(
                label=_("Main Cover Resolution"),
                value=gs.covers.main_resolution,
                min=100,
                max=5000,
            ).classes("w-48 mb-4").bind_value(gs.covers, "main_resolution")

            ui.checkbox(
                _("Save External Cover"),
                value=gs.covers.save_external,
            ).bind_value(gs.covers, "save_external")

            ui.select(
                label=_("External Cover Format"),
                options=["jpg", "png", "webp"],
                value=gs.covers.external_format,
            ).classes("w-32 mb-2").bind_value(gs.covers, "external_format")

            ui.select(
                label=_("External Cover Compression"),
                options=["low", "high"],
                value=gs.covers.external_compression,
            ).classes("w-32 mb-2").bind_value(gs.covers, "external_compression")

            ui.number(
                label=_("External Cover Resolution"),
                value=gs.covers.external_resolution,
                min=100,
                max=5000,
            ).classes("w-48 mb-4").bind_value(gs.covers, "external_resolution")

            ui.checkbox(
                _("Save Animated Cover"),
                value=gs.covers.save_animated_cover,
            ).bind_value(gs.covers, "save_animated_cover")

    def _render_lyrics_settings(self) -> None:
        """Renders lyrics settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("Lyrics Settings")).classes("text-lg font-semibold mb-4")

            ui.checkbox(
                _("Embed Lyrics"),
                value=gs.lyrics.embed_lyrics,
            ).bind_value(gs.lyrics, "embed_lyrics")

            ui.checkbox(
                _("Embed Synced Lyrics"),
                value=gs.lyrics.embed_synced_lyrics,
            ).bind_value(gs.lyrics, "embed_synced_lyrics")

            ui.checkbox(
                _("Save Synced Lyrics File (.lrc)"),
                value=gs.lyrics.save_synced_lyrics,
            ).bind_value(gs.lyrics, "save_synced_lyrics")

        with ui.card().classes("w-full mt-4"):
            ui.label(_("Playlist Settings")).classes("text-lg font-semibold mb-4")

            ui.checkbox(
                _("Save M3U Playlist"),
                value=gs.playlist.save_m3u,
            ).bind_value(gs.playlist, "save_m3u")

            ui.select(
                label=_("M3U Path Type"),
                options=["absolute", "relative"],
                value=gs.playlist.paths_m3u,
            ).classes("w-32 mb-2").bind_value(gs.playlist, "paths_m3u")

            ui.checkbox(
                _("Extended M3U Format"),
                value=gs.playlist.extended_m3u,
            ).bind_value(gs.playlist, "extended_m3u")

    def _render_advanced_settings(self) -> None:
        """Renders advanced settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("Advanced Settings")).classes("text-lg font-semibold mb-4")

            ui.number(
                label=_("Concurrent Downloads"),
                value=gs.advanced.concurrent_downloads,
                min=1,
                max=10,
            ).classes("w-48 mb-4").bind_value(gs.advanced, "concurrent_downloads")

            ui.checkbox(
                _("Dry Run (Collect info only, no download)"),
                value=gs.advanced.dry_run,
            ).bind_value(gs.advanced, "dry_run")

            ui.checkbox(
                _("Debug Mode"),
                value=gs.advanced.debug_mode,
            ).bind_value(gs.advanced, "debug_mode")

            ui.checkbox(
                _("Ignore Existing Files"),
                value=gs.advanced.ignore_existing_files,
            ).bind_value(gs.advanced, "ignore_existing_files")

            ui.checkbox(
                _("Disable Subscription Checks"),
                value=gs.advanced.disable_subscription_checks,
            ).bind_value(gs.advanced, "disable_subscription_checks")

            ui.checkbox(
                _("Abort Download When Single Failed"),
                value=gs.advanced.abort_download_when_single_failed,
            ).bind_value(gs.advanced, "abort_download_when_single_failed")

            ui.checkbox(
                _("Enable Undesirable Conversions (lossy to lossy)"),
                value=gs.advanced.enable_undesirable_conversions,
            ).bind_value(gs.advanced, "enable_undesirable_conversions")

            ui.checkbox(
                _("Advanced Login System"),
                value=gs.advanced.advanced_login_system,
            ).bind_value(gs.advanced, "advanced_login_system")

            ui.checkbox(
                _("Keep Original After Conversion"),
                value=gs.advanced.conversion_keep_original,
            ).bind_value(gs.advanced, "conversion_keep_original")

            ui.number(
                label=_("Cover Variance Threshold"),
                value=gs.advanced.cover_variance_threshold,
                min=0,
                max=100,
            ).classes("w-48 mb-4").bind_value(gs.advanced, "cover_variance_threshold")

    def _render_webui_settings(self) -> None:
        """Renders WebUI settings section."""
        gs = self._edit_settings.global_settings

        with ui.card().classes("w-full"):
            ui.label(_("WebUI Settings")).classes("text-lg font-semibold mb-4")

            ui.label(_("Server Settings")).classes(
                "text-md font-medium text-gray-600 mb-2"
            )

            ui.input(
                label=_("Host Address"),
                value=gs.webui.host,
                placeholder=_("Leave empty to listen on all interfaces (0.0.0.0)"),
            ).classes("w-full mb-2").bind_value(gs.webui, "host")

            ui.number(
                label=_("Port"),
                value=gs.webui.port,
                min=1,
                max=65535,
            ).classes("w-48 mb-4").bind_value(gs.webui, "port")

            ui.label(_("Authentication Settings")).classes(
                "text-md font-medium text-gray-600 mb-2 mt-4"
            )

            ui.checkbox(
                _("Enable Login Authentication"),
                value=gs.webui.auth_enabled,
            ).bind_value(gs.webui, "auth_enabled")

            ui.input(
                _("Username"),
                value=gs.webui.username,
            ).classes("w-full mb-2").bind_value(gs.webui, "username")

            ui.input(
                _("Password"),
                value=gs.webui.password,
                password=True,
                password_toggle_button=True,
            ).classes("w-full mb-4").bind_value(gs.webui, "password")

            ui.label(_("Language Settings")).classes(
                "text-md font-medium text-gray-600 mb-2 mt-4"
            )

            # Language selector with change handler
            language_names = {
                "zh_CN": "简体中文",
                "en_US": "English",
            }

            def on_language_change(e: object) -> None:
                """Handle language change."""
                new_lang = getattr(e, "value", gs.webui.language)
                gs.webui.language = new_lang
                set_language(new_lang)
                ui.notify(
                    _("Language will be applied after saving and refreshing"),
                    type="info",
                )

            ui.select(
                label=_("Interface Language"),
                options={lang: language_names[lang] for lang in SUPPORTED_LANGUAGES},
                value=gs.webui.language,
                on_change=on_language_change,
            ).classes("w-48")

    def _render_module_settings(self) -> None:
        """Renders module-specific settings section.

        Supports multi-account structure where each module has a list of accounts.
        Provides add/delete account functionality with dynamic UI updates.
        """
        modules = self._edit_settings.modules

        if not modules:
            with ui.card().classes("w-full"):
                ui.label(_("No configured modules")).classes("text-gray-500")
            return

        for module_name, accounts in modules.items():
            # Handle both old dict format and new list format for compatibility
            if isinstance(accounts, dict):
                logging.getLogger(__name__).warning(
                    "Module '%s' uses legacy dict format, migrating to list format",
                    module_name,
                )
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

                # Action buttons row
                with ui.row().classes("mt-2 gap-2"):
                    ui.button(
                        _("Add Account"),
                        icon="add",
                        on_click=lambda _, m=module_name: self._add_account(m),
                    ).props("flat")
                    ui.button(
                        _("Re-login"),
                        icon="refresh",
                        on_click=lambda _, m=module_name: self._clear_module_session(m),
                    ).props("flat color=warning").tooltip(
                        _("Clear login data, will need to re-login on next use")
                    )

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
                ui.label(f"{_('Account')} {account_index + 1}").classes(
                    "text-sm font-semibold text-gray-600"
                )
                ui.button(
                    icon="delete",
                    on_click=lambda _, m=module_name, idx=account_index: (
                        self._delete_account(m, idx)
                    ),
                ).props("flat dense color=negative").tooltip(_("Delete this account"))
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
            ui.notify(_("At least one account must be kept"), type="warning")
            return

        if account_index < len(accounts):
            accounts.pop(account_index)

            # Clear all cards for this module
            cards = self._account_cards.get(module_name, [])
            for card in cards:
                card.delete()
            self._account_cards[module_name] = []

            # Rebuild all account cards with correct indices
            container = self._account_containers.get(module_name)
            if container is not None:
                with container:
                    for idx, account_config in enumerate(accounts):
                        self._create_account_card(module_name, idx, account_config)

            # Update expansion title
            expansion = self._module_expansions.get(module_name)
            if expansion is not None:
                expansion.props(
                    f'label="{module_name.upper()} ({len(accounts)} 个账号)"'
                )

            ui.notify(_("Account deleted"), type="positive")

    def _clear_module_session(self, module_name: str) -> None:
        """Clears session data for a module, forcing re-login.

        Args:
            module_name: Name of the module to clear session for.
        """
        haberlea = Haberlea()
        if haberlea.clear_module_session(module_name):
            ui.notify(
                _("Login data cleared, will re-login on next use"),
                type="positive",
            )
        else:
            ui.notify(_("Failed to clear login data"), type="negative")

    def _get_available_modules(self) -> list[str]:
        """Gets list of available modules.

        Returns:
            List of module names.
        """
        return list(self._edit_settings.modules.keys())

    def _save_settings(self) -> None:
        """Saves edit settings to file and updates global singleton."""
        set_settings(self._edit_settings)
        save_settings(get_settings_path(), self._edit_settings)
        ui.notify(_("Settings saved"), type="positive")

    def _reload_settings(self) -> None:
        """Reloads settings from file and refreshes the page."""
        reload_settings()
        ui.notify(_("Settings reloaded"), type="info")
        ui.navigate.reload()

    def _render_extension_settings(self) -> None:
        """Renders extension settings section.

        Extensions are grouped by type (e.g., post_download).
        Each extension has its own settings card.
        """
        extensions = self._edit_settings.extensions

        if not extensions:
            with ui.card().classes("w-full"):
                ui.label(_("No installed extensions")).classes("text-gray-500")
            return

        for ext_type, ext_configs in extensions.items():
            if not ext_configs:
                continue

            # Extension type header
            type_labels: dict[str, str] = {
                "post_download": _("Post-Download Processing"),
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
            "priority": _("Priority"),
            "rar_enabled": _("Enable RAR Compression"),
            "rar_path": _("RAR Executable Path"),
            "compression_level": _("Compression Level (0-5)"),
            "delete_after_upload": _("Delete archive and source files after upload"),
            "password": _("Compression Password"),
            "upload_enabled": _("Enable Baidu Netdisk Upload"),
            "baidupcs_path": _("BaiduPCS-Go Path"),
            "upload_path": _("Upload Target Path"),
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
