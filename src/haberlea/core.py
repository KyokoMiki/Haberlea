"""Core module for Haberlea music downloader.

This module provides the main orchestration layer using a global download queue
that collects all tracks and downloads them concurrently.
"""

import asyncio
import base64
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import msgspec
from rich import print
from rich.logging import RichHandler

from .download_queue import DownloadJob, DownloadQueue
from .music_downloader import Downloader, ModuleControls
from .plugins.base import ModuleBase
from .plugins.loader import (
    discover_extensions,
    discover_modules,
    load_extension,
    load_module,
)
from .utils.exceptions import (
    ConfigurationError,
    InvalidInput,
    InvalidModuleError,
    ModuleDoesNotSupportAbility,
    RegionRestrictedError,
)
from .utils.models import (
    CodecOptions,
    CoverCompressionEnum,
    CoverOptions,
    DownloadTypeEnum,
    ExtensionInstance,
    HabeleaOptions,
    ImageFileTypeEnum,
    ManualEnum,
    MediaIdentification,
    ModuleController,
    ModuleFlags,
    ModuleInformation,
    ModuleModes,
    QualityEnum,
    TemporarySettingsController,
)
from .utils.settings import (
    AppSettings,
    load_settings,
    save_settings,
    set_settings,
    set_settings_path,
    settings,
)
from .utils.utils import hash_string, read_temporary_setting, set_temporary_setting

logger = logging.getLogger(__name__)

_timestamp_correction: int = 0


def get_utc_timestamp() -> int:
    """Gets the current UTC timestamp with correction applied."""
    return int(datetime.now(UTC).timestamp()) + _timestamp_correction


@runtime_checkable
class SettingsLoaderProtocol(Protocol):
    """Protocol for loading and saving settings."""

    def load(self, path: Path) -> AppSettings:
        """Loads settings from a file."""
        ...

    def save(self, path: Path, settings: AppSettings) -> None:
        """Saves settings to a file."""
        ...


class TomlSettingsLoader:
    """TOML-based settings loader implementation."""

    def load(self, path: Path) -> AppSettings:
        """Loads settings from a TOML file."""
        return load_settings(path)

    def save(self, path: Path, settings: AppSettings) -> None:
        """Saves settings to a TOML file."""
        save_settings(path, settings)


class Haberlea:
    """Main orchestrator for music downloading operations."""

    __slots__ = (
        "_config_dir",
        "_settings_path",
        "_session_path",
        "_settings_loader",
        "_discovered_extensions",
        "_current_account_index",
        "extensions",
        "extension_list",
        "module_list",
        "module_settings",
        "module_netloc_constants",
        "loaded_modules",
        "module_controls",
    )

    def __init__(
        self,
        private_mode: bool = False,
        config_dir: Path | None = None,
        settings_loader: SettingsLoaderProtocol | None = None,
    ) -> None:
        """Initializes the Haberlea orchestrator."""
        self._config_dir = config_dir or Path("config")
        self._settings_path = self._config_dir / "settings.toml"
        self._session_path = self._config_dir / "loginstorage.json"
        self._settings_loader = settings_loader or TomlSettingsLoader()

        self.extensions: list[ExtensionInstance] = []
        self.extension_list: set[str] = set()
        self.module_list: set[str] = set()
        self.module_settings: dict[str, ModuleInformation] = {}
        self.module_netloc_constants: dict[str, str] = {}
        self.loaded_modules: dict[str, ModuleBase] = {}
        # Track current account index for each module (for multi-account support)
        self._current_account_index: dict[str, int] = {}

        self._config_dir.mkdir(parents=True, exist_ok=True)

        # Initialize global settings singleton with correct path
        set_settings_path(self._settings_path)
        self._configure_logging()

        self._discovered_extensions = discover_extensions()
        self._register_extensions()

        discovered_modules = discover_modules()
        self._register_modules(discovered_modules, private_mode)
        self._validate_netloc_constants()

        self._update_module_storage()
        self._initialize_extensions()

        self.module_controls = ModuleControls(
            module_list=list(self.module_list),
            module_settings=self.module_settings,
            loaded_modules=self.loaded_modules,
            module_loader=self.load_module,
            extensions=[ext.instance for ext in self.extensions],
        )

    def _configure_logging(self) -> None:
        """Configures logging based on debug mode setting using Rich handler."""
        level = (
            logging.DEBUG
            if settings.global_settings.advanced.debug_mode
            else logging.WARNING
        )
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )

    def _register_extensions(self) -> None:
        """Registers discovered extensions."""
        for ext_name in self._discovered_extensions:
            self.extension_list.add(ext_name)
            logger.debug("Extension detected: %s", ext_name)

    def _register_modules(
        self,
        discovered_modules: dict[str, ModuleInformation],
        private_mode: bool,
    ) -> None:
        """Registers discovered modules based on privacy mode."""
        if not discovered_modules:
            print("No modules are installed, quitting")
            raise SystemExit(1)

        for name, info in discovered_modules.items():
            if not info:
                continue

            is_private = bool(info.flags & ModuleFlags.private)
            should_add = (private_mode and is_private) or (
                not private_mode and not is_private
            )

            if should_add:
                self.module_list.add(name)
                self.module_settings[name] = info

    def _validate_netloc_constants(self) -> None:
        """Validates that no duplicate netlocation constants exist."""
        duplicates: set[tuple[str, str]] = set()

        for module in self.module_list:
            module_info = self.module_settings[module]
            url_constants = module_info.netlocation_constant

            if url_constants is None:
                continue

            constants = (
                url_constants if isinstance(url_constants, list) else [url_constants]
            )

            for constant in constants:
                resolved = self._resolve_netloc_constant(constant, module)
                if not resolved:
                    continue

                self._check_duplicate_constant(
                    resolved, module, module_info, duplicates
                )

        if duplicates:
            dup_str = ", ".join(f"{a} and {b}" for a, b in duplicates)
            raise ConfigurationError(
                f"Multiple modules connect to the same service names: {dup_str}"
            )

    def _resolve_netloc_constant(self, constant: str, module: str) -> str | None:
        """Resolves a netlocation constant."""
        if not constant.startswith("setting."):
            return constant

        setting_key = constant.split("setting.", 1)[1]
        # Get first account's settings for netloc resolution
        accounts = settings.modules.get(module, [])
        if not accounts:
            return None
        module_settings = accounts[0]
        return module_settings.get(setting_key)

    def _check_duplicate_constant(
        self,
        constant: str,
        module: str,
        module_info: ModuleInformation,
        duplicates: set[tuple[str, str]],
    ) -> None:
        """Checks for duplicate netlocation constants."""
        if constant not in self.module_netloc_constants:
            self.module_netloc_constants[constant] = module
            return

        existing_module = self.module_netloc_constants[constant]
        is_current_private = bool(module_info.flags & ModuleFlags.private)
        is_existing_private = bool(
            self.module_settings[existing_module].flags & ModuleFlags.private
        )

        if is_current_private and not is_existing_private:
            self.module_netloc_constants[constant] = module
        elif not (is_current_private and is_existing_private):
            m1, m2 = sorted((module, existing_module))
            duplicates.add((m1, m2))

    def _initialize_extensions(self) -> None:
        """Initializes extension instances sorted by priority.

        Priority is read from user settings, defaulting to 100 if not specified.
        """
        extension_instances: list[ExtensionInstance] = []

        for ext_name in self.extension_list:
            ext_info = self._discovered_extensions[ext_name]
            ext_settings = self._get_extension_settings(ext_name, ext_info)

            ext_class = load_extension(ext_name)
            if ext_class:
                instance = ext_class(ext_settings)
                # Get priority from user settings, default to 100
                priority = ext_settings.get("priority", 100)
                extension_instances.append(
                    ExtensionInstance(
                        name=ext_name,
                        priority=priority,
                        instance=instance,
                    )
                )

        # Sort by priority (lower numbers run first)
        self.extensions = sorted(extension_instances, key=lambda x: x.priority)

    def _get_extension_settings(self, ext_name: str, ext_info: Any) -> dict[str, Any]:
        """Gets extension settings from config or defaults."""
        ext_type = ext_info.extension_type
        type_config = settings.extensions.get(ext_type, {})
        return type_config.get(ext_name) or ext_info.settings

    async def load_module(self, module: str, account_index: int = 0) -> ModuleBase:
        """Loads and initializes a module by name with specified account.

        Args:
            module: Module name to load.
            account_index: Index of the account to use (for multi-account support).

        Returns:
            Loaded module instance.

        Raises:
            InvalidModuleError: If module doesn't exist or can't be loaded.
        """
        module = module.lower()

        if module not in self.module_list:
            raise InvalidModuleError(module)

        # Create cache key that includes account index
        cache_key = f"{module}:{account_index}"

        if cache_key in self.loaded_modules:
            return self.loaded_modules[cache_key]

        module_class = load_module(module)
        if not module_class:
            raise InvalidModuleError(module)

        controller = self._build_module_controller(module, account_index)
        loaded_module = module_class(controller)
        self.loaded_modules[cache_key] = loaded_module

        await self._handle_module_auth(module, loaded_module, account_index)
        self._ensure_module_data_folder(module)

        logger.debug("Module loaded: %s (account %d)", module, account_index)
        return loaded_module

    def _build_module_controller(
        self, module: str, account_index: int = 0
    ) -> ModuleController:
        """Builds a ModuleController for the specified module.

        Uses the specified account index to select which account settings to use.

        Args:
            module: Module name.
            account_index: Index of the account to use.

        Returns:
            Configured ModuleController instance.
        """
        accounts = settings.modules.get(module, [])

        # Get settings for specified account, or empty dict if no accounts
        if accounts and account_index < len(accounts):
            module_settings = accounts[account_index]
        else:
            module_settings = {}

        data_folder = str(self._config_dir / "modules" / module)

        return ModuleController(
            module_settings=module_settings,
            data_folder=data_folder,
            extensions=self.extensions,
            temporary_settings_controller=TemporarySettingsController(
                module, str(self._session_path), account_index
            ),
            get_current_timestamp=get_utc_timestamp,
            haberlea_options=self._build_haberlea_options(),
        )

    def _build_haberlea_options(self) -> HabeleaOptions:
        """Builds HabeleaOptions from current settings."""
        gs = settings.global_settings
        covers = gs.covers

        return HabeleaOptions(
            debug_mode=gs.advanced.debug_mode,
            quality_tier=QualityEnum[gs.general.download_quality.upper()],
            disable_subscription_check=gs.advanced.disable_subscription_checks,
            default_cover_options=CoverOptions(
                file_type=ImageFileTypeEnum[covers.external_format],
                resolution=covers.main_resolution,
                compression=CoverCompressionEnum[covers.main_compression],
            ),
        )

    async def _handle_module_auth(
        self, module: str, loaded_module: ModuleBase, account_index: int = 0
    ) -> None:
        """Handles module authentication if required.

        Args:
            module: Module name.
            loaded_module: Loaded module instance.
            account_index: Index of the account to authenticate.
        """
        module_info = self.module_settings[module]
        if module_info.login_behaviour is not ManualEnum.haberlea:
            return

        accounts = settings.modules.get(module, [])
        account_settings = (
            accounts[account_index] if account_index < len(accounts) else {}
        )

        session_name = "default" if account_index == 0 else f"account_{account_index}"
        session = read_temporary_setting(
            str(self._session_path), module, session_name=session_name
        )
        advanced_mode = settings.global_settings.advanced.advanced_login_system

        if session and session.get("clear_session") and not advanced_mode:
            await self._perform_login(
                module, loaded_module, account_settings, session, account_index
            )

        if self._should_refresh_jwt(module, session):
            refresh_fn = getattr(loaded_module, "refresh_login", None)
            if refresh_fn is not None:
                if inspect.iscoroutinefunction(refresh_fn):
                    await refresh_fn()
                else:
                    result = refresh_fn()
                    if inspect.iscoroutine(result):
                        await result

    async def _perform_login(
        self,
        module: str,
        loaded_module: ModuleBase,
        settings: dict[str, Any],
        session: dict[str, Any],
        account_index: int = 0,
    ) -> None:
        """Performs login for a module.

        Args:
            module: Module name.
            loaded_module: Loaded module instance.
            settings: Account settings dictionary.
            session: Session data dictionary.
            account_index: Index of the account to login.
        """
        module_info = self.module_settings[module]
        hashes = {k: hash_string(str(v)) for k, v in settings.items()}
        session_name = "default" if account_index == 0 else f"account_{account_index}"

        if session.get("hashes"):
            needs_login = any(
                k not in hashes or hashes[k] != v
                for k, v in session["hashes"].items()
                if k in module_info.session_settings
            )
        else:
            needs_login = True

        if not needs_login:
            return

        print(f"Logging into {module_info.service_name} (account {account_index})")
        username: str = settings.get("email") or settings.get("username") or ""
        password: str = settings.get("password", "")

        try:
            await loaded_module.login(username, password)
        except Exception:
            set_temporary_setting(
                str(self._session_path),
                module,
                "hashes",
                None,
                {},
                session_name=session_name,
            )
            raise

        set_temporary_setting(
            str(self._session_path),
            module,
            "hashes",
            None,
            hashes,
            session_name=session_name,
        )

    def _should_refresh_jwt(self, module: str, session: dict[str, Any] | None) -> bool:
        """Checks if JWT token should be refreshed."""
        if not session:
            return False

        module_info = self.module_settings[module]
        has_jwt = bool(module_info.flags & ModuleFlags.enable_jwt_system)

        return bool(has_jwt and session.get("refresh") and not session.get("bearer"))

    def _ensure_module_data_folder(self, module: str) -> None:
        """Creates module data folder if needed."""
        module_info = self.module_settings[module]
        if not (module_info.flags & ModuleFlags.uses_data):
            return

        data_folder = self._config_dir / "modules" / module
        data_folder.mkdir(parents=True, exist_ok=True)

    def _update_module_storage(self) -> None:
        """Updates and persists module settings and session storage."""
        ext_new = self._update_extension_settings()
        mod_new = self._update_module_settings_config()

        new_setting_detected = ext_new or mod_new

        advanced_mode = settings.global_settings.advanced.advanced_login_system
        sessions = self._update_sessions(advanced_mode, settings.modules)

        self._persist_settings(sessions)

        if new_setting_detected:
            print(
                "New settings detected, or the configuration has been reset. "
                "Please update settings.toml"
            )
            raise SystemExit(0)

    def _update_extension_settings(self) -> bool:
        """Updates extension settings in the current settings."""
        new_detected = False
        current_extensions = dict(settings.extensions)

        for ext_name in self.extension_list:
            ext_info = self._discovered_extensions.get(ext_name)
            if not ext_info:
                continue

            ext_type = ext_info.extension_type
            if ext_type not in current_extensions:
                current_extensions[ext_type] = {}

            if ext_name not in current_extensions[ext_type]:
                current_extensions[ext_type][ext_name] = dict(ext_info.settings)
                new_detected = True
            else:
                for key, default_value in ext_info.settings.items():
                    if key not in current_extensions[ext_type][ext_name]:
                        current_extensions[ext_type][ext_name][key] = default_value
                        new_detected = True

        set_settings(
            AppSettings(
                global_settings=settings.global_settings,
                extensions=current_extensions,
                modules=settings.modules,
            )
        )
        return new_detected

    def _update_module_settings_config(self) -> bool:
        """Updates module settings in the current settings.

        Supports multi-account structure where each module has a list of accounts.
        """
        new_detected = False
        current_modules = dict(settings.modules)
        advanced_mode = settings.global_settings.advanced.advanced_login_system

        for module_name in self.module_list:
            module_info = self.module_settings[module_name]

            if advanced_mode:
                settings_to_parse = module_info.global_settings
            else:
                settings_to_parse = {
                    **module_info.global_settings,
                    **module_info.session_settings,
                }

            if not settings_to_parse:
                continue

            # Get existing accounts list or create new one
            existing_accounts = current_modules.get(module_name, [])

            if not existing_accounts:
                # No accounts configured, create default account with settings
                current_modules[module_name] = [dict(settings_to_parse)]
                new_detected = True
            else:
                # Update each existing account with missing default settings
                for account in existing_accounts:
                    for key, default_value in settings_to_parse.items():
                        if key not in account:
                            account[key] = default_value
                            new_detected = True

        set_settings(
            AppSettings(
                global_settings=settings.global_settings,
                extensions=settings.extensions,
                modules=current_modules,
            )
        )
        return new_detected

    def _update_sessions(
        self, advanced_mode: bool, module_settings: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Updates session storage for all modules.

        Creates separate sessions for each account in multi-account setup.

        Args:
            advanced_mode: Whether advanced login mode is enabled.
            module_settings: Module settings with list of accounts per module.

        Returns:
            Updated sessions dictionary.
        """
        sessions = self._load_sessions()

        if sessions.get("advancedmode") != advanced_mode or "modules" not in sessions:
            sessions = {"advancedmode": advanced_mode, "modules": {}}

        for module_name in self.module_list:
            accounts = module_settings.get(module_name, [])
            sessions["modules"][module_name] = self._update_module_session(
                module_name,
                sessions["modules"].get(module_name),
                accounts,
                advanced_mode,
            )

        return sessions

    def _load_sessions(self) -> dict[str, Any]:
        """Loads session data from storage."""
        if not self._session_path.exists():
            return {}
        return msgspec.json.decode(self._session_path.read_bytes())

    def _update_module_session(
        self,
        module_name: str,
        existing_session: dict[str, Any] | None,
        accounts: list[dict[str, Any]],
        advanced_mode: bool,
    ) -> dict[str, Any]:
        """Updates a single module's session data.

        Creates separate session entries for each account.

        Args:
            module_name: Name of the module.
            existing_session: Existing session data if any.
            accounts: List of account settings for this module.
            advanced_mode: Whether advanced login mode is enabled.

        Returns:
            Updated session dictionary for the module.
        """
        session = existing_session or {
            "selected": "default",
            "sessions": {},
        }
        module_info = self.module_settings[module_name]

        self._update_global_storage(session, module_info)

        # Ensure sessions dict exists
        if "sessions" not in session:
            session["sessions"] = {}

        # Create/update session for each account
        for idx, account_settings in enumerate(accounts):
            session_name = "default" if idx == 0 else f"account_{idx}"

            if session_name not in session["sessions"]:
                session["sessions"][session_name] = {}

            self._update_session_entry(
                session["sessions"][session_name],
                module_info,
                account_settings,
                advanced_mode,
            )

        # If no accounts, ensure at least default session exists
        if not accounts and "default" not in session["sessions"]:
            session["sessions"]["default"] = {}

        return session

    def _update_global_storage(
        self, session: dict[str, Any], module_info: ModuleInformation
    ) -> None:
        """Updates global storage variables in session."""
        storage_vars = module_info.global_storage_variables
        if not storage_vars:
            return

        existing_data = session.get("custom_data", {})
        session["custom_data"] = {
            k: v for k, v in existing_data.items() if k in storage_vars
        }

    def _update_session_entry(
        self,
        session_data: dict[str, Any],
        module_info: ModuleInformation,
        module_settings: dict[str, Any],
        advanced_mode: bool,
    ) -> None:
        """Updates a single session entry."""
        clear_session = self._should_clear_session(
            session_data, module_info, module_settings, advanced_mode
        )
        session_data["clear_session"] = clear_session

        self._update_jwt_tokens(session_data, module_info, clear_session)
        self._update_session_storage(session_data, module_info, clear_session)

    def _should_clear_session(
        self,
        session_data: dict[str, Any],
        module_info: ModuleInformation,
        module_settings: dict[str, Any],
        advanced_mode: bool,
    ) -> bool:
        """Determines if a session should be cleared."""
        if module_info.login_behaviour is not ManualEnum.haberlea or advanced_mode:
            return False

        hashes = {k: hash_string(str(v)) for k, v in module_settings.items()}
        existing_hashes = session_data.get("hashes")

        if not existing_hashes:
            return True

        return any(
            k not in hashes or hashes[k] != v
            for k, v in existing_hashes.items()
            if k in module_info.session_settings
        )

    def _update_jwt_tokens(
        self,
        session_data: dict[str, Any],
        module_info: ModuleInformation,
        clear_session: bool,
    ) -> None:
        """Updates JWT tokens in session data."""
        has_jwt = bool(module_info.flags & ModuleFlags.enable_jwt_system)

        if not has_jwt:
            session_data.pop("bearer", None)
            session_data.pop("refresh", None)
            return

        bearer = session_data.get("bearer")
        if bearer and not clear_session:
            if self._is_jwt_expired(bearer):
                session_data["bearer"] = ""
        else:
            session_data["bearer"] = ""
            session_data["refresh"] = ""

    def _is_jwt_expired(self, bearer: str) -> bool:
        """Checks if a JWT bearer token is expired."""
        try:
            parts = bearer.split(".")
            if len(parts) < 2:
                return True

            payload = parts[1]
            # Add proper base64 padding if needed
            padding = len(payload) % 4
            if padding:
                payload += "=" * (4 - padding)

            decoded = msgspec.json.decode(base64.b64decode(payload))
            time_left = decoded["exp"] - get_utc_timestamp()
            return time_left <= 0
        except Exception:
            return True

    def _update_session_storage(
        self,
        session_data: dict[str, Any],
        module_info: ModuleInformation,
        clear_session: bool,
    ) -> None:
        """Updates session storage variables."""
        storage_vars = module_info.session_storage_variables

        if not storage_vars:
            session_data.pop("custom_data", None)
            return

        if clear_session:
            session_data["custom_data"] = {}
            return

        existing_data = session_data.get("custom_data", {})
        session_data["custom_data"] = {
            k: v for k, v in existing_data.items() if k in storage_vars
        }

    def _persist_settings(self, sessions: dict[str, Any]) -> None:
        """Persists settings and sessions to disk."""
        self._session_path.write_bytes(msgspec.json.encode(sessions))
        self._settings_loader.save(self._settings_path, settings.current)

    def clear_module_session(self, module: str) -> bool:
        """Clears all session data for a specific module.

        This will force re-login on next module load by setting the module's
        session data to an empty object.

        Args:
            module: Module name to clear session for.

        Returns:
            True if session was cleared successfully, False if module not found.
        """
        sessions = self._load_sessions()

        if "modules" not in sessions or module not in sessions["modules"]:
            return False

        sessions["modules"][module] = {}
        self._session_path.write_bytes(msgspec.json.encode(sessions))
        return True

    # =========================================================================
    # Multi-Account Support Methods
    # =========================================================================

    def get_module_account_count(self, module: str) -> int:
        """Gets the number of configured accounts for a module.

        Args:
            module: Module name.

        Returns:
            Number of configured accounts.
        """
        accounts = settings.modules.get(module, [])
        return len(accounts)

    def get_module_accounts(self, module: str) -> list[dict[str, Any]]:
        """Gets all configured accounts for a module.

        Args:
            module: Module name.

        Returns:
            List of account settings dictionaries.
        """
        return settings.modules.get(module, [])

    async def load_module_with_fallback(
        self,
        module: str,
        preferred_account_index: int = 0,
    ) -> tuple[ModuleBase, int]:
        """Loads a module, trying alternative accounts if the preferred one fails.

        Args:
            module: Module name to load.
            preferred_account_index: Preferred account index to try first.

        Returns:
            Tuple of (loaded module instance, actual account index used).

        Raises:
            InvalidModuleError: If module doesn't exist or all accounts fail.
        """
        account_count = self.get_module_account_count(module)
        if account_count == 0:
            # No accounts configured, try loading with default (empty) settings
            return await self.load_module(module, 0), 0

        # Try preferred account first
        try:
            return await self.load_module(module, preferred_account_index), (
                preferred_account_index
            )
        except Exception as e:
            logger.warning(
                "Failed to load module %s with account %d: %s",
                module,
                preferred_account_index,
                e,
            )

        # Try other accounts
        for idx in range(account_count):
            if idx == preferred_account_index:
                continue
            try:
                return await self.load_module(module, idx), idx
            except Exception as e:
                logger.warning(
                    "Failed to load module %s with account %d: %s", module, idx, e
                )

        raise InvalidModuleError(module)


# =============================================================================
# Download Orchestration - New Queue-Based System
# =============================================================================


async def haberlea_core_download(
    haberlea_session: Haberlea,
    media_to_download: dict[str, list[MediaIdentification]],
    third_party_modules: dict[ModuleModes, str],
    separate_download_module: str,
    output_path: str,
    on_queue_ready: Callable[[DownloadQueue], None] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Orchestrates media downloads using a global concurrent queue.

    This function collects all tracks from the provided media items and
    downloads them concurrently, regardless of their source module.
    Progress is reported through the global callback in utils.progress.

    Args:
        haberlea_session: The Haberlea session instance.
        media_to_download: Dictionary mapping module names to media items.
        third_party_modules: Third-party module selections for features.
        separate_download_module: Module for separate playlist downloading.
        output_path: Output directory path.
        on_queue_ready: Optional callback invoked after all items are queued,
            receives the DownloadQueue for UI progress tracking.

    Returns:
        Tuple of (completed track IDs, failed track IDs with errors).

    Raises:
        ModuleDoesNotSupportAbility: If a module lacks required capability.
        InvalidModuleError: If a specified module doesn't exist.
        InvalidInput: If an unknown media type is encountered.
    """
    gs = settings.global_settings

    # TaskGroup for managing extension tasks
    extension_tasks: asyncio.TaskGroup | None = None

    # Create job completion callback that runs extensions in background
    async def on_job_complete(job: DownloadJob) -> None:
        """Spawns background task to run extensions when job completes."""
        if extension_tasks is not None and job.download_path:
            extension_tasks.create_task(_run_extensions(haberlea_session, job))

    # Create global download queue
    queue = DownloadQueue(
        max_concurrent=gs.advanced.concurrent_downloads,
        quality_tier=QualityEnum[gs.general.download_quality.upper()],
        codec_options=CodecOptions(
            spatial_codecs=gs.codecs.spatial_codecs,
            proprietary_codecs=gs.codecs.proprietary_codecs,
        ),
        on_job_complete=on_job_complete,
    )

    # Validate and load third-party modules
    await _validate_third_party_modules(haberlea_session, third_party_modules)

    # Create downloader
    downloader = Downloader(
        haberlea_session.module_controls,
        output_path,
        queue,
        third_party_modules,
    )

    try:
        # Phase 1: Collect all tracks into the queue
        print("=== Collecting tracks ===")
        for module_name, items in media_to_download.items():
            await _queue_module_items(
                haberlea_session,
                downloader,
                module_name,
                items,
                separate_download_module,
            )

        print(f"\nTotal tracks queued: {queue.track_count}\n")

        # Notify caller that queue is ready (for UI progress tracking)
        if on_queue_ready:
            on_queue_ready(queue)

        # Phase 2: Process all tracks concurrently with extension tasks
        # TaskGroup ensures all extension tasks complete before exiting
        async with asyncio.TaskGroup() as tg:
            extension_tasks = tg
            completed, failed = await downloader.process_queue()

        # Phase 3: Finalize extensions (batch operations)
        await _run_extensions_finalize(haberlea_session)

        return completed, failed

    finally:
        await _cleanup_modules(haberlea_session)


async def _queue_module_items(
    session: Haberlea,
    downloader: Downloader,
    module_name: str,
    items: list[MediaIdentification],
    separate_download_module: str,
) -> None:
    """Queues all media items from a module.

    Args:
        session: The Haberlea session.
        downloader: The downloader instance.
        module_name: The module name.
        items: List of media items to queue.
        separate_download_module: Module for separate downloading.
    """
    # Validate module supports downloading
    supported_modes = session.module_settings[module_name].module_supported_modes
    if ModuleModes.download not in supported_modes:
        raise ModuleDoesNotSupportAbility(module_name, "track downloading")

    # Load module
    module = await session.load_module(module_name)

    # Queue each media item
    for media in items:
        await _queue_media_item(
            session,
            downloader,
            module_name,
            module,
            media,
            separate_download_module,
        )


async def _queue_media_item(
    session: Haberlea,
    downloader: Downloader,
    module_name: str,
    module: ModuleBase,
    media: MediaIdentification,
    separate_download_module: str,
    account_index: int = 0,
) -> None:
    """Queues a single media item with multi-account fallback for region restrictions.

    Args:
        session: The Haberlea session.
        downloader: The downloader instance.
        module_name: The module name.
        module: The loaded module instance.
        media: The media item to queue.
        separate_download_module: Module for separate downloading.
        account_index: Current account index being used.
    """
    media_type = media.media_type
    media_id = media.media_id

    # Handle separate download module for playlists
    custom_module: ModuleBase | None = None
    custom_module_name: str | None = None

    if (
        separate_download_module != "default"
        and separate_download_module != module_name
        and media_type is DownloadTypeEnum.playlist
    ):
        custom_module = await session.load_module(separate_download_module)
        custom_module_name = separate_download_module

    try:
        match media_type:
            case DownloadTypeEnum.album:
                await downloader.queue_album(
                    media_id, module_name, module, original_url=media.original_url
                )
            case DownloadTypeEnum.track:
                await downloader.queue_track(
                    media_id, module_name, module, original_url=media.original_url
                )
            case DownloadTypeEnum.playlist:
                await downloader.queue_playlist(
                    media_id,
                    module_name,
                    module,
                    original_url=media.original_url,
                    custom_module_name=custom_module_name,
                    custom_module=custom_module,
                )
            case DownloadTypeEnum.artist:
                await downloader.queue_artist(
                    media_id, module_name, module, original_url=media.original_url
                )
            case _:
                raise InvalidInput(
                    f'Unknown media type "{media_type}"',
                    field="media_type",
                    value=media_type,
                )
    except RegionRestrictedError:
        # Try other accounts for region-restricted content
        account_count = session.get_module_account_count(module_name)
        next_account = _find_next_account(account_index, account_count)

        if next_account is None:
            # All accounts tried, re-raise the error
            raise

        logger.warning(
            "Region restricted for %s %s with account %d, trying account %d",
            media_type.value,
            media_id,
            account_index,
            next_account,
        )
        print(
            f"Account {account_index} region restricted for {media_type.value} "
            f"{media_id}, switching to account {next_account}..."
        )

        # Load module with new account and retry
        new_module = await session.load_module(module_name, next_account)
        await _queue_media_item(
            session,
            downloader,
            module_name,
            new_module,
            media,
            separate_download_module,
            account_index=next_account,
        )


def _find_next_account(current: int, total: int) -> int | None:
    """Finds the next account index to try.

    Args:
        current: Current account index.
        total: Total number of accounts.

    Returns:
        Next account index, or None if no more accounts.
    """
    next_idx = current + 1
    if next_idx < total:
        return next_idx
    return None


async def _validate_third_party_modules(
    session: Haberlea,
    third_party_modules: dict[ModuleModes, str],
) -> None:
    """Validates and loads third-party modules.

    Args:
        session: The Haberlea session.
        third_party_modules: Module selections to validate.

    Raises:
        InvalidModuleError: If a module doesn't exist.
        ModuleDoesNotSupportAbility: If a module lacks required capability.
    """
    for mode, module_name in third_party_modules.items():
        if module_name not in session.module_list:
            raise InvalidModuleError(module_name)

        module_modes = session.module_settings[module_name].module_supported_modes
        if isinstance(mode, ModuleModes) and mode not in module_modes:
            raise ModuleDoesNotSupportAbility(module_name, str(mode))

        await session.load_module(module_name)


async def _run_extensions(session: Haberlea, job: DownloadJob) -> None:
    """Runs all extensions for a completed job in background.

    Extensions are executed in priority order (lower numbers run first).

    Args:
        session: The Haberlea session.
        job: The completed download job.
    """
    for ext in session.extensions:
        try:
            print(f"\n=== Running Extension {ext.name} (priority: {ext.priority}) ===")
            await ext.instance.on_job_complete(job)
            print(f"=== Extension {ext.name} Completed ===\n")
        except Exception:
            logger.exception("Extension %s failed for %s", ext.name, job.download_path)


async def _run_extensions_finalize(session: Haberlea) -> None:
    """Runs on_all_complete method for all extensions.

    Extensions are executed in priority order.

    Args:
        session: The Haberlea session.
    """
    for ext in session.extensions:
        try:
            await ext.instance.on_all_complete()
        except Exception:
            logger.exception("Extension %s on_all_complete failed", ext.name)


async def _cleanup_modules(session: Haberlea) -> None:
    """Closes all loaded modules to release resources.

    Args:
        session: The Haberlea session.
    """
    for module_name, module_instance in session.loaded_modules.items():
        try:
            await module_instance.close()
        except Exception:
            logger.debug("Error closing module %s", module_name)


@asynccontextmanager
async def create_haberlea_session(
    private_mode: bool = False,
    config_dir: Path | None = None,
) -> AsyncIterator[Haberlea]:
    """Creates a Haberlea session with automatic cleanup.

    Args:
        private_mode: Enable private modules only.
        config_dir: Configuration directory path.

    Yields:
        Configured Haberlea session instance.
    """
    session = Haberlea(private_mode=private_mode, config_dir=config_dir)
    try:
        yield session
    finally:
        await _cleanup_modules(session)
