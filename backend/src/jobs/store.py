"""Atomic on-disk persistence for exam-generation jobs (WP18 §2).

Layout (all git-ignored)::

    artifacts/exam_jobs/
      <job_id>/
        job.json            # the whole Job, atomically replaced on every change
        job.lock            # best-effort cross-process run lock
        slots/<slot_id>/    # per-slot generator audit dir

* ``job_id`` / ``slot_id`` are UUIDs; every path is validated to stay inside the
  jobs root (no traversal).
* Writes go to a temp file in the same directory and are ``os.replace``d over
  the target, so a reader never sees a half-written file.
* On backend start, a job left ``running`` becomes ``interrupted`` and its
  running slots become ``interrupted`` (retryable). Billable calls are never
  auto-resumed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Optional

from src.jobs.model import Job

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

# process-wide guard around job.json writes (atomic replace still protects
# cross-process, this just avoids interleaved temp files in one process)
_IO_LOCK = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def jobs_root(*, create: bool = False) -> Path:
    """``<repo>/artifacts/exam_jobs`` unless overridden by ``EXAM_JOBS_ROOT``
    (tests point this at a tmp dir). Only created on demand (a write), so merely
    importing the backend never leaves an empty ``artifacts/`` behind."""
    override = os.environ.get("EXAM_JOBS_ROOT")
    root = Path(override) if override else _repo_root() / "artifacts" / "exam_jobs"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_job_id(job_id: str) -> str:
    if not _UUID_RE.match(job_id or ""):
        raise ValueError(f"invalid job id {job_id!r}")
    return job_id


def job_dir(job_id: str) -> Path:
    root = jobs_root(create=True).resolve()
    d = (root / _validate_job_id(job_id)).resolve()
    if root not in d.parents and d != root:
        raise ValueError("job path escapes the jobs root")
    return d


def slot_audit_dir(job_id: str, slot_id: str) -> Path:
    if not _UUID_RE.match(slot_id or ""):
        raise ValueError(f"invalid slot id {slot_id!r}")
    d = job_dir(job_id) / "slots" / slot_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_file(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def save(job: Job) -> None:
    """Atomically (re)write ``job.json``."""
    job.touch()
    d = job_dir(job.job_id)
    d.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(job.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    with _IO_LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".job.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, str(_job_file(job.job_id)))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def load(job_id: str) -> Optional[Job]:
    f = _job_file(job_id)
    if not f.is_file():
        return None
    return Job.from_dict(json.loads(f.read_text(encoding="utf-8")))


def exists(job_id: str) -> bool:
    return _job_file(job_id).is_file()


def list_job_ids() -> list[str]:
    root = jobs_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and _UUID_RE.match(p.name) and (p / "job.json").is_file()
    )


# --------------------------------------------------------------------------- #
# best-effort cross-process run lock
# --------------------------------------------------------------------------- #
def try_acquire_lock(job_id: str) -> bool:
    lock = job_dir(job_id) / "job.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock(job_id: str) -> None:
    lock = job_dir(job_id) / "job.lock"
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- #
# crash recovery
# --------------------------------------------------------------------------- #
def recover_on_start() -> list[str]:
    """Mark every ``running`` job (and its running slots) ``interrupted``.

    Returns the ids that were changed. Never resumes a billable call.
    """
    changed: list[str] = []
    for job_id in list_job_ids():
        job = load(job_id)
        if job is None:
            continue
        if job.status == "running":
            job.status = "interrupted"
            job.safe_error = "backend restarted while this job was running; unfinished slots are retryable"
            for s in job.slots:
                if s.status == "running":
                    s.status = "interrupted"
            save(job)
            release_lock(job_id)
            changed.append(job_id)
    return changed
