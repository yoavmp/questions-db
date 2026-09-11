"""Atomic on-disk persistence for exam-generation jobs (WP18 §2).

Layout (all git-ignored)::

    artifacts/exam_jobs/
      <job_id>/
        job.json            # the whole Job, atomically replaced on every change
        job.lock            # best-effort cross-process run lock
        slots/<slot_id>/    # per-slot generator audit dir
          <operation>_<seq>_<uuid>/          # one invocation, never reused (WP21R §3)
            invocation_manifest.json           # safe identifiers only, written pre-call
            attempt_01/ ...                     # the generator's own per-attempt evidence

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
import uuid as _uuid
from pathlib import Path
from typing import Optional

from src.jobs.model import Job, now_iso

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
#: one top-level invocation's audit-directory name: "<operation>_<4-digit
#: seq>_<uuid4>", e.g. "initial_0001_3fa85f64-5717-4562-b3fc-2c963f66afa6" --
#: see ``invocation_audit_dir`` (WP21R §3). The trailing UUID is the
#: authoritative, collision-proof identity; "<operation>_<seq>" is
#: human-readable context only and MAY repeat across invocations (e.g. after
#: a crash recomputes the same sequence number) without causing a collision.
_INVOCATION_RE = re.compile(
    r"^(initial|retry|replace_llm)_[0-9]{4}_"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

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


def new_invocation_uuid() -> str:
    """A fresh, securely-random UUID identifying one top-level LLM invocation
    (WP21R §3). This is the sole authoritative collision-proof identity for
    an invocation directory -- ``uuid.uuid4()`` draws from the OS CSPRNG."""
    return str(_uuid.uuid4())


def invocation_dir_name(operation: str, sequence: int, invocation_uuid: str) -> str:
    """Build ``"<operation>_<4-digit sequence>_<uuid>"`` -- the human-readable
    ``operation``/``sequence`` prefix is context only; ``invocation_uuid`` is
    what actually guarantees this name is never reused (WP21R §3)."""
    if operation not in ("initial", "retry", "replace_llm"):
        raise ValueError(f"invalid operation {operation!r}")
    return f"{operation}_{int(sequence):04d}_{invocation_uuid}"


def invocation_audit_dir(job_id: str, slot_id: str, invocation_id: str) -> Path:
    """A fresh, never-reused audit directory for ONE top-level LLM invocation
    (initial run / retry / replace_llm) on one slot (WP21 §7, hardened WP21R
    §3).

    Earlier code passed the same ``slot_audit_dir`` to every invocation on a
    slot; the generator's own internal ``attempt_01``/``attempt_02`` counter
    then restarted at 1 each time, so a later invocation silently overwrote an
    earlier one's evidence. WP21 gave every invocation its own subdirectory
    named ``<kind>_<seq>`` -- but ``seq`` was ``len(cost_ledger) + 1``,
    computed *before* the (possibly crashing) provider call and only made
    durable *after* it returns (``_record_cost`` appends to the ledger). A
    crash in between left ``cost_ledger`` unchanged, so the next invocation
    recomputed the *same* ``seq`` and, with the old ``exist_ok=True``,
    silently reused (and could overwrite evidence inside) the crashed
    invocation's directory.

    ``invocation_id`` is now ``<operation>_<seq>_<uuid>`` (see
    ``invocation_dir_name``): the UUID is generated fresh for every call and
    never recomputed from mutable state, so two invocations can never collide
    even if a crash makes them share the same ``operation``/``seq`` prefix.
    ``exist_ok=False`` turns any such collision (which should be
    cryptographically impossible) into a loud error instead of silent
    directory reuse -- this function must never delete or step around an
    existing path to manufacture a free one. ``invocation_id`` must match
    ``_INVOCATION_RE`` -- it is also the relative audit reference stored on
    the matching ledger entry and slot, safe to surface in the UI (no
    absolute path, no prompt/response content).
    """
    if not _INVOCATION_RE.match(invocation_id or ""):
        raise ValueError(f"invalid invocation id {invocation_id!r}")
    d = slot_audit_dir(job_id, slot_id) / invocation_id
    d.mkdir(parents=True, exist_ok=False)
    return d


#: safe field names for ``write_invocation_manifest`` (WP21R §3) -- job/slot
#: identifiers, operation metadata and timestamps only; deliberately excludes
#: anything that could carry a question, prompt, response, source content or
#: credential (name or value), and never an absolute filesystem path.
_MANIFEST_FIELDS = frozenset({"job_id", "slot_id", "operation", "sequence", "invocation_uuid", "created_at"})


def write_invocation_manifest(audit_dir: Path, manifest: dict) -> None:
    """Atomically write ``invocation_manifest.json`` into ``audit_dir`` (WP21R
    §3), *before* the provider boundary, so a crash mid-call still leaves
    behind enough to diagnose the orphaned directory without prompts,
    responses or credentials.

    ``manifest`` must contain only keys from ``_MANIFEST_FIELDS``. The write
    is temp-file-then-``os.replace`` (like ``save``), so a reader never sees
    a half-written manifest, and a crash before the ``os.replace`` simply
    leaves no manifest at all rather than a corrupt one.
    """
    extra = set(manifest) - _MANIFEST_FIELDS
    if extra:
        raise ValueError(f"manifest has unsafe field(s): {sorted(extra)}")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=str(audit_dir), prefix=".invocation_manifest.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(audit_dir / "invocation_manifest.json"))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
