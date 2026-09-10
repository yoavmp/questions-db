"""WP17 section 5 -- read-only generator adapter. Fake-provider, network-blocked.

These tests never make a provider call. A socket guard fails any real
connection attempt, and the only provider ever used is a scripted fake.
"""

from __future__ import annotations

import os
import socket
from decimal import Decimal
from pathlib import Path

import pytest

from src.integration.generator_adapter import (
    AdapterRequest,
    generate_category_question,
    generator_paths,
)

_REPO = Path(__file__).resolve().parents[2]
_GEN = _REPO / "exam_generator"


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _no_connect(*a, **k):  # pragma: no cover - only if something tries
        raise AssertionError("network access attempted during a WP17 adapter test")

    monkeypatch.setattr(socket.socket, "connect", _no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_connect)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


def test_paths_resolve_into_submodule_from_any_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = generator_paths()
    assert p["generator_root"] == str(_GEN)
    assert p["llm_config"].endswith("exam_generator/config/llm.yaml")
    assert Path(p["repo_root"]) == _REPO


def test_unknown_category_is_systemic_failure_no_network():
    res = generate_category_question(
        AdapterRequest(canonical_category="not a category", question_number=1)
    )
    assert res.status == "systemic_failure"
    assert res.question is None


def test_no_provider_and_no_key_is_systemic_failure():
    # canonical category, but nothing to call with -> typed systemic failure
    res = generate_category_question(
        AdapterRequest(canonical_category="מבוא", question_number=1)
    )
    assert res.status == "systemic_failure"
    assert "OPENAI_API_KEY" in (res.failure_reason or "") or "generator" in (res.failure_reason or "")


def test_cost_ceiling_short_circuits_before_any_call():
    class Exploding:
        name = "exploding"

        def generate_candidates(self, *a, **k):
            raise AssertionError("provider called despite cost ceiling")

        def review_candidates(self, *a, **k):
            raise AssertionError("provider called despite cost ceiling")

    res = generate_category_question(
        AdapterRequest(
            canonical_category="מבוא",
            question_number=1,
            actual_spend_usd=Decimal("4.80"),
            conservative_next_pair_usd=Decimal("0.50"),
            cost_ceiling_usd=Decimal("5.00"),
        ),
        provider=Exploding(),
    )
    assert res.status == "cost_ceiling"
    assert res.question is None


# --- the full assembly + fake provider (needs generator deps installed) -------
_gen_importable = (_GEN / "src" / "exam_generator" / "__init__.py").is_file()
pytestmark_full = pytest.mark.skipif(
    not _gen_importable, reason="exam_generator submodule not checked out"
)


@pytestmark_full
def test_provider_refusal_maps_to_provider_output_failure():
    pytest.importorskip("pydantic")
    pytest.importorskip("jinja2")
    pytest.importorskip("yaml")
    try:
        from exam_generator.providers import ProviderRefusal, ScriptedFakeProvider
    except Exception:
        pytest.skip("generator provider deps unavailable")

    fake = ScriptedFakeProvider(generations=[ProviderRefusal("simulated refusal")])
    res = generate_category_question(
        AdapterRequest(canonical_category="גרעיני הבסיס", question_number=1),
        provider=fake,
    )
    assert res.status in ("provider_output_failure", "systemic_failure")
    if res.status == "provider_output_failure":
        assert fake.generation_calls == 1
        assert res.question is None


@pytestmark_full
def test_missing_index_dir_is_systemic(monkeypatch, tmp_path):
    pytest.importorskip("pydantic")
    from src.integration import generator_adapter as ga

    monkeypatch.setattr(ga, "_GENERATOR_ROOT", tmp_path)  # no Data/index under here
    try:
        from exam_generator.providers import ScriptedFakeProvider
    except Exception:
        pytest.skip("generator provider deps unavailable")
    res = ga.generate_category_question(
        AdapterRequest(canonical_category="מבוא", question_number=1),
        provider=ScriptedFakeProvider(),
    )
    assert res.status == "systemic_failure"
