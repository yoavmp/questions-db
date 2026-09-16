"""WP26 §1/§5/§8 -- structured/custom exam identity: validation, the exact
example display name/slug, legacy fallback labels. Pure, no app/DB needed."""

from __future__ import annotations

import pytest

from src.jobs.naming import IdentityError, fallback_label, resolve_identity, safe_slug


def test_no_identity_is_a_legal_request_shape():
    assert resolve_identity(None) is None


def test_structured_example_display_name_and_slug():
    identity = resolve_identity({
        "mode": "structured", "course": "מבנה המוח", "year": "2026",
        "exam_type": "מבחן מסכם", "sitting": "א",
    })
    assert identity["display_name"] == "מבנה המוח 2026 מבחן מסכם מועד א"
    assert identity["slug"] == "מבנה_המוח_2026_מבחן_מסכם_מועד_א"
    assert identity["mode"] == "structured"


def test_structured_sitting_defaults_when_omitted():
    identity = resolve_identity({
        "mode": "structured", "course": "נוירואנטומיה", "year": "2025",
        "exam_type": "מבחן אמצע",
    })
    assert identity["sitting"] == "א"
    assert "מועד א" in identity["display_name"]


@pytest.mark.parametrize("bad_course", ["פיזיולוגיה", "", "  ", None, 5])
def test_course_is_a_closed_enum(bad_course):
    with pytest.raises(IdentityError):
        resolve_identity({
            "mode": "structured", "course": bad_course, "year": "2026",
            "exam_type": "מבחן מסכם", "sitting": "א",
        })


@pytest.mark.parametrize("bad_type", ["מבחן ביניים", "", None])
def test_exam_type_is_a_closed_enum(bad_type):
    with pytest.raises(IdentityError):
        resolve_identity({
            "mode": "structured", "course": "מבנה המוח", "year": "2026",
            "exam_type": bad_type, "sitting": "א",
        })


@pytest.mark.parametrize("bad_year", ["26", "20266", "abcd", "", "  ", None])
def test_year_must_be_four_digits(bad_year):
    with pytest.raises(IdentityError):
        resolve_identity({
            "mode": "structured", "course": "מבנה המוח", "year": bad_year,
            "exam_type": "מבחן מסכם", "sitting": "א",
        })


def test_custom_name_trimmed_exactly_for_display():
    identity = resolve_identity({"mode": "custom", "custom_name": "  מבחן תרגול  "})
    assert identity["display_name"] == "מבחן תרגול"
    assert identity["mode"] == "custom"


@pytest.mark.parametrize("bad_name", ["", "   ", None, "a" * 200])
def test_custom_name_must_be_nonempty_and_bounded(bad_name):
    with pytest.raises(IdentityError):
        resolve_identity({"mode": "custom", "custom_name": bad_name})


@pytest.mark.parametrize("unsafe_name", ["../etc/passwd", "a/b", "a\\b", "..", "a\x00b"])
def test_custom_name_rejects_path_traversal_and_control_chars(unsafe_name):
    with pytest.raises(IdentityError):
        resolve_identity({"mode": "custom", "custom_name": unsafe_name})


def test_control_characters_rejected_in_structured_fields():
    with pytest.raises(IdentityError):
        resolve_identity({
            "mode": "structured", "course": "מבנה המוח", "year": "2026",
            "exam_type": "מבחן מסכם", "sitting": "א\x01",
        })


def test_unknown_mode_rejected():
    with pytest.raises(IdentityError):
        resolve_identity({"mode": "weird"})
    with pytest.raises(IdentityError):
        resolve_identity("not-a-dict")


def test_safe_slug_never_empty_and_strips_unsafe_filename_chars():
    assert safe_slug("") == "exam"
    assert safe_slug("a/b\\c:d*e?f\"g<h>i|j") == "abcdefghij"
    assert safe_slug("  a   b  ") == "a_b"


def test_fallback_label_format():
    label = fallback_label("14f2a1ea-0000-0000-0000-000000000000", "2026-09-16T14:00:00Z")
    assert label == "מבחן ללא שם – 16.09.2026 – 14f2a1ea"
