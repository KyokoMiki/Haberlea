"""Modern async CLI for Haberlea music downloader.

Built with asyncclick for Python 3.14+, featuring:
- Hierarchical command groups
- Type-safe parameters
- Clean separation of concerns
- Rich help text generation
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import asyncclick as click

from .core import Haberlea, haberlea_core_download
from .music_downloader import format_duration
from .utils.models import (
    DownloadTypeEnum,
    ManualEnum,
    MediaIdentification,
    ModuleFlags,
    ModuleModes,
    SearchResult,
)
from .utils.progress import RichProgressCallback, clear_all, set_callback
from .utils.settings import reload_settings, settings

# CLI configuration constants
MEDIA_TYPES = tuple(t.name for t in DownloadTypeEnum if t.name is not None)
MEDIA_TYPES_STR = "/".join(MEDIA_TYPES)

BANNER = r'''
  _  _     ___     ___     ___     ___     _       ___     ___  
 | || |   / _ \   | _ )   | __|   | _ \   | |     | __|   / _ \ 
 | __ |   | _ |   | _ \   | _|    |   /   | |__   | _|    | _ | 
 |_||_|   |_|_|   |___/   |___|   |_|_\   |____|  |___|   |_|_| 
_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|
"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'
'''


# =============================================================================
# Helper Functions
# =============================================================================


def get_visible_modules(haberlea: Haberlea) -> list[str]:
    """Gets list of non-hidden modules.

    Args:
        haberlea: The Haberlea instance.

    Returns:
        List of visible module names.
    """
    return [
        name
        for name in haberlea.module_list
        if (
            haberlea.module_settings[name].flags is None
            or not (haberlea.module_settings[name].flags & ModuleFlags.hidden)
        )
    ]


def validate_module_name(haberlea: Haberlea, module_name: str) -> str:
    """Validates and normalizes a module name.

    Args:
        haberlea: The Haberlea instance.
        module_name: The module name to validate.

    Returns:
        Normalized module name.

    Raises:
        click.BadParameter: If module name is invalid.
    """
    module_name = module_name.lower()
    if module_name not in haberlea.module_list:
        visible = get_visible_modules(haberlea)
        raise click.BadParameter(
            f'Unknown module "{module_name}". Available: {", ".join(visible)}'
        )
    return module_name


def validate_media_type(type_str: str) -> DownloadTypeEnum:
    """Validates and converts a media type string.

    Args:
        type_str: The media type string.

    Returns:
        DownloadTypeEnum value.

    Raises:
        click.BadParameter: If media type is invalid.
    """
    try:
        return DownloadTypeEnum[type_str.lower()]
    except KeyError as e:
        raise click.BadParameter(
            f'Invalid media type "{type_str}". Choose from: {MEDIA_TYPES_STR}'
        ) from e


def format_search_result(
    index: int,
    item: SearchResult,
    query_type: DownloadTypeEnum,
) -> str:
    """Formats a search result for display.

    Args:
        index: The 1-based index of the result.
        item: The search result item.
        query_type: The type of search performed.

    Returns:
        Formatted string for display.
    """
    parts: list[str] = []

    if item.explicit:
        parts.append("[E]")
    if item.duration:
        parts.append(f"[{format_duration(item.duration)}]")
    if item.year:
        parts.append(f"[{item.year}]")
    if item.additional:
        parts.extend(f"[{a}]" for a in item.additional)

    # Extract album title from data if available
    if item.data is not None:
        first_value = next(iter(item.data.values()), None)
        if first_value is not None:
            album_data = first_value.get("album")
            if album_data is not None:
                title = album_data.get("title")
                if title:
                    parts.append("{" + title + "}")

    additional = " ".join(parts)

    if query_type is not DownloadTypeEnum.artist:
        artists = (
            ", ".join(item.artists) if isinstance(item.artists, list) else item.artists
        )
        return f"{index}. {item.name} - {artists or ''} {additional}"
    return f"{index}. {item.name} {additional}"


async def resolve_urls_to_media(
    haberlea: Haberlea,
    urls: tuple[str, ...],
) -> dict[str, list[MediaIdentification]]:
    """Resolves URLs to media identifications.

    Args:
        haberlea: The Haberlea instance.
        urls: Tuple of URLs to resolve.

    Returns:
        Dictionary mapping module names to media identifications.

    Raises:
        click.ClickException: If URL parsing fails.
    """
    media_to_download: dict[str, list[MediaIdentification]] = {}

    for link in urls:
        if not link.startswith("http"):
            raise click.ClickException(f'Invalid URL: "{link}"')

        url = urlparse(link)
        components = url.path.split("/")

        # Find matching module for URL
        service_name: str | None = None
        for pattern in haberlea.module_netloc_constants:
            if re.search(pattern, url.netloc):
                service_name = haberlea.module_netloc_constants[pattern]
                break

        if not service_name:
            raise click.ClickException(
                f'URL location "{url.netloc}" is not found in modules!'
            )

        if service_name not in media_to_download:
            media_to_download[service_name] = []

        module_settings = haberlea.module_settings[service_name]

        # Handle manual URL decoding
        if module_settings.url_decoding is ManualEnum.manual:
            module = await haberlea.load_module(service_name)
            media_to_download[service_name].append(module.custom_url_parse(link))
            continue

        # Standard URL parsing
        if not components or len(components) <= 2:
            raise click.ClickException(f'Invalid URL: "{link}"')

        url_constants = module_settings.url_constants or {
            "track": DownloadTypeEnum.track,
            "album": DownloadTypeEnum.album,
            "playlist": DownloadTypeEnum.playlist,
            "artist": DownloadTypeEnum.artist,
        }

        type_matches = [
            media_type
            for url_check, media_type in url_constants.items()
            if url_check in components
        ]

        if not type_matches:
            raise click.ClickException(f'Invalid URL: "{link}"')

        media_to_download[service_name].append(
            MediaIdentification(
                media_type=type_matches[-1],
                media_id=components[-1],
                original_url=link,
            )
        )

    return media_to_download


async def run_download_with_progress(
    haberlea: Haberlea,
    media_to_download: dict[str, list[MediaIdentification]],
    tpm: dict[ModuleModes, str],
    sdm: str,
    output_path: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Runs download with Rich progress display.

    Args:
        haberlea: The Haberlea instance.
        media_to_download: Media items to download.
        tpm: Third-party module mapping.
        sdm: Separate download module.
        output_path: Output directory path.

    Returns:
        Tuple of (completed track IDs, failed track IDs with errors).
    """
    with RichProgressCallback() as progress:
        set_callback(progress)
        try:
            completed, failed = await haberlea_core_download(
                haberlea, media_to_download, tpm, sdm, output_path
            )
        finally:
            set_callback(None)
            clear_all()

    return completed, failed


def init_haberlea_context(
    ctx: click.Context,
    private: bool,
    output: Path | None,
    lyrics: str,
    covers: str,
    credits: str,
    separate_download: str,
) -> None:
    """Initializes Haberlea and stores context for subcommands.

    Args:
        ctx: Click context.
        private: Enable private modules only.
        output: Output path override.
        lyrics: Lyrics module override.
        covers: Covers module override.
        credits: Credits module override.
        separate_download: Separate download module.
    """
    # Initialize Haberlea core
    haberlea = Haberlea(private)

    # Resolve output path
    output_path = output or Path(settings.global_settings.general.download_path)
    if str(output_path).endswith("/"):
        output_path = Path(str(output_path)[:-1])
    output_path.mkdir(parents=True, exist_ok=True)

    # Build third-party module mapping (using ModuleModes as keys)
    tpm: dict[ModuleModes, str] = {}
    for mode in (ModuleModes.covers, ModuleModes.lyrics, ModuleModes.credits):
        mode_name = mode.name
        if mode_name is None:
            continue

        module_selected: str | None = {
            "covers": covers,
            "lyrics": lyrics,
            "credits": credits,
        }.get(mode_name, "default")

        if module_selected:
            module_selected = module_selected.lower()

        if module_selected == "default":
            module_selected = getattr(
                settings.global_settings.module_defaults, mode_name, None
            )
        if module_selected == "default":
            module_selected = None

        if module_selected:
            tpm[mode] = module_selected

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["haberlea"] = haberlea
    ctx.obj["output_path"] = output_path
    ctx.obj["third_party_modules"] = tpm
    ctx.obj["separate_download"] = separate_download.lower()


# =============================================================================
# Main CLI Group
# =============================================================================


@click.group(invoke_without_command=True)
@click.option(
    "-p",
    "--private",
    is_flag=True,
    hidden=True,
    help="Enable private modules only.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Download output path. Defaults to config setting.",
)
@click.option(
    "-lr",
    "--lyrics",
    default="default",
    help="Module to get lyrics from.",
)
@click.option(
    "-cv",
    "--covers",
    default="default",
    help="Module to get covers from.",
)
@click.option(
    "-cr",
    "--credits",
    "credits_module",
    default="default",
    help="Module to get credits from.",
)
@click.option(
    "-sd",
    "--separate-download",
    default="default",
    help="Module to download playlist tracks from.",
)
@click.pass_context
async def cli(
    ctx: click.Context,
    private: bool,
    output: Path | None,
    lyrics: str,
    covers: str,
    credits_module: str,
    separate_download: str,
) -> None:
    """Haberlea - Modular music archival tool.

    Download music from various streaming services with high quality.

    \b
    Examples:
        haberlea url https://open.qobuz.com/album/...
        haberlea search qobuz album "Pink Floyd"
        haberlea download tidal track 12345678
    """
    click.echo(BANNER)

    # Store CLI options for lazy initialization
    ctx.ensure_object(dict)
    ctx.obj["_cli_options"] = {
        "private": private,
        "output": output,
        "lyrics": lyrics,
        "covers": covers,
        "credits": credits_module,
        "separate_download": separate_download,
    }
    ctx.obj["_initialized"] = False

    # If no subcommand, show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def ensure_haberlea(ctx: click.Context) -> None:
    """Ensures Haberlea is initialized in the context.

    Args:
        ctx: Click context.
    """
    if ctx.obj.get("_initialized"):
        return

    opts = ctx.obj["_cli_options"]
    init_haberlea_context(
        ctx,
        opts["private"],
        opts["output"],
        opts["lyrics"],
        opts["covers"],
        opts["credits"],
        opts["separate_download"],
    )
    ctx.obj["_initialized"] = True


def extract_context_objects(
    ctx: click.Context,
) -> tuple[Haberlea, Path, dict[ModuleModes, str], str]:
    """Extracts common context objects for commands.

    Args:
        ctx: Click context.

    Returns:
        Tuple of (haberlea, output_path, third_party_modules, separate_download).
    """
    haberlea: Haberlea = ctx.obj["haberlea"]
    output_path: Path = ctx.obj["output_path"]
    tpm: dict[ModuleModes, str] = ctx.obj["third_party_modules"]
    sdm: str = ctx.obj["separate_download"]
    return haberlea, output_path, tpm, sdm


# =============================================================================
# Standalone Commands (no Haberlea required)
# =============================================================================


@cli.command("version")
def version_command() -> None:
    """Show Haberlea version information."""
    click.echo("Haberlea v0.1.0")
    click.echo("Modular music archival tool")


# =============================================================================
# URL Download Command
# =============================================================================


@cli.command("url")
@click.argument("urls", nargs=-1, required=True)
@click.pass_context
async def download_urls(
    ctx: click.Context,
    urls: tuple[str, ...],
) -> None:
    """Download from URLs.

    All tracks are downloaded concurrently using a global queue.

    \b
    Examples:
        haberlea url https://open.qobuz.com/album/...
        haberlea url url1 url2 url3
    """
    ensure_haberlea(ctx)

    haberlea: Haberlea = ctx.obj["haberlea"]
    output_path: Path = ctx.obj["output_path"]
    tpm: dict[ModuleModes, str] = ctx.obj["third_party_modules"]
    sdm: str = ctx.obj["separate_download"]

    # Handle file input (list of URLs in a file)
    if len(urls) == 1 and os.path.isfile(urls[0]):
        with open(urls[0], encoding="utf-8") as f:
            urls = tuple(line.strip() for line in f if line.strip())

    if not urls:
        raise click.ClickException("No URLs provided.")

    # All downloads now use the global concurrent queue
    await _download_sequential(haberlea, urls, tpm, sdm, output_path)


async def _download_sequential(
    haberlea: Haberlea,
    urls: tuple[str, ...],
    tpm: dict[ModuleModes, str],
    sdm: str,
    output_path: Path,
) -> None:
    """Downloads all URLs using a global concurrent queue.

    Args:
        haberlea: The Haberlea instance.
        urls: URLs to download.
        tpm: Third-party module mapping.
        sdm: Separate download module.
        output_path: Output directory path.
    """
    media_to_download = await resolve_urls_to_media(haberlea, urls)

    completed, failed = await run_download_with_progress(
        haberlea, media_to_download, tpm, sdm, str(output_path)
    )

    if completed:
        click.echo(f"\nCompleted: {len(completed)} tracks")
    if failed:
        click.echo(f"Failed: {len(failed)} tracks")
        for track_id, error in failed:
            click.echo(f"  - {track_id}: {error}")


# =============================================================================
# Search Command
# =============================================================================


@cli.command("search")
@click.argument("module")
@click.argument("media_type")
@click.argument("query", nargs=-1, required=True)
@click.option(
    "-l",
    "--lucky",
    is_flag=True,
    help="Automatically select first result (I'm Feeling Lucky).",
)
@click.pass_context
async def search_command(
    ctx: click.Context,
    module: str,
    media_type: str,
    query: tuple[str, ...],
    lucky: bool,
) -> None:
    """Search for music and optionally download.

    \b
    Arguments:
        MODULE      Music service module (e.g., qobuz, tidal)
        MEDIA_TYPE  Type to search (track/album/artist/playlist)
        QUERY       Search query terms

    \b
    Examples:
        haberlea search qobuz album "Pink Floyd"
        haberlea search -l tidal track "Bohemian Rhapsody"
    """
    ensure_haberlea(ctx)

    haberlea, output_path, tpm, sdm = extract_context_objects(ctx)

    # Validate inputs
    module = validate_module_name(haberlea, module)
    query_type = validate_media_type(media_type)
    query_str = " ".join(query)

    # Load module and perform search
    loaded_module = await haberlea.load_module(module)
    search_limit = 1 if lucky else settings.global_settings.general.search_limit

    items = await loaded_module.search(query_type, query_str, limit=search_limit)

    if not items:
        raise click.ClickException(f"No results for {query_type.name}: {query_str}")

    # Handle lucky mode - auto-select first result
    if lucky:
        selection = 0
    else:
        # Display results
        for index, item in enumerate(items, start=1):
            click.echo(format_search_result(index, item, query_type))

        # Get user selection (use asyncclick prompt for async input)
        selection_input: str = await click.prompt("Selection: ")
        if selection_input.lower() in ("e", "q", "x", "exit", "quit"):
            raise SystemExit(0)

        if not selection_input.isdigit():
            raise click.ClickException("Please enter a number.")

        selection = int(selection_input) - 1
        if selection < 0 or selection >= len(items):
            raise click.ClickException("Invalid selection.")

        click.echo()

    # Download selected item
    selected_item: SearchResult = items[selection]
    media_to_download = {
        module: [
            MediaIdentification(
                media_type=query_type,
                media_id=selected_item.result_id,
                original_url=f"{module}:search:{query_type.value}:{selected_item.result_id}",
            )
        ]
    }

    completed, failed = await run_download_with_progress(
        haberlea, media_to_download, tpm, sdm, str(output_path)
    )

    if completed:
        click.echo(f"\nCompleted: {len(completed)} tracks")
    if failed:
        click.echo(f"Failed: {len(failed)} tracks")


# =============================================================================
# Direct Download Command
# =============================================================================


@cli.command("download")
@click.argument("module")
@click.argument("media_type")
@click.argument("media_ids", nargs=-1, required=True)
@click.pass_context
async def download_command(
    ctx: click.Context,
    module: str,
    media_type: str,
    media_ids: tuple[str, ...],
) -> None:
    """Download by module and media ID directly.

    \b
    Arguments:
        MODULE      Music service module (e.g., qobuz, tidal)
        MEDIA_TYPE  Type to download (track/album/artist/playlist)
        MEDIA_IDS   One or more media IDs

    \b
    Examples:
        haberlea download qobuz album abc123xyz
        haberlea download tidal track 12345678 87654321
    """
    ensure_haberlea(ctx)

    haberlea, output_path, tpm, sdm = extract_context_objects(ctx)

    # Validate inputs
    module = validate_module_name(haberlea, module)
    download_type = validate_media_type(media_type)

    media_to_download = {
        module: [
            MediaIdentification(
                media_type=download_type,
                media_id=mid,
                original_url=f"{module}:{download_type.value}:{mid}",
            )
            for mid in media_ids
        ]
    }

    completed, failed = await run_download_with_progress(
        haberlea, media_to_download, tpm, sdm, str(output_path)
    )

    if completed:
        click.echo(f"\nCompleted: {len(completed)} tracks")
    if failed:
        click.echo(f"Failed: {len(failed)} tracks")


# =============================================================================
# Modules Command
# =============================================================================


@cli.command("modules")
@click.pass_context
async def list_modules(ctx: click.Context) -> None:
    """List all available modules."""
    ensure_haberlea(ctx)

    haberlea: Haberlea = ctx.obj["haberlea"]

    click.echo("Available modules:")
    for module_name in sorted(get_visible_modules(haberlea)):
        info = haberlea.module_settings[module_name]
        click.echo(f"  {module_name}: {info.service_name}")


# =============================================================================
# Settings Command Group
# =============================================================================


@cli.group("settings")
@click.pass_context
async def settings_group(ctx: click.Context) -> None:
    """Manage Haberlea settings and modules.

    \b
    Examples:
        haberlea settings refresh
        haberlea settings modules
        haberlea settings module qobuz test
    """
    ensure_haberlea(ctx)


@settings_group.command("refresh")
def settings_refresh() -> None:
    """Refresh settings.toml configuration."""
    try:
        reload_settings()
        click.echo("settings.toml has been refreshed successfully.")
    except Exception as e:
        click.echo(f"Failed to refresh settings: {e}", err=True)
        raise SystemExit(1) from None


@settings_group.command("modules")
@click.pass_context
async def settings_list_modules(ctx: click.Context) -> None:
    """List all installed modules."""
    haberlea: Haberlea = ctx.obj["haberlea"]

    click.echo("Installed modules:")
    for module_name in sorted(haberlea.module_list):
        info = haberlea.module_settings[module_name]
        test_status = "+" if info.test_url else "-"
        click.echo(f"  {module_name}: {info.service_name} [test: {test_status}]")


@settings_group.command("test-all")
@click.pass_context
async def settings_test_all(ctx: click.Context) -> None:
    """Test all installed modules by downloading their test URLs."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    output_path: Path = ctx.obj["output_path"]
    tpm: dict[ModuleModes, str] = ctx.obj["third_party_modules"]
    sdm: str = ctx.obj["separate_download"]

    click.echo("Testing all installed modules...\n")

    test_urls = []
    module_names = []

    for module_name in sorted(haberlea.module_list):
        test_url = haberlea.module_settings[module_name].test_url
        if test_url:
            test_urls.append(test_url)
            module_names.append(module_name)
            click.echo(f"  {module_name}: {test_url}")
        else:
            click.echo(f"  {module_name}: no test URL configured (skipped)")

    if not test_urls:
        click.echo("\nNo modules with test URLs found.")
        return

    click.echo(f"\nRunning tests for {len(test_urls)} modules...\n")

    try:
        media_to_download = await resolve_urls_to_media(haberlea, tuple(test_urls))
        completed, failed = await run_download_with_progress(
            haberlea, media_to_download, tpm, sdm, str(output_path)
        )

        click.echo("\n=== Test Results ===")
        click.echo(f"Completed: {len(completed)} tracks")
        if failed:
            click.echo(f"Failed: {len(failed)} tracks")
            for track_id, error in failed:
                click.echo(f"  - {track_id}: {error}")
    except Exception as e:
        click.echo(f"\nTest failed with error: {e}", err=True)
        raise


# =============================================================================
# Module Subcommand Group
# =============================================================================


@settings_group.group("module")
@click.argument("module_name")
@click.pass_context
async def module_group(ctx: click.Context, module_name: str) -> None:
    """Module-specific settings and operations.

    \b
    Examples:
        haberlea settings module qobuz test
        haberlea settings module tidal info
    """
    haberlea: Haberlea = ctx.obj["haberlea"]
    module_name = validate_module_name(haberlea, module_name)
    ctx.obj["target_module"] = module_name


@module_group.command("test")
@click.pass_context
async def module_test(ctx: click.Context) -> None:
    """Test a specific module with its test URL."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    module_name: str = ctx.obj["target_module"]
    output_path: Path = ctx.obj["output_path"]
    tpm: dict[ModuleModes, str] = ctx.obj["third_party_modules"]
    sdm: str = ctx.obj["separate_download"]

    test_url = haberlea.module_settings[module_name].test_url
    if not test_url:
        raise click.ClickException(f"Module {module_name} has no test URL configured.")

    click.echo(f"Testing module {module_name} with URL: {test_url}")

    media_to_download = await resolve_urls_to_media(haberlea, (test_url,))

    completed, failed = await run_download_with_progress(
        haberlea, media_to_download, tpm, sdm, str(output_path)
    )

    if completed:
        click.echo(f"\nTest completed: {len(completed)} tracks")
    if failed:
        click.echo(f"Test failed: {len(failed)} tracks")


@module_group.command("info")
@click.pass_context
async def module_info(ctx: click.Context) -> None:
    """Show detailed information about a module."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    module_name: str = ctx.obj["target_module"]

    info = haberlea.module_settings[module_name]

    click.echo(f"Module: {module_name}")
    click.echo(f"  Service: {info.service_name}")
    click.echo(f"  Modes: {info.module_supported_modes}")
    click.echo(f"  Flags: {info.flags}")
    click.echo(f"  Test URL: {info.test_url or 'Not configured'}")
    click.echo(f"  URL Decoding: {info.url_decoding.value}")
    click.echo(f"  Login Behavior: {info.login_behaviour.value}")


# =============================================================================
# Sessions Command Group
# =============================================================================


@cli.group("sessions")
@click.pass_context
async def sessions_group(ctx: click.Context) -> None:
    """Manage module authentication sessions.

    \b
    Examples:
        haberlea sessions list qobuz
        haberlea sessions info tidal
    """
    ensure_haberlea(ctx)


@sessions_group.command("list")
@click.argument("module")
@click.pass_context
async def sessions_list(ctx: click.Context, module: str) -> None:
    """List sessions for a module."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    module = validate_module_name(haberlea, module)

    click.echo(f"Sessions for module {module}:")
    click.echo("  - default (active)")
    click.echo()
    click.echo("Note: Session listing is managed automatically in simple mode.")
    click.echo("For advanced mode, edit loginstorage.json in your config directory.")


@sessions_group.command("info")
@click.argument("module")
@click.pass_context
async def sessions_info(ctx: click.Context, module: str) -> None:
    """Show session information for a module."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    module = validate_module_name(haberlea, module)

    info = haberlea.module_settings[module]
    click.echo(f"Session info for {module}:")
    click.echo(f"  Login behavior: {info.login_behaviour.value}")
    click.echo(f"  Session settings: {list(info.session_settings.keys())}")
    click.echo(f"  Storage variables: {info.session_storage_variables}")


@sessions_group.command("clear")
@click.argument("module")
@click.confirmation_option(prompt="Are you sure you want to clear this session?")
@click.pass_context
async def sessions_clear(ctx: click.Context, module: str) -> None:
    """Clear session data for a module to force re-login."""
    haberlea: Haberlea = ctx.obj["haberlea"]
    module = validate_module_name(haberlea, module)

    if haberlea.clear_module_session(module):
        click.echo(f"Session for {module} has been cleared.")
        click.echo("The module will re-authenticate on next use.")
    else:
        click.echo(f"Failed to clear session for {module}.", err=True)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Main entry point for the Haberlea CLI."""
    try:
        cli(_anyio_backend_options={"use_uvloop": True})
    except KeyboardInterrupt:
        click.echo("\n\t^C pressed - abort")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
