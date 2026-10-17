"""WP31R Part B: the backend-startup pricing-cache warm-up.

Every test is offline. The suite-wide ``_wp18_no_network`` autouse fixture
(conftest.py) traps any real socket connection as a defensive backstop; this
module additionally monkeypatches ``exam_generator.pricing_refresh.fetch_pricing_markdown``
directly wherever a (fake) refresh needs to happen, so no test ever reaches
the real pricing-document host or a provider. ``OPENAI_API_KEY`` is never
read by this code path (it never builds a provider) -- proven explicitly
below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exam_generator import pricing_refresh as pr
from exam_generator.live_cost import load_price_snapshot

from src.startup_pricing import refresh_pricing_at_startup, should_refresh_at_this_process

_GENERATOR_ROOT = Path(__file__).resolve().parents[2] / "exam_generator"
BUNDLED = _GENERATOR_ROOT / "config" / "pricing.yaml"
LLM_CONFIG = _GENERATOR_ROOT / "config" / "llm.yaml"
SELECTED_MODEL = load_price_snapshot(BUNDLED).model  # gpt-5.6-terra, kept symbolic


def _utc(*, days_ago: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


# --------------------------------------------------------------------------- #
# fresh cache: zero network calls
# --------------------------------------------------------------------------- #
def test_fresh_cache_makes_zero_network_calls(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"
    pr.seed_cache_from_bundled(cache_path, BUNDLED, now=_utc())

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("fetch_pricing_markdown called despite a fresh cache")

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _boom)

    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert "fresh cache" in line
    assert "warning" not in line
    assert SELECTED_MODEL in line


# --------------------------------------------------------------------------- #
# stale/absent cache: the injected fake downloader is called exactly once,
# and a valid cache is written
# --------------------------------------------------------------------------- #
def test_stale_cache_refreshes_exactly_once_and_writes_a_valid_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"
    pr.seed_cache_from_bundled(cache_path, BUNDLED, now=_utc(days_ago=10))  # > 7-day TTL

    calls = {"n": 0}

    def _fake_fetch(url=pr.DEFAULT_DOC_URL, **kw):
        calls["n"] += 1
        return pr_test_fixture_markdown()

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _fake_fetch)
    now = _utc()
    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=now,
    )
    assert calls["n"] == 1
    assert "refreshed" in line
    assert "warning" not in line
    on_disk = load_price_snapshot(cache_path)
    assert on_disk.model == SELECTED_MODEL


def test_absent_cache_refreshes_exactly_once(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"  # never written
    calls = {"n": 0}

    def _fake_fetch(url=pr.DEFAULT_DOC_URL, **kw):
        calls["n"] += 1
        return pr_test_fixture_markdown()

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _fake_fetch)
    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert calls["n"] == 1
    assert "refreshed" in line
    assert cache_path.is_file()


# --------------------------------------------------------------------------- #
# debug-reloader / concurrent initialization: never a duplicate refresh
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "debug,run_main,expected",
    [
        (True, None, False),       # reloader monitor pass: about to respawn -- skip
        (True, "true", True),      # respawned worker: WERKZEUG_RUN_MAIN set -- run
        (False, None, True),       # no reloader ever used -- run
        (False, "true", True),     # defensive: still run
    ],
)
def test_should_refresh_at_this_process_skips_only_the_reloader_monitor_pass(debug, run_main, expected):
    environ = {} if run_main is None else {"WERKZEUG_RUN_MAIN": run_main}
    assert should_refresh_at_this_process(debug=debug, environ=environ) is expected


def test_second_call_after_a_successful_refresh_is_a_zero_network_cache_hit(tmp_path, monkeypatch):
    """Simulates the debug reloader's monitor pass (first call, real fetch)
    immediately followed by the respawned worker pass (second call) -- the
    second call must never fetch again."""
    cache_path = tmp_path / "cache.yaml"  # absent -- "monitor pass" starts stale
    calls = {"n": 0}

    def _fake_fetch(url=pr.DEFAULT_DOC_URL, **kw):
        calls["n"] += 1
        return pr_test_fixture_markdown()

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _fake_fetch)
    now = _utc()

    first = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=now,
    )
    second = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=now,
    )
    assert calls["n"] == 1  # the second (worker) pass never re-fetched
    assert "refreshed" in first
    assert "fresh cache" in second


# --------------------------------------------------------------------------- #
# offline / timeout / malformed response: startup still proceeds, one warning
# --------------------------------------------------------------------------- #
def test_offline_refresh_failure_still_permits_startup_with_one_warning(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"
    pr.seed_cache_from_bundled(cache_path, BUNDLED, now=_utc(days_ago=10))

    def _offline(*a, **k):
        raise pr.PricingRefreshError("pricing document fetch failed: offline")

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _offline)
    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert "bundled fallback" in line
    assert line.count("warning:") == 1
    assert SELECTED_MODEL in line


def test_timeout_refresh_failure_still_permits_startup(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"
    pr.seed_cache_from_bundled(cache_path, BUNDLED, now=_utc(days_ago=10))
    monkeypatch.setattr(pr, "fetch_pricing_markdown", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out")))

    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert "bundled fallback" in line
    assert line.count("warning:") == 1


def test_malformed_response_with_no_prior_cache_falls_back_to_bundled(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"  # never written
    monkeypatch.setattr(pr, "fetch_pricing_markdown", lambda *a, **k: "garbage, no table")

    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert "bundled fallback" in line
    assert SELECTED_MODEL in line
    assert not cache_path.exists()  # never created from a failed refresh


# --------------------------------------------------------------------------- #
# missing selected-model pricing everywhere: never crashes, stays a
# readiness/LLM-operation blocker only
# --------------------------------------------------------------------------- #
def test_missing_selected_model_pricing_everywhere_does_not_crash_startup(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"  # never written

    def _fake_fetch(url=pr.DEFAULT_DOC_URL, **kw):
        return pr_test_fixture_markdown()

    monkeypatch.setattr(pr, "fetch_pricing_markdown", _fake_fetch)

    # llm.yaml selects SELECTED_MODEL, but this fixture document (and the
    # bundled snapshot it falls back to) never mentions a different,
    # deliberately-wrong "selected" model id -- simulate that mismatch by
    # asking for a config where the selected model id cannot be found
    # anywhere by monkeypatching the loaded config's model id instead of the
    # real llm.yaml (never edit the tracked config file).
    import exam_generator.llm_config as llm_config_mod

    real_load = llm_config_mod.load_llm_config

    def _mismatched_config(path):
        cfg = real_load(path)
        cfg.generation.model = "some-model-not-priced-anywhere"
        cfg.review.model = "some-model-not-priced-anywhere"
        return cfg

    monkeypatch.setattr(llm_config_mod, "load_llm_config", _mismatched_config)

    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    # never crashes (a string always comes back) and clearly flags the
    # blocker without crashing DB-only startup.
    assert isinstance(line, str) and line
    assert "not the selected model" in line or "some-model-not-priced-anywhere" in line


# --------------------------------------------------------------------------- #
# OPENAI_API_KEY is never read by this code path
# --------------------------------------------------------------------------- #
def test_startup_never_accesses_openai_api_key(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.yaml"
    pr.seed_cache_from_bundled(cache_path, BUNDLED, now=_utc())

    class _TrackingEnviron(dict):
        def __getitem__(self, key):
            if key == "OPENAI_API_KEY":
                raise AssertionError("OPENAI_API_KEY was read during startup pricing refresh")
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key == "OPENAI_API_KEY":
                raise AssertionError("OPENAI_API_KEY was read during startup pricing refresh")
            return super().get(key, default)

    import os as _os

    tracked = _TrackingEnviron(_os.environ)
    monkeypatch.setattr(_os, "environ", tracked)

    line = refresh_pricing_at_startup(
        llm_config_path=LLM_CONFIG, pricing_path=BUNDLED, cache_path=cache_path, now=_utc(),
    )
    assert "fresh cache" in line


def pr_test_fixture_markdown() -> str:
    return f"""# Pricing

### Standard pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| {SELECTED_MODEL} | $2.00 | $0.20 | $2.50 | $12.00 | $4.00 | $0.40 | $5.00 | $18.00 |
"""
