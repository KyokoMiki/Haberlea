"""Settings data structures for Haberlea.

This module defines all settings as msgspec.Struct classes for type-safe
configuration management. Settings are organized hierarchically and support
TOML serialization/deserialization via msgspec.
"""

import secrets
from pathlib import Path
from typing import Any

import msgspec
import platformdirs

# =============================================================================
# Global Settings Structures
# =============================================================================


class GeneralSettings(msgspec.Struct, kw_only=True):
    """General application settings.

    Attributes:
        download_path: Default download directory path.
        download_quality: Audio quality tier (minimum/low/medium/high/lossless/hifi).
        search_limit: Maximum number of search results to return.
        temp_path: Temporary files directory path. Defaults to system temp directory.
    """

    download_path: str = "./downloads/"
    download_quality: str = "hifi"
    search_limit: int = 10
    temp_path: str = ""


class ArtistDownloadingSettings(msgspec.Struct, kw_only=True):
    """Artist downloading behavior settings.

    Attributes:
        return_credited_albums: Include albums where artist is credited.
        separate_tracks_skip_downloaded: Skip tracks already downloaded in albums.
        ignore_different_artists: Skip tracks from different artists.
    """

    return_credited_albums: bool = True
    separate_tracks_skip_downloaded: bool = True
    ignore_different_artists: bool = True


class FormattingSettings(msgspec.Struct, kw_only=True):
    """File and folder naming format settings.

    Attributes:
        album_format: Format string for album folder names.
        playlist_format: Format string for playlist folder names.
        track_filename_format: Format string for track file names.
        single_full_path_format: Format string for single track downloads.
        enable_zfill: Zero-pad track numbers.
        force_album_format: Always use album format even for singles.
    """

    album_format: str = "{name}{explicit}"
    playlist_format: str = "{name}{explicit}"
    track_filename_format: str = "{track_number}. {name}"
    single_full_path_format: str = "{name}"
    enable_zfill: bool = True
    force_album_format: bool = False


class CodecsSettings(msgspec.Struct, kw_only=True):
    """Audio codec preference settings.

    Attributes:
        proprietary_codecs: Allow proprietary codecs (MQA, Dolby, etc.).
        spatial_codecs: Allow spatial audio codecs (Atmos, 360RA, etc.).
    """

    proprietary_codecs: bool = False
    spatial_codecs: bool = True


class ModuleDefaultsSettings(msgspec.Struct, kw_only=True):
    """Default module selection for various features.

    Attributes:
        lyrics: Default module for lyrics fetching.
        covers: Default module for cover art fetching.
        credits: Default module for credits fetching.
    """

    lyrics: str = "default"
    covers: str = "default"
    credits: str = "default"


class LyricsSettings(msgspec.Struct, kw_only=True):
    """Lyrics handling settings.

    Attributes:
        embed_lyrics: Embed plain lyrics in audio files.
        embed_synced_lyrics: Embed synced (timed) lyrics in audio files.
        save_synced_lyrics: Save synced lyrics as separate .lrc files.
    """

    embed_lyrics: bool = True
    embed_synced_lyrics: bool = False
    save_synced_lyrics: bool = True


class CoversSettings(msgspec.Struct, kw_only=True):
    """Cover art handling settings.

    Attributes:
        embed_cover: Embed cover art in audio files.
        restrict_cover_size: Limit cover art file size.
        main_compression: Compression level for embedded covers (low/high).
        main_resolution: Resolution for embedded covers in pixels.
        save_external: Save cover art as separate files.
        external_format: Format for external cover files (jpg/png/webp).
        external_compression: Compression for external covers (low/high).
        external_resolution: Resolution for external covers in pixels.
        save_animated_cover: Save animated covers when available.
    """

    embed_cover: bool = True
    restrict_cover_size: bool = False
    main_compression: str = "high"
    main_resolution: int = 1400
    save_external: bool = False
    external_format: str = "png"
    external_compression: str = "low"
    external_resolution: int = 3000
    save_animated_cover: bool = True


class PlaylistSettings(msgspec.Struct, kw_only=True):
    """Playlist export settings.

    Attributes:
        save_m3u: Generate M3U playlist files.
        paths_m3u: Path type in M3U files (absolute/relative).
        extended_m3u: Use extended M3U format with metadata.
    """

    save_m3u: bool = True
    paths_m3u: str = "absolute"
    extended_m3u: bool = True


class AdvancedSettings(msgspec.Struct, kw_only=True):
    """Advanced configuration settings.

    Attributes:
        advanced_login_system: Use advanced multi-session login system.
        codec_conversions: Codec conversion mappings (e.g., alac -> flac).
        conversion_flags: FFmpeg/encoder flags for conversions.
        conversion_keep_original: Keep original files after conversion.
        cover_variance_threshold: Threshold for cover image comparison.
        debug_mode: Enable debug logging.
        disable_subscription_checks: Skip subscription validation.
        dry_run: Skip actual downloads, only collect track info.
        enable_undesirable_conversions: Allow lossy-to-lossy conversions.
        ignore_existing_files: Re-download existing files.
        abort_download_when_single_failed: Stop on first track failure.
        concurrent_downloads: Maximum concurrent track downloads.
    """

    advanced_login_system: bool = False
    codec_conversions: dict[str, str] = msgspec.field(
        default_factory=lambda: {"alac": "flac", "wav": "flac"}
    )
    conversion_flags: dict[str, dict[str, str]] = msgspec.field(
        default_factory=lambda: {"flac": {"compression_level": "5"}}
    )
    conversion_keep_original: bool = False
    cover_variance_threshold: int = 8
    debug_mode: bool = False
    disable_subscription_checks: bool = False
    dry_run: bool = False
    enable_undesirable_conversions: bool = False
    ignore_existing_files: bool = False
    abort_download_when_single_failed: bool = False
    concurrent_downloads: int = 5


class WebuiSettings(msgspec.Struct, kw_only=True):
    """WebUI settings.

    Attributes:
        host: Server host address (empty string for all interfaces).
        port: Server port number.
        auth_enabled: Whether authentication is enabled.
        username: Login username.
        password: Login password.
        storage_secret: Secret key for session storage encryption.
        language: Interface language (zh_CN or en_US).
    """

    host: str = ""
    port: int = 7628
    auth_enabled: bool = False
    username: str = "admin"
    password: str = msgspec.field(default_factory=lambda: secrets.token_urlsafe(32))
    storage_secret: str = msgspec.field(
        default_factory=lambda: secrets.token_urlsafe(32)
    )
    language: str = "zh_CN"


class GlobalSettings(msgspec.Struct, kw_only=True):
    """Complete global settings container.

    Attributes:
        general: General application settings.
        artist_downloading: Artist downloading behavior.
        formatting: File/folder naming formats.
        codecs: Codec preferences.
        module_defaults: Default module selections.
        lyrics: Lyrics handling settings.
        covers: Cover art settings.
        playlist: Playlist export settings.
        advanced: Advanced configuration.
        webui: WebUI settings.
    """

    general: GeneralSettings = msgspec.field(default_factory=GeneralSettings)
    artist_downloading: ArtistDownloadingSettings = msgspec.field(
        default_factory=ArtistDownloadingSettings
    )
    formatting: FormattingSettings = msgspec.field(default_factory=FormattingSettings)
    codecs: CodecsSettings = msgspec.field(default_factory=CodecsSettings)
    module_defaults: ModuleDefaultsSettings = msgspec.field(
        default_factory=ModuleDefaultsSettings
    )
    lyrics: LyricsSettings = msgspec.field(default_factory=LyricsSettings)
    covers: CoversSettings = msgspec.field(default_factory=CoversSettings)
    playlist: PlaylistSettings = msgspec.field(default_factory=PlaylistSettings)
    advanced: AdvancedSettings = msgspec.field(default_factory=AdvancedSettings)
    webui: WebuiSettings = msgspec.field(default_factory=WebuiSettings)


# =============================================================================
# Application Settings Container
# =============================================================================


class AppSettings(msgspec.Struct, kw_only=True):
    """Complete application settings.

    Attributes:
        global_settings: Global settings (serialized as "global" in TOML).
        extensions: Extension-specific settings by type and name.
        modules: Module-specific settings by name, each module has a list of accounts.
    """

    global_settings: GlobalSettings = msgspec.field(
        default_factory=GlobalSettings, name="global"
    )
    extensions: dict[str, dict[str, dict[str, Any]]] = msgspec.field(
        default_factory=dict
    )
    modules: dict[str, list[dict[str, Any]]] = msgspec.field(default_factory=dict)


# =============================================================================
# Settings I/O Utilities
# =============================================================================


def load_settings(path: Path) -> AppSettings:
    """Loads settings from a TOML file.

    Args:
        path: Path to the settings TOML file.

    Returns:
        AppSettings instance. Returns defaults if file doesn't exist.
    """
    if not path.exists():
        return AppSettings()
    return msgspec.toml.decode(path.read_bytes(), type=AppSettings)


def save_settings(path: Path, settings: AppSettings) -> None:
    """Saves settings to a TOML file.

    Args:
        path: Path to save the settings file.
        settings: AppSettings instance to save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = msgspec.toml.encode(settings)
    path.write_bytes(data)


def get_default_settings() -> AppSettings:
    """Creates default application settings.

    Returns:
        AppSettings instance with all default values.
    """
    return AppSettings()


# Global settings singleton
_app_settings: AppSettings | None = None
_settings_path: Path = (
    Path(platformdirs.user_config_dir("Haberlea", ensure_exists=True)) / "settings.toml"
)


class _SettingsProxy:
    """Proxy class for lazy-loading global settings."""

    @property
    def current(self) -> AppSettings:
        """Gets the current global settings, loading if needed."""
        global _app_settings
        if _app_settings is None:
            _app_settings = load_settings(_settings_path)
        return _app_settings

    @property
    def global_settings(self) -> GlobalSettings:
        """Gets the global settings section."""
        return self.current.global_settings

    @property
    def extensions(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Gets the extensions settings section."""
        return self.current.extensions

    @property
    def modules(self) -> dict[str, list[dict[str, Any]]]:
        """Gets the modules settings section."""
        return self.current.modules


settings = _SettingsProxy()


def get_settings_path() -> Path:
    """Returns the current settings file path.

    Returns:
        Path to the current settings TOML file.
    """
    return _settings_path


def set_settings_path(path: Path) -> None:
    """Sets the settings file path and reloads settings.

    Args:
        path: Path to the settings TOML file.
    """
    global _app_settings, _settings_path
    _settings_path = path
    _app_settings = load_settings(path)


def set_settings(new_settings: AppSettings) -> None:
    """Sets the global settings directly.

    Use this to sync settings when they are modified elsewhere (e.g., by Haberlea).

    Args:
        new_settings: The new AppSettings instance.
    """
    global _app_settings
    _app_settings = new_settings


def reload_settings() -> AppSettings:
    """Reloads settings from the current path.

    Returns:
        The reloaded AppSettings instance.
    """
    global _app_settings
    _app_settings = load_settings(_settings_path)
    return _app_settings
