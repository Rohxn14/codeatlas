"""Index jobs started from the web app: one background thread at a time.

Indexing a repository takes from a second to a few minutes, far longer than a page may
take to answer. So the page that starts an index gets a job id back at once, the work
runs on its own thread, and a progress page asks for the job's state every two seconds.

Jobs live in memory only. Stopping the server forgets them; an index that was running
is lost with it, and the database keeps whatever was already complete.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# The pipeline's steps in the order they run, with the words the progress page shows.
STEPS: tuple[tuple[str, str], ...] = (
    ("intake", "Fetch the repository"),
    ("discover", "List the files"),
    ("parse", "Read each file"),
    ("repo_layer", "Find packages, tests and change history"),
    ("write", "Store files and symbols"),
    ("resolve", "Connect calls and imports"),
    ("link", "Connect HTTP calls to routes"),
    ("save", "Store the connections"),
)
MAX_ACTIVE = 6  # one running and five waiting
MAX_KEPT = 30

# What a job runs: (source, force, progress) -> the index report as a dict.
Work = Callable[[str, bool, Callable[[str, str], None]], dict[str, Any]]


class TooManyJobs(Exception):
    """Enough jobs are waiting already; starting more would only queue work unseen."""


@dataclass(slots=True)
class Job:
    """One request to index a source, and where it has got to."""

    id: str
    source: str
    force: bool
    state: str = "waiting"  # waiting, running, done, failed
    step: str = ""
    detail: str = ""
    error: str = ""
    report: dict[str, Any] | None = None
    created: float = field(default_factory=time.monotonic)
    started: float | None = None
    finished: float | None = None

    @property
    def active(self) -> bool:
        return self.state in ("waiting", "running")

    @property
    def seconds(self) -> float:
        """How long the work has run, or ran; zero while it waits."""
        if self.started is None:
            return 0.0
        return (self.finished or time.monotonic()) - self.started

    def steps(self) -> list[dict[str, str]]:
        """Each pipeline step as done, now or next, for the progress page."""
        names = [name for name, _ in STEPS]
        at = names.index(self.step) if self.step in names else -1
        rows = []
        for i, (name, label) in enumerate(STEPS):
            if self.state == "done" or i < at:
                status = "done"
            elif i == at and self.state == "running":
                status = "now"
            elif i == at and self.state == "failed":
                status = "failed"
            else:
                status = "next"
            rows.append({"name": name, "label": label, "status": status,
                         "detail": self.detail if i == at else ""})
        return rows


class Jobs:
    """Starts jobs, runs them one after another, and remembers the recent ones."""

    def __init__(self, work: Work, on_done: Callable[[Job], None] | None = None) -> None:
        self._work = work
        self._on_done = on_done
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()  # guards the dictionary
        self._turn = threading.Lock()  # held by the one job that is indexing

    def start(self, source: str, force: bool = False) -> Job:
        """Queue an index of `source`, or return the job already working on it."""
        with self._lock:
            for job in self._jobs.values():
                if job.active and job.source == source:
                    return job
            if sum(1 for job in self._jobs.values() if job.active) >= MAX_ACTIVE:
                raise TooManyJobs(f"{MAX_ACTIVE} repositories are already being indexed")
            job = Job(uuid.uuid4().hex[:12], source, force)
            self._jobs[job.id] = job
            self._forget_old()
        threading.Thread(target=self._run, args=(job,), daemon=True, name="index").start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[Job]:
        """Newest first."""
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created, reverse=True)

    def busy(self) -> bool:
        with self._lock:
            return any(job.active for job in self._jobs.values())

    def wait(self, job_id: str, timeout: float = 60.0) -> Job:
        """Block until a job has finished. For tests; pages never wait."""
        end = time.monotonic() + timeout
        job = self.get(job_id)
        assert job is not None, job_id
        while job.active and time.monotonic() < end:
            time.sleep(0.02)
        return job

    def _run(self, job: Job) -> None:
        def progress(step: str, detail: str) -> None:
            job.step, job.detail = step, detail

        with self._turn:
            job.state, job.started = "running", time.monotonic()
            try:
                report = self._work(job.source, job.force, progress)
            except Exception as exc:  # a job must end as "failed", never vanish
                job.error = str(exc) or type(exc).__name__
                job.finished = time.monotonic()
                job.state = "failed"
                return
            job.report = report
            job.finished = time.monotonic()
            if self._on_done is not None:
                self._on_done(job)
            job.state = "done"

    def _forget_old(self) -> None:
        """Keep the newest finished jobs only, so a long-running server does not grow."""
        finished = sorted((job for job in self._jobs.values() if not job.active),
                          key=lambda job: job.created)
        for job in finished[: max(0, len(finished) - MAX_KEPT)]:
            del self._jobs[job.id]
