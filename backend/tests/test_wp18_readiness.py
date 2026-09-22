"""WP18 §1 -- non-network readiness: stale warns, missing key/data/pricing blocks."""

from __future__ import annotations

from src.integration import readiness as R
from src.jobs import service


def test_ready_when_key_present_and_everything_else_ok(llm_ready):
    rep = R.readiness_report()
    assert rep["ready_for_llm"] is True
    assert rep["db_only_available"] is True
    assert rep["blocking_reasons"] == []
    assert rep["generator"]["importable"] is True
    assert rep["models"]["generation"] and rep["models"]["review"]
    assert rep["category_mapping"]["ok"] is True
    assert rep["pricing"]["complete"] and rep["pricing"]["matches_models"]
    # never echoes the key value
    blob = str(rep)
    assert "sk-wp18" not in blob


def test_missing_key_blocks_llm_only_not_db(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rep = R.readiness_report()
    assert rep["ready_for_llm"] is False
    assert rep["db_only_available"] is True
    assert any("OPENAI_API_KEY" in r for r in rep["blocking_reasons"])
    assert rep["openai_api_key_present"] is False


def test_stale_pricing_warns_but_does_not_block(llm_ready):
    # the submodule snapshot is a few days old; a 0-day threshold makes it "stale"
    rep = R.readiness_report(pricing_stale_days=0)
    assert rep["ready_for_llm"] is True                 # stale never blocks
    assert rep["pricing"]["stale"] is True
    assert any("old" in w for w in rep["warnings"])
    assert any(c["name"] == "pricing_age" and c["level"] == "warning" for c in rep["checks"])


def test_missing_pricing_file_blocks(monkeypatch, llm_ready, tmp_path):
    paths = R.generator_paths()
    bad = dict(paths)
    bad["pricing"] = str(tmp_path / "nope.yaml")
    monkeypatch.setattr(R, "generator_paths", lambda: bad)
    rep = R.readiness_report()
    assert rep["ready_for_llm"] is False
    assert any("pricing" in r for r in rep["blocking_reasons"])


def test_create_job_never_checks_readiness_even_with_llm_requested(jobs_app, jobs_root, monkeypatch):
    """WP27 §2: initial DB selection must work with no OPENAI_API_KEY at all,
    even when LLM work is planned -- readiness is checked only later, at
    Continue / manual replace time, never at creation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 0, "llm": 1}}, "cost_ceiling_usd": "5.00"}
        )
    assert job.status == "queued"  # db_review: nothing has run
    assert service.workflow_phase(job) == "db_review"
    assert job.accumulated_cost_usd == "0"

    # a DB-only job (no LLM planned) is also accepted with the same missing
    # key, and is persisted completed immediately (WP27 §2 edge case)
    with jobs_app.app_context():
        job2 = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 1, "llm": 0}}, "cost_ceiling_usd": "5.00"}
        )
    assert job2.status == "completed"
    assert service.workflow_phase(job2) == "complete"


def test_submodule_pin_check_matches_recorded_pin(llm_ready):
    rep = R.readiness_report()
    pin = rep["submodule_pin"]
    if pin["checked"]:
        assert pin["matches"] is True
        assert pin["actual"] == pin["expected"]
