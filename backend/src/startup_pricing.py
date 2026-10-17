"""WP31R Part B: warm the generator's WP31 pricing-refresh cache once at
backend startup, so the first real generation request after startup is
normally a cache hit instead of paying the refresh latency itself.

Factored out of ``src/main.py`` exactly like ``src/cors_config.py`` (WP31
Part C) -- diagnosable and callable on its own, without importing
``src.main`` (which runs database migrations against a fixed path at import
time -- see ``backend/tests/conftest.py``).

This module adds **no** new downloader, parser, or cache format: it is a
thin caller of ``exam_generator.pricing_refresh.load_price_snapshot_cached``,
the exact function ``backend/src/integration/generator_adapter.py`` already
opts every real generation call into. Startup warms the very same
Git-ignored cache file (same ``EXAM_GENERATOR_PRICING_CACHE_PATH`` env var
and default path) that a later generation request reads, so a successful
startup refresh turns that request into a cache hit -- it never replaces
that per-call safety net.

Best effort, non-fatal: every failure mode -- the generator package not
importable, an unreadable/invalid ``llm.yaml``, offline/timeout, a malformed
pricing document, the selected model missing from every trusted source, an
unwritable cache -- is caught here and turned into one concise line; this
module never raises, so it can never block backend startup as long as the
bundled generator snapshot is loadable. It never reads or forwards
``OPENAI_API_KEY`` -- ``exam_generator.pricing_refresh`` never touches that
variable, and nothing here does either. A pricing snapshot still missing for
a selected model after this (bundled fallback included) remains exactly the
pre-existing ``exam_generator.production._verify_pricing`` LLM-operation-time
blocker -- ordinary DB-only application use is never affected by this
module.

Duplicate-prevention under Flask's debug reloader: :func:`should_refresh_at_this_process`
is the small, independently testable decision ``src/main.py`` calls to skip
the reloader's pre-respawn "monitor" pass (which never serves a request) so
the refresh attempt and its terminal line happen at most once per
``python run.py`` invocation. This is the standard Werkzeug
``WERKZEUG_RUN_MAIN`` reloader-guard idiom, not a second locking mechanism --
genuine cross-process fetch/write safety during real concurrent
initialization still comes entirely from
``exam_generator.pricing_refresh``'s own in-process lock plus its
best-effort cross-process ``flock``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

__all__ = [
    "refresh_pricing_at_startup",
    "should_refresh_at_this_process",
    "DEFAULT_LLM_CONFIG_PATH",
    "DEFAULT_PRICING_PATH",
    "DEFAULT_PRICING_CACHE_PATH",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATOR_ROOT = _REPO_ROOT / "exam_generator"

DEFAULT_LLM_CONFIG_PATH = _GENERATOR_ROOT / "config" / "llm.yaml"
DEFAULT_PRICING_PATH = _GENERATOR_ROOT / "config" / "pricing.yaml"
#: Same default the per-generation-call adapter uses (generator_adapter.py).
DEFAULT_PRICING_CACHE_PATH = (
    _GENERATOR_ROOT / "artifacts" / "pricing_cache" / "openai_pricing_cache.yaml"
)


def should_refresh_at_this_process(*, debug: bool, environ: Mapping[str, str] | None = None) -> bool:
    """``False`` only for the Werkzeug debug reloader's pre-respawn "monitor"
    pass: ``debug`` is True (a reloader will be used) and ``WERKZEUG_RUN_MAIN``
    is not yet set (this process is about to respawn a child that sets it).
    ``True`` for that respawned child (``WERKZEUG_RUN_MAIN == "true"``) and
    for any run that never uses the reloader at all (``debug`` is False --
    e.g. a production WSGI import), so the refresh still always happens
    exactly once per real serving process.
    """
    environ = environ if environ is not None else os.environ
    if not debug:
        return True
    return environ.get("WERKZEUG_RUN_MAIN") == "true"


def _resolve_pricing_cache_path() -> Path:
    return Path(
        os.environ.get("EXAM_GENERATOR_PRICING_CACHE_PATH", str(DEFAULT_PRICING_CACHE_PATH))
    )


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def refresh_pricing_at_startup(
    *,
    llm_config_path: Path | str = DEFAULT_LLM_CONFIG_PATH,
    pricing_path: Path | str = DEFAULT_PRICING_PATH,
    cache_path: Path | str | None = None,
    now: datetime | None = None,
) -> str:
    """Best-effort startup pricing warm-up. Returns one concise summary
    line describing the outcome; never raises.
    """
    resolved_cache_path = Path(cache_path) if cache_path is not None else _resolve_pricing_cache_path()

    try:
        from exam_generator.llm_config import load_llm_config
    except Exception as exc:  # noqa: BLE001 - import failure must never block startup
        return f"pricing startup: generator package unavailable, skipped ({type(exc).__name__}: {exc})"

    try:
        config = load_llm_config(llm_config_path)
    except Exception as exc:  # noqa: BLE001 - a bad/missing llm.yaml is best-effort too
        return f"pricing startup: llm config unreadable, skipped ({type(exc).__name__}: {exc})"

    generation_model = config.generation.model
    review_model = config.review.model

    try:
        from exam_generator.pricing_refresh import load_price_snapshot_cached
    except Exception as exc:  # noqa: BLE001
        return f"pricing startup: pricing_refresh unavailable, skipped ({type(exc).__name__}: {exc})"

    before_mtime = _mtime(resolved_cache_path)
    try:
        kwargs = {} if now is None else {"now": now}
        snapshot, warnings = load_price_snapshot_cached(
            pricing_path, model=generation_model, cache_path=resolved_cache_path, **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 - WP31R Part B: any refresh failure
        # not already caught/wrapped inside load_price_snapshot_cached itself
        # must still never block startup.
        return (
            f"pricing startup: refresh failed unexpectedly for "
            f"generation={generation_model!r} review={review_model!r} "
            f"({type(exc).__name__}: {exc}); backend starting with no pricing guarantee"
        )
    after_mtime = _mtime(resolved_cache_path)

    if warnings:
        basis = "bundled fallback"
    elif before_mtime is not None and after_mtime == before_mtime:
        basis = "fresh cache"
    else:
        basis = "refreshed"

    models_str = (
        f"model={generation_model!r}"
        if generation_model == review_model
        else f"generation={generation_model!r} review={review_model!r}"
    )

    today = (now or datetime.now(timezone.utc)).date()
    age_days = (today - snapshot.verified_at).days
    age_str = f"verified_at={snapshot.verified_at.isoformat()} ({age_days}d old)"

    notes: list[str] = [w["detail"] for w in warnings]
    if snapshot.model not in {generation_model, review_model}:
        notes.append(
            f"pricing snapshot covers {snapshot.model!r}, not the selected "
            f"model(s); later LLM generation requests will be blocked until "
            f"a trusted source prices the selected model (DB-only use is unaffected)"
        )

    warn_str = f"; warning: {'; '.join(notes)}" if notes else ""
    return f"pricing startup: {basis} ({models_str}, {age_str}){warn_str}"
