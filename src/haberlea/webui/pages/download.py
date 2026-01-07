"""Download page for Haberlea WebUI."""

import contextlib
import traceback
from typing import Any

from nicegui import app, ui

from haberlea.i18n import _

from ...cli import resolve_urls_to_media
from ...core import Haberlea, haberlea_core_download
from ...download_queue import DownloadQueue
from ...plugins.base import ExtensionBase
from ...utils.models import (
    MediaIdentification,
    ModuleModes,
)
from ...utils.progress import ProgressEvent, clear_all, set_callback
from ...utils.settings import _settings_path, save_settings, settings
from ..state import add_log, get_app_storage


class DownloadPage:
    """Download page component with job-based download queue display."""

    def __init__(self) -> None:
        """Initialize download page."""
        self.url_input: ui.textarea | None = None
        self.download_log: ui.log | None = None
        self._is_downloading: bool = False

        # Job-based progress tracking
        self._jobs: dict[str, dict[str, Any]] = {}
        self._track_progress: dict[str, dict[str, Any]] = {}

        # UI element references for updates
        self._job_cards: dict[str, ui.card] = {}
        self._job_progress_bars: dict[str, ui.linear_progress] = {}
        self._job_status_labels: dict[str, ui.label] = {}
        self._job_expansions: dict[str, ui.expansion] = {}
        self._track_rows: dict[str, ui.row] = {}
        self._track_progress_bars: dict[str, ui.linear_progress] = {}

        # Reference to the actual download queue (set during download)
        self._download_queue: DownloadQueue | None = None

    def render(self) -> None:
        """Renders the download page."""
        with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
            ui.label(_("Music Download")).classes("text-2xl font-bold")
            self._render_url_input()
            self._render_quick_options()
            self._render_queue_card()
            self._render_log_card()

        self._check_url_parameter()

    def _check_url_parameter(self) -> None:
        """Check for URL query parameter and fill input if present."""
        url_param = app.storage.browser.get("url_param")
        if url_param and self.url_input:
            self.url_input.value = url_param
            app.storage.browser["url_param"] = None
            ui.notify(_("Download link added, click to start download"), type="info")

    def _render_url_input(self) -> None:
        """Render URL input section."""
        with ui.card().classes("w-full"):
            ui.label(_("Enter Download URL")).classes("text-lg font-semibold mb-2")
            with ui.row().classes("w-full gap-2 items-end"):
                self.url_input = (
                    ui.textarea(
                        label=_("URL (one per line)"), placeholder="https://..."
                    )
                    .classes("flex-grow")
                    .props("rows=3")
                )
                ui.button(
                    _("Start Download"), icon="download", on_click=self._start_download
                ).props("color=primary")

    def _render_quick_options(self) -> None:
        """Render quick options section."""
        with ui.card().classes("w-full"):
            ui.label(_("Quick Options")).classes("text-lg font-semibold mb-2")
            with ui.row().classes("gap-4 flex-wrap"):
                ui.checkbox(
                    _("Dry Run (Collect info only, no download)"),
                    value=settings.global_settings.advanced.dry_run,
                    on_change=self._on_dry_run_change,
                )

    def _on_dry_run_change(self, e: Any) -> None:
        """Handles dry run checkbox change and saves settings.

        Args:
            e: The change event containing the new value.
        """
        settings.global_settings.advanced.dry_run = e.value
        save_settings(_settings_path, settings.current)
        ui.notify(
            f"{_('Dry Run')} {_('enabled') if e.value else _('disabled')}", type="info"
        )

    def _render_queue_card(self) -> None:
        """Render download queue card."""
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full justify-between items-center mb-2"):
                ui.label(_("Download Queue")).classes("text-lg font-semibold")
                ui.button(
                    _("Clear"), icon="delete_sweep", on_click=self._clear_queue
                ).props("flat dense")
            self._render_queue()

    def _render_log_card(self) -> None:
        """Render log card."""
        with ui.card().classes("w-full"):
            ui.label(_("Download Log")).classes("text-lg font-semibold mb-2")
            self.download_log = ui.log(max_lines=100).classes("w-full h-64")
            storage = get_app_storage()
            for log_msg in storage.get("logs", [])[-50:]:
                self.download_log.push(log_msg)

    @ui.refreshable_method
    def _render_queue(self) -> None:
        """Renders the job-based download queue display."""
        # Save expansion states before refresh
        saved_states: dict[str, bool] = {}
        for job_id, expansion in self._job_expansions.items():
            with contextlib.suppress(RuntimeError):
                saved_states[job_id] = expansion.value

        # Clear UI element references (will be recreated)
        self._job_cards.clear()
        self._job_progress_bars.clear()
        self._job_status_labels.clear()
        self._job_expansions.clear()
        self._track_rows.clear()
        self._track_progress_bars.clear()

        if not self._jobs:
            ui.label(_("Queue is empty")).classes("text-gray-500 py-4")
            return

        # Summary stats
        total_jobs = len(self._jobs)
        total_tracks = sum(j.get("total_tracks", 0) for j in self._jobs.values())
        completed_tracks = sum(j.get("completed", 0) for j in self._jobs.values())
        failed_tracks = sum(j.get("failed", 0) for j in self._jobs.values())

        ui.label(
            f"共 {total_jobs} 个任务 | {total_tracks} 首曲目 | "
            f"完成: {completed_tracks} | 失败: {failed_tracks}"
        ).classes("text-sm text-gray-600 mb-2")

        # Render each job with saved expansion state
        for job_id, job_data in self._jobs.items():
            expanded = saved_states.get(job_id, True)
            self._render_job_card(job_id, job_data, expanded)

    def _render_job_card(
        self, job_id: str, job_data: dict[str, Any], expanded: bool = True
    ) -> None:
        """Renders a single job card with its tracks.

        Args:
            job_id: The job identifier.
            job_data: Job data dictionary.
            expanded: Whether the track list should be expanded.
        """
        status = job_data.get("status", "pending")
        media_type = job_data.get("media_type", "unknown")
        name = job_data.get("name", job_data.get("original_url", job_id)[:50])
        artist = job_data.get("artist", "")

        # Media type icons
        type_icons = {
            "track": "music_note",
            "album": "album",
            "playlist": "queue_music",
            "artist": "person",
        }
        # Status colors
        status_colors = {
            "pending": "bg-gray-100",
            "downloading": "bg-blue-50",
            "completed": "bg-green-50",
            "partial": "bg-orange-50",
            "failed": "bg-red-50",
        }

        card_class = status_colors.get(status, "bg-gray-100")
        with ui.card().classes(f"w-full {card_class} mb-2") as card:
            self._job_cards[job_id] = card

            # Job header
            with ui.row().classes("w-full items-center gap-2"):
                ui.icon(type_icons.get(media_type, "help")).classes("text-gray-600")
                with ui.column().classes("flex-grow min-w-0"):
                    display_name = f"{artist} - {name}" if artist else name
                    ui.label(display_name).classes("font-medium truncate")

                    # Progress info
                    total = job_data.get("total_tracks", 0)
                    completed = job_data.get("completed", 0)
                    failed = job_data.get("failed", 0)
                    skipped = job_data.get("skipped", 0)
                    finished = completed + failed + skipped

                    status_text = f"{finished}/{total} 曲目"
                    if failed > 0:
                        status_text += f" ({failed} 失败)"
                    status_label = ui.label(status_text).classes(
                        "text-xs text-gray-500"
                    )
                    self._job_status_labels[job_id] = status_label

                # Job progress bar
                progress = job_data.get("progress", 0.0)
                progress_bar = ui.linear_progress(value=progress, show_value=True)
                progress_bar.classes("w-32")
                self._job_progress_bars[job_id] = progress_bar

            # Expandable track list with preserved state
            track_ids = job_data.get("track_ids", [])
            if track_ids:
                expansion = ui.expansion(
                    f"{_('Track list')} ({len(track_ids)})", value=expanded
                ).classes("w-full")
                self._job_expansions[job_id] = expansion
                with expansion:
                    for track_id in track_ids[:50]:
                        track_data = self._track_progress.get(track_id, {})
                        self._render_track_row(track_id, track_data)
                    if len(track_ids) > 50:
                        ui.label(
                            f"... {_('and')} {len(track_ids) - 50} {_('more')}"
                        ).classes("text-sm text-gray-500 py-1")

    def _render_track_row(self, track_id: str, track_data: dict[str, Any]) -> None:
        """Renders a single track row within a job.

        Args:
            track_id: The track identifier.
            track_data: Track progress data.
        """
        status = track_data.get("status", "pending")
        status_icons = {
            "pending": "schedule",
            "downloading": "downloading",
            "completed": "check_circle",
            "failed": "error",
            "skipped": "skip_next",
        }
        status_colors = {
            "pending": "text-gray-400",
            "downloading": "text-blue-500",
            "completed": "text-green-500",
            "failed": "text-red-500",
            "skipped": "text-orange-500",
        }

        with ui.row().classes(
            "w-full items-center gap-2 py-1 border-b border-gray-100"
        ) as row:
            self._track_rows[track_id] = row

            ui.icon(status_icons.get(status, "help")).classes(
                f"text-sm {status_colors.get(status, 'text-gray-400')}"
            )

            name = track_data.get("name", track_id[:20])
            artist = track_data.get("artist", "")
            display = f"{artist} - {name}" if artist else name
            ui.label(display).classes("text-sm flex-grow truncate")

            message = track_data.get("message", "")
            if message:
                ui.label(message).classes("text-xs text-gray-500")

            if status == "downloading":
                progress = track_data.get("progress", 0.0)
                progress_bar = ui.linear_progress(value=progress).classes("w-20")
                self._track_progress_bars[track_id] = progress_bar

    def _clear_queue(self) -> None:
        """Clears the job queue."""
        self._jobs.clear()
        self._track_progress.clear()
        self._job_cards.clear()
        self._job_progress_bars.clear()
        self._job_status_labels.clear()
        self._track_rows.clear()
        self._track_progress_bars.clear()
        self._render_queue.refresh()
        ui.notify(_("Queue cleared"), type="info")

    def _on_progress(self, event: ProgressEvent) -> None:
        """Callback for track progress updates.

        Args:
            event: Progress event from the unified progress system.
        """
        task_id = event.task_id
        old_status = self._track_progress.get(task_id, {}).get("status")
        new_status = event.status.value

        self._track_progress[task_id] = {
            "task_id": task_id,
            "name": event.name,
            "artist": event.artist,
            "album": event.album,
            "service": event.service,
            "status": new_status,
            "progress": event.progress,
            "message": event.message,
        }

        # Update job progress from the actual queue
        self._sync_job_progress()

        with contextlib.suppress(RuntimeError):
            # If status changed, refresh the whole queue display
            if old_status != new_status:
                self._render_queue.refresh()
                return

            # Otherwise just update the progress bar
            if task_id in self._track_progress_bars:
                self._track_progress_bars[task_id].set_value(round(event.progress, 2))

    def _sync_job_progress(self) -> None:
        """Syncs job progress from the actual download queue."""
        if not self._download_queue:
            return

        for job in self._download_queue.get_all_jobs():
            job_id = job.job_id
            progress = self._download_queue.get_job_progress(job_id)

            if job_id in self._jobs:
                self._jobs[job_id].update(
                    {
                        "status": job.status.value,
                        "completed": progress.completed,
                        "failed": progress.failed,
                        "skipped": progress.skipped,
                        "progress": progress.progress,
                    }
                )

            with contextlib.suppress(RuntimeError):
                if job_id in self._job_progress_bars:
                    # Use 1.0 if job is finished to ensure final state is correct
                    if progress.is_finished:
                        display_progress = 1.0
                    else:
                        display_progress = progress.progress
                    self._job_progress_bars[job_id].set_value(
                        round(display_progress, 2)
                    )
                if job_id in self._job_status_labels:
                    finished = progress.finished
                    status_text = f"{finished}/{progress.total} 曲目"
                    if progress.failed > 0:
                        status_text += f" ({progress.failed} 失败)"
                    self._job_status_labels[job_id].set_text(status_text)

    def _register_jobs_from_queue(self, queue: DownloadQueue) -> None:
        """Registers jobs from the download queue for UI display.

        Args:
            queue: The download queue instance.
        """
        self._download_queue = queue

        for job in queue.get_all_jobs():
            self._jobs[job.job_id] = {
                "job_id": job.job_id,
                "original_url": job.original_url,
                "media_type": job.media_type.value,
                "name": job.name,
                "artist": job.artist,
                "status": job.status.value,
                "total_tracks": job.total_tracks,
                "completed": len(job.completed_tracks),
                "failed": len(job.failed_tracks),
                "skipped": len(job.skipped_tracks),
                "progress": job.progress,
                "track_ids": list(job.track_ids),
            }

        self._render_queue.refresh()

    async def _start_download(self) -> None:
        """Starts downloading URLs from input."""
        if self._is_downloading:
            ui.notify(_("Download in progress"), type="warning")
            return

        if not self.url_input or not self.url_input.value:
            ui.notify(_("Please enter download URL"), type="warning")
            return

        urls = [url for url in self.url_input.value.split() if url.startswith("http")]

        if not urls:
            ui.notify(_("Please enter valid download URL"), type="warning")
            return

        self.url_input.value = ""
        self._is_downloading = True
        self._jobs.clear()
        self._track_progress.clear()
        self._render_queue.refresh()

        try:
            await self.download_urls(urls)
        finally:
            self._is_downloading = False
            self._download_queue = None
            self._render_queue.refresh()

    async def download_urls(self, urls: list[str]) -> None:
        """Downloads multiple URLs using the job-based queue.

        This method can be called from other pages to trigger downloads.

        Args:
            urls: List of URLs to download.
        """
        self._log(f"{_('Starting download')} {len(urls)} {_('links')}")
        set_callback(self._on_progress)

        try:
            haberlea = Haberlea()
            media_to_download = await resolve_urls_to_media(haberlea, tuple(urls))

            for service, media_list in media_to_download.items():
                self._log(f"{_('Service')} {service}: {len(media_list)} {_('items')}")

            output_path = settings.global_settings.general.download_path

            tpm: dict[ModuleModes, str] = {}
            for mode_name in ["covers", "lyrics", "credits"]:
                mode_value: str | None = getattr(
                    settings.global_settings.module_defaults, mode_name, "default"
                )
                if mode_value and mode_value != "default":
                    tpm[ModuleModes[mode_name]] = mode_value

            # Use custom download function that exposes the queue
            completed, failed = await self._run_download_with_queue(
                haberlea,
                media_to_download,
                tpm,
                "default",
                output_path,
            )

            self._log(
                f"{_('Done')}: {len(completed)} {_('success')}, "
                f"{len(failed)} {_('failed')}"
            )

        except (ValueError, OSError) as e:
            # Handle common errors from URL parsing and file operations
            self._log(f"{_('Download error')}: {e}")
            self._log(f"{_('Details')}: {traceback.format_exc()}")
        except Exception as e:
            # Catch any unexpected errors and log them
            self._log(f"{_('Unexpected error')}: {e}")
            self._log(f"{_('Details')}: {traceback.format_exc()}")
        finally:
            set_callback(None)
            clear_all()

    async def _run_download_with_queue(
        self,
        haberlea_session: Haberlea,
        media_to_download: dict[str, list[MediaIdentification]],
        third_party_modules: dict[ModuleModes, str],
        separate_download_module: str,
        output_path: str,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Runs download using core function with UI progress tracking.

        Args:
            haberlea_session: The Haberlea session.
            media_to_download: Media items to download by module.
            third_party_modules: Third-party module mappings.
            separate_download_module: Module for separate downloading.
            output_path: Output directory path.

        Returns:
            Tuple of (completed track IDs, failed track IDs with errors).
        """
        # Set extension log callback to route output to WebUI
        ExtensionBase.set_log_callback(self._log)

        def on_queue_ready(queue: DownloadQueue) -> None:
            """Registers queue for UI display when ready."""
            self._register_jobs_from_queue(queue)
            self._log(
                f"{_('Added')} {queue.job_count} {_('jobs')}, "
                f"{queue.track_count} {_('tracks')}"
            )

        try:
            completed, failed = await haberlea_core_download(
                haberlea_session,
                media_to_download,
                third_party_modules,
                separate_download_module,
                output_path,
                on_queue_ready=on_queue_ready,
            )

            # Final sync to ensure UI shows 100% completion
            self._sync_job_progress()

            return completed, failed
        finally:
            ExtensionBase.set_log_callback(None)

    def _log(self, message: str) -> None:
        """Logs a message.

        Args:
            message: Message to log.
        """
        add_log(message)
        if self.download_log:
            with contextlib.suppress(RuntimeError):
                self.download_log.push(message)
