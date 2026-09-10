"""Non-network startup / readiness service for LLM exam generation (WP18 §1).

Every check here is offline: no socket is opened, no provider is constructed,
and the ``OPENAI_API_KEY`` is probed for *presence only* -- its value is never
read into a variable that is returned or logged.

A failure of any of {generator import, local Data, category mapping, complete
matching pricing, API key} disables **LLM generation only**. DB-only application
functions stay available (``db_only_available`` is always ``True``). Pricing that
is merely stale (older than the configured threshold, default 30 days) produces
a warning and does *not* disable generation.

The structured report is safe to hand to the future UI: it contains no
filesystem secret and no key value.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Optional

from src.integration.category_map import verify_against_generator_catalog
from src.integration.generator_adapter import GENERATOR_IMPORT_ERROR, generator_paths
from src.integration.generator_pin import EXPECTED_GENERATOR_PIN

__all__ = ["readiness_report", "DEFAULT_PRICING_STALE_DAYS"]

DEFAULT_PRICING_STALE_DAYS = 30

_PRICE_FIELDS = ("input", "cached_input", "cache_write", "output")


def _check(name: str, ok: bool, level: str, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "level": level, "detail": detail}


def _generator_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("exam-generator")
    except Exception:  # noqa: BLE001
        try:
            import exam_generator  # type: ignore

            return getattr(exam_generator, "__version__", None)
        except Exception:  # noqa: BLE001
            return None


def _submodule_pin(generator_root: Path) -> dict:
    """Compare the checked-out submodule HEAD to the pin this repo records.

    Only meaningful in a development git checkout; returns ``checked=False``
    otherwise (e.g. a packaged deployment).
    """
    git_dir = generator_root / ".git"
    if not git_dir.exists():
        return {"checked": False, "expected": EXPECTED_GENERATOR_PIN, "actual": None, "matches": None}
    try:
        actual = subprocess.run(
            ["git", "-C", str(generator_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return {
            "checked": False, "expected": EXPECTED_GENERATOR_PIN, "actual": None,
            "matches": None, "error": f"{type(exc).__name__}",
        }
    return {
        "checked": True,
        "expected": EXPECTED_GENERATOR_PIN,
        "actual": actual,
        "matches": actual == EXPECTED_GENERATOR_PIN,
    }


def _pricing_status(pricing_path: Path, gen_model: Optional[str], rev_model: Optional[str],
                    stale_days: int) -> dict:
    out: dict[str, Any] = {
        "complete": False, "matches_models": False, "model": None,
        "verified_at": None, "age_days": None, "stale": False, "error": None,
    }
    try:
        from exam_generator.live_cost import load_price_snapshot
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"cannot import price loader: {type(exc).__name__}"
        return out
    try:
        price = load_price_snapshot(pricing_path)
    except Exception as exc:  # noqa: BLE001 - LivePolicyError etc.
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    from decimal import Decimal

    complete = all(
        isinstance(getattr(price, f, None), Decimal) and getattr(price, f) > 0
        for f in _PRICE_FIELDS
    )
    out["complete"] = complete
    out["model"] = price.model
    out["verified_at"] = price.verified_at.isoformat()
    age = (date.today() - price.verified_at).days
    out["age_days"] = age
    out["stale"] = age > stale_days
    selected = {m for m in (gen_model, rev_model) if m}
    out["matches_models"] = bool(selected) and selected == {price.model}
    return out


def _selected_models(llm_config_path: Path) -> dict:
    try:
        from exam_generator.llm_config import load_llm_config

        cfg = load_llm_config(llm_config_path)
        return {"generation": cfg.generation.model, "review": cfg.review.model, "provider": cfg.provider}
    except Exception as exc:  # noqa: BLE001
        return {"generation": None, "review": None, "provider": None, "error": f"{type(exc).__name__}: {exc}"}


def readiness_report(*, pricing_stale_days: int = DEFAULT_PRICING_STALE_DAYS) -> dict:
    """Build the structured, secret-free readiness report."""
    paths = generator_paths()
    generator_root = Path(paths["generator_root"])
    checks: list[dict] = []
    warnings: list[str] = []
    blocking: list[str] = []

    # 1. generator import + version -----------------------------------------
    importable = GENERATOR_IMPORT_ERROR is None
    version = _generator_version() if importable else None
    checks.append(_check(
        "generator_import", importable, "blocking" if not importable else "ok",
        "pinned generator imported" if importable
        else f"cannot import exam_generator.production: {GENERATOR_IMPORT_ERROR}",
    ))
    if not importable:
        blocking.append("generator package is not importable")

    # 2. submodule pin (development only) ----------------------------------
    pin = _submodule_pin(generator_root)
    if pin["checked"]:
        checks.append(_check(
            "submodule_pin", bool(pin["matches"]),
            "ok" if pin["matches"] else "warning",
            "submodule HEAD matches the recorded pin" if pin["matches"]
            else f"submodule HEAD {pin['actual'][:12] if pin['actual'] else '?'} != recorded pin {EXPECTED_GENERATOR_PIN[:12]}",
        ))
        if not pin["matches"]:
            warnings.append("checked-out generator differs from the recorded pin; re-run git submodule update")
    else:
        checks.append(_check("submodule_pin", True, "ok", "not a development checkout; pin check skipped"))

    # 3. local Data readiness --------------------------------------------
    index_dir = Path(paths["index_dir"])
    pdf = Path(paths["pdf"])
    index_ok = index_dir.is_dir() and any(index_dir.iterdir())
    pdf_ok = pdf.is_file()
    data_ok = index_ok and pdf_ok
    checks.append(_check(
        "local_data", data_ok, "blocking" if not data_ok else "ok",
        "Data/index and course PDF present" if data_ok
        else f"missing generator runtime data (index_dir={index_ok}, pdf={pdf_ok})",
    ))
    if not data_ok:
        blocking.append("generator local Data (Data/index and/or course PDF) is missing")

    # 4. 20/20 exact category mapping -----------------------------------
    catalog = Path(paths["catalog"])
    mapping = {"ok": False, "count": 0}
    if catalog.is_file():
        try:
            rep = verify_against_generator_catalog(catalog)
            mapping = {
                "ok": rep["canonical_count"] == rep["generator_count"] == 20
                and rep["byte_exact_names"] and rep["unmapped"] == [] and rep["ambiguous"] == [],
                "count": rep["canonical_count"],
            }
        except AssertionError as exc:
            mapping = {"ok": False, "count": 0, "error": str(exc)}
    checks.append(_check(
        "category_mapping", mapping["ok"], "blocking" if not mapping["ok"] else "ok",
        "20/20 canonical categories map exactly to strict-ready contexts" if mapping["ok"]
        else f"category mapping incomplete: {mapping.get('error', 'catalog missing')}",
    ))
    if not mapping["ok"]:
        blocking.append("canonical <-> generator category mapping is not 20/20 exact")

    # 5. selected models --------------------------------------------------
    models = _selected_models(Path(paths["llm_config"]))
    checks.append(_check(
        "selected_models", bool(models.get("generation") and models.get("review")),
        "blocking" if not models.get("generation") else "ok",
        f"generation={models.get('generation')}, review={models.get('review')}"
        + (f" ({models['error']})" if models.get("error") else ""),
    ))
    if not models.get("generation"):
        blocking.append("cannot read the selected generation/review models")

    # 6/7. complete matching pricing + age --------------------------------
    pricing = _pricing_status(
        Path(paths["pricing"]), models.get("generation"), models.get("review"), pricing_stale_days
    )
    pricing_ok = pricing["complete"] and pricing["matches_models"]
    checks.append(_check(
        "pricing_complete_and_matching", pricing_ok,
        "blocking" if not pricing_ok else "ok",
        (f"pricing model {pricing['model']} matches selected models and is complete"
         if pricing_ok else
         f"pricing not usable (complete={pricing['complete']}, matches_models={pricing['matches_models']}"
         + (f", error={pricing['error']}" if pricing.get("error") else "") + ")"),
    ))
    if not pricing_ok:
        blocking.append("config/pricing.yaml is incomplete or does not match the selected models")
    if pricing_ok and pricing["stale"]:
        checks.append(_check(
            "pricing_age", False, "warning",
            f"pricing verified {pricing['age_days']} days ago (> {pricing_stale_days}); refresh advised, not blocking",
        ))
        warnings.append(
            f"pricing snapshot is {pricing['age_days']} days old (threshold {pricing_stale_days}); estimate still a safe bound"
        )
    elif pricing_ok:
        checks.append(_check("pricing_age", True, "ok", f"pricing verified {pricing['age_days']} days ago"))

    # 8. OPENAI_API_KEY presence (never the value) ----------------------
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    checks.append(_check(
        "openai_api_key_present", key_present, "blocking" if not key_present else "ok",
        "OPENAI_API_KEY is set" if key_present else "OPENAI_API_KEY is not set in the environment",
    ))
    if not key_present:
        blocking.append("OPENAI_API_KEY is not set (LLM generation only; DB-only functions unaffected)")

    ready_for_llm = not blocking
    return {
        "ready_for_llm": ready_for_llm,
        "db_only_available": True,
        "checks": checks,
        "warnings": warnings,
        "blocking_reasons": blocking,
        "generator": {"importable": importable, "version": version, "import_error": GENERATOR_IMPORT_ERROR},
        "models": {k: models.get(k) for k in ("generation", "review", "provider")},
        "pricing": pricing,
        "submodule_pin": pin,
        "data": {"index_dir": index_ok, "pdf": pdf_ok},
        "category_mapping": mapping,
        "openai_api_key_present": key_present,
        "pricing_stale_days": pricing_stale_days,
    }
