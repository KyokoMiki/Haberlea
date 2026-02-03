"""Global download queue system with job-based organization.

This module provides a unified queue system that organizes downloads by job
(original URL/request) while executing track downloads concurrently.
Jobs represent the original download request (album, playlist, artist, track),
while tracks are the actual execution units.
"""

import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

import anyio
import msgspec

from .plugins.base import ModuleBase
from .utils.models import (
    CodecOptions,
    QualityEnum,
    TrackInfo,
)
from .utils.progress import (
    ProgressStatus,
    create_task,
    update,
)

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a download job."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some tracks failed
    FAILED = "failed"


class MediaType(Enum):
    """Type of media being downloaded."""

    TRACK = "track"
    ALBUM = "album"
    PLAYLIST = "playlist"
    ARTIST = "artist"


class JobProgress(msgspec.Struct, frozen=True):
    """Progress statistics for a download job.

    Attributes:
        completed: Number of successfully completed tracks.
        failed: Number of failed tracks.
        skipped: Number of skipped tracks.
        total: Total number of tracks in the job.
    """

    completed: int
    failed: int
    skipped: int
    total: int

    @property
    def finished(self) -> int:
        """Total number of finished tracks (completed + failed + skipped)."""
        return self.completed + self.failed + self.skipped

    @property
    def progress(self) -> float:
        """Progress ratio (0.0 to 1.0)."""
        if self.total == 0:
            return 0.0
        return self.finished / self.total

    @property
    def is_finished(self) -> bool:
        """Whether all tracks have finished."""
        return self.finished >= self.total and self.total > 0


class DownloadJob(msgspec.Struct, kw_only=True):
    """Represents an original download request.

    A job groups all tracks from a single URL/request together,
    allowing progress tracking and completion detection at the
    album/playlist/artist level.

    Attributes:
        job_id: Unique identifier for this job.
        original_url: The original URL that initiated this download.
        media_type: Type of media (track, album, playlist, artist).
        media_id: The media identifier from the service.
        module_name: Name of the module handling this download.
        name: Display name (album name, playlist name, etc.).
        artist: Artist name for display.
        download_path: Base path for downloaded files.
        track_ids: List of track IDs belonging to this job.
        track_infos: Dictionary mapping track IDs to their TrackInfo metadata.
        completed_tracks: Set of successfully completed track IDs.
        failed_tracks: Set of failed track IDs.
        skipped_tracks: Set of skipped track IDs.
        status: Current job status.
        created_at: Unix timestamp when job was created.
        cover_url: Cover image URL for the job.
    """

    job_id: str
    original_url: str
    media_type: MediaType
    media_id: str
    module_name: str
    name: str = ""
    artist: str = ""
    download_path: str = ""
    track_ids: list[str] = msgspec.field(default_factory=list)
    track_infos: dict[str, TrackInfo] = msgspec.field(default_factory=dict)
    completed_tracks: set[str] = msgspec.field(default_factory=set)
    failed_tracks: set[str] = msgspec.field(default_factory=set)
    skipped_tracks: set[str] = msgspec.field(default_factory=set)
    status: JobStatus = JobStatus.PENDING
    created_at: float = 0.0
    cover_url: str = ""

    @property
    def has_successful_downloads(self) -> bool:
        """Whether any tracks were successfully downloaded (not skipped)."""
        return len(self.completed_tracks) > 0

    @property
    def total_tracks(self) -> int:
        """Total number of tracks in this job."""
        return len(self.track_ids)

    @property
    def finished_tracks(self) -> int:
        """Number of tracks that have finished (success, failed, or skipped)."""
        return (
            len(self.completed_tracks)
            + len(self.failed_tracks)
            + len(self.skipped_tracks)
        )

    @property
    def is_finished(self) -> bool:
        """Whether all tracks in this job have finished."""
        return self.finished_tracks >= self.total_tracks and self.total_tracks > 0

    @property
    def progress(self) -> float:
        """Job progress as a ratio (0.0 to 1.0)."""
        if self.total_tracks == 0:
            return 0.0
        return self.finished_tracks / self.total_tracks


class TrackTask(msgspec.Struct):
    """A single track download task.

    Attributes:
        track_id: The track identifier.
        job_id: The job this track belongs to.
        module_name: The module to use for downloading.
        module: The loaded module instance.
        download_path: Path to save the track.
        track_index: Track number in album/playlist.
        total_tracks: Total tracks in album/playlist.
        main_artist: Main artist name for filtering.
        track_data: Pre-fetched track data from album/playlist/artist.
        account_index: Account index used for this task.
    """

    track_id: str
    job_id: str
    module_name: str
    module: ModuleBase
    download_path: str = ""
    track_index: int = 0
    total_tracks: int = 0
    main_artist: str = ""
    track_data: dict[str, Any] | None = None
    account_index: int = 0


# Type alias for job completion callback
JobCompletionCallback = Callable[[DownloadJob], Coroutine[Any, Any, None]]


class DownloadQueue:
    """Global download queue with job-based organization.

    This queue organizes downloads by job (original URL/request) while
    executing track downloads concurrently. Progress is reported through
    the unified progress system in utils.progress.
    """

    def __init__(
        self,
        max_concurrent: int,
        quality_tier: QualityEnum,
        codec_options: CodecOptions,
        on_job_complete: JobCompletionCallback | None = None,
    ) -> None:
        """Initializes the download queue.

        Args:
            max_concurrent: Maximum concurrent downloads.
            quality_tier: Quality tier for downloads.
            codec_options: Codec options for downloads.
            on_job_complete: Optional callback when a job completes.
        """
        self.semaphore = anyio.Semaphore(max_concurrent)
        self._quality_tier = quality_tier
        self._codec_options = codec_options
        self._on_job_complete = on_job_complete

        # Job management
        self._jobs: dict[str, DownloadJob] = {}
        self._track_tasks: dict[str, TrackTask] = {}
        self._job_lock = anyio.Lock()

    def _generate_job_id(self, original_url: str) -> str:
        """Generates a unique job ID from the original URL.

        Args:
            original_url: The original download URL.

        Returns:
            A unique job identifier.
        """
        # Use UUID4 for guaranteed uniqueness
        return str(uuid.uuid4())

    async def create_job(
        self,
        original_url: str,
        media_type: MediaType,
        media_id: str,
        module_name: str,
        name: str = "",
        artist: str = "",
        download_path: str = "",
        cover_url: str = "",
    ) -> str:
        """Creates a new download job.

        Args:
            original_url: The original URL that initiated this download.
            media_type: Type of media (track, album, playlist, artist).
            media_id: The media identifier from the service.
            module_name: Name of the module handling this download.
            name: Display name (album name, playlist name, etc.).
            artist: Artist name for display.
            download_path: Base path for downloaded files.
            cover_url: Cover image URL.

        Returns:
            The generated job ID.
        """
        job_id = self._generate_job_id(original_url)
        job = DownloadJob(
            job_id=job_id,
            original_url=original_url,
            media_type=media_type,
            media_id=media_id,
            module_name=module_name,
            name=name,
            artist=artist,
            download_path=download_path,
            cover_url=cover_url,
            created_at=time.time(),
        )
        async with self._job_lock:
            self._jobs[job_id] = job
        logger.debug("Created job %s for %s", job_id, original_url)
        return job_id

    async def add_track(self, job_id: str, task: TrackTask) -> None:
        """Adds a track task to a job.

        Args:
            job_id: The job ID to add the track to.
            task: The track task to add.

        Raises:
            KeyError: If the job ID doesn't exist.
        """
        async with self._job_lock:
            if job_id not in self._jobs:
                raise KeyError(f"Job {job_id} not found")

            job = self._jobs[job_id]
            job.track_ids.append(task.track_id)
            self._track_tasks[task.track_id] = task
            # Capture job name for use outside the lock
            job_name = job.name

        # Create progress task for UI (use job name for album/playlist)
        # This is done outside the lock to avoid holding lock during async call
        await create_task(
            task_id=task.track_id,
            service=task.module_name,
            album=job_name,
            artist=task.main_artist,
        )

    def get_job(self, job_id: str) -> DownloadJob | None:
        """Gets a job by ID.

        Args:
            job_id: The job ID.

        Returns:
            The job or None if not found.
        """
        return self._jobs.get(job_id)

    def get_track_task(self, track_id: str) -> TrackTask | None:
        """Gets a track task by ID.

        Args:
            track_id: The track ID.

        Returns:
            The track task or None if not found.
        """
        return self._track_tasks.get(track_id)

    def get_all_jobs(self) -> list[DownloadJob]:
        """Gets all jobs in the queue.

        Returns:
            List of all jobs.
        """
        return list(self._jobs.values())

    def get_all_track_tasks(self) -> list[TrackTask]:
        """Gets all track tasks in the queue.

        Returns:
            List of all track tasks.
        """
        return list(self._track_tasks.values())

    @property
    def job_count(self) -> int:
        """Returns number of jobs in the queue."""
        return len(self._jobs)

    @property
    def track_count(self) -> int:
        """Returns number of track tasks in the queue."""
        return len(self._track_tasks)

    async def mark_track_complete(
        self,
        track_id: str,
        status: ProgressStatus = ProgressStatus.COMPLETED,
    ) -> None:
        """Marks a track as complete and updates job status.

        Args:
            track_id: The track identifier.
            status: The completion status (COMPLETED, FAILED, or SKIPPED).
        """
        task = self._track_tasks.get(track_id)
        if not task:
            logger.warning("Track %s not found in queue", track_id)
            return

        job = self._jobs.get(task.job_id)
        if not job:
            logger.warning("Job %s not found for track %s", task.job_id, track_id)
            return

        async with self._job_lock:
            # Update job tracking sets
            if status == ProgressStatus.COMPLETED:
                job.completed_tracks.add(track_id)
            elif status == ProgressStatus.FAILED:
                job.failed_tracks.add(track_id)
            elif status == ProgressStatus.SKIPPED:
                job.skipped_tracks.add(track_id)

            # Check if job is finished
            if job.is_finished:
                if job.failed_tracks:
                    job.status = JobStatus.PARTIAL
                else:
                    job.status = JobStatus.COMPLETED

                logger.info(
                    "Job %s finished: %d completed, %d failed, %d skipped",
                    job.job_id,
                    len(job.completed_tracks),
                    len(job.failed_tracks),
                    len(job.skipped_tracks),
                )

                if self._on_job_complete:
                    await self._on_job_complete(job)

    async def update_progress(
        self,
        track_id: str,
        status: ProgressStatus | None = None,
        name: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        file_size: int | None = None,
        downloaded_size: int | None = None,
    ) -> None:
        """Updates progress for a track.

        Args:
            track_id: The track identifier.
            status: New status.
            name: Track name.
            artist: Artist name.
            album: Album name.
            progress: Download progress (0.0 to 1.0).
            message: Status message.
            file_size: Total file size in bytes.
            downloaded_size: Downloaded size in bytes.
        """
        current: int | None = None
        total: int | None = None

        if file_size is not None:
            total = file_size
        if downloaded_size is not None:
            current = downloaded_size
        elif progress is not None and file_size:
            current = int(progress * file_size)

        await update(
            task_id=track_id,
            status=status,
            name=name,
            artist=artist,
            album=album,
            current=current,
            total=total,
            message=message,
        )

        # Update job status to downloading if first track starts
        async with self._job_lock:
            task = self._track_tasks.get(track_id)
            if task and status == ProgressStatus.DOWNLOADING:
                job = self._jobs.get(task.job_id)
                if job and job.status == JobStatus.PENDING:
                    job.status = JobStatus.DOWNLOADING

    def get_job_progress(self, job_id: str) -> JobProgress:
        """Gets progress for a job.

        Args:
            job_id: The job ID.

        Returns:
            JobProgress with completed, failed, skipped, and total counts.
        """
        job = self._jobs.get(job_id)
        if not job:
            return JobProgress(completed=0, failed=0, skipped=0, total=0)
        return JobProgress(
            completed=len(job.completed_tracks),
            failed=len(job.failed_tracks),
            skipped=len(job.skipped_tracks),
            total=job.total_tracks,
        )

    def get_results(self) -> tuple[list[str], list[tuple[str, str]]]:
        """Returns download results for all tracks.

        Returns:
            Tuple of (completed track IDs, failed track IDs with errors).
        """
        completed: list[str] = []
        failed: list[tuple[str, str]] = []

        for job in self._jobs.values():
            completed.extend(job.completed_tracks)
            for track_id in job.failed_tracks:
                failed.append((track_id, "Download failed"))

        return completed, failed

    async def clear(self) -> None:
        """Clears all jobs and tasks from the queue."""
        async with self._job_lock:
            self._jobs.clear()
            self._track_tasks.clear()

    async def remove_job(self, job_id: str) -> bool:
        """Removes a job and its tracks from the queue.

        Args:
            job_id: The job ID to remove.

        Returns:
            True if the job was removed, False if not found.
        """
        async with self._job_lock:
            job = self._jobs.pop(job_id, None)
            if not job:
                return False

            for track_id in job.track_ids:
                self._track_tasks.pop(track_id, None)

            return True
