"""In-process async job store for long investigations (docs/Production-Roadmap.md A1-prod).

`POST /api/investigate` submits work here and returns a job id immediately; the
client polls `GET /api/investigate/jobs/{id}`. The work runs as an asyncio task on
the same event loop — so the browser never holds a long connection and a trace can
*never* time out the request, even in POC.

Deliberately in-memory + single-process (no Redis/Dramatiq): matches the lean
deployment and today's "one analyst" workload. The API contract (submit → poll) is
the same one a real queue would expose, so swapping the executor to Dramatiq later
is a drop-in — see the A1-prod roadmap note. Jobs are ephemeral (lost on restart)
and capped to the most-recent N.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

_MAX_JOBS = 64  # keep only the most-recent jobs; oldest evicted (bounded memory)


class JobError(Exception):
    """Raise inside a job to fail it with a client-facing {code, message}."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class Job:
    id: str
    status: str = "pending"  # pending | running | done | error
    result: Any = None
    error: dict[str, str] | None = None
    created: float = field(default_factory=time.time)


class JobStore:
    def __init__(self, max_jobs: int = _MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()  # hold refs so tasks aren't GC'd
        self._max = max_jobs

    def submit(self, work: Callable[[], Awaitable[Any]]) -> str:
        """Queue `work` (an async thunk) and return its job id immediately."""
        job = Job(id=uuid.uuid4().hex)
        self._jobs[job.id] = job
        self._evict()
        task = asyncio.create_task(self._run(job, work))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job.id

    async def _run(self, job: Job, work: Callable[[], Awaitable[Any]]) -> None:
        job.status = "running"
        try:
            job.result = await work()
            job.status = "done"
        except JobError as exc:
            job.status = "error"
            job.error = {"code": exc.code, "message": exc.message}
        except Exception as exc:  # noqa: BLE001 — never let a job crash the loop silently
            job.status = "error"
            job.error = {"code": "job_failed", "message": str(exc)[:200]}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _evict(self) -> None:
        # dict preserves insertion order → the first key is the oldest job.
        while len(self._jobs) > self._max:
            del self._jobs[next(iter(self._jobs))]


_store = JobStore()


def get_job_store() -> JobStore:
    return _store
