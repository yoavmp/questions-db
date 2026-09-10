"""WP17 section 6 -- backend exam-question DTO."""

from __future__ import annotations

import pytest

from src.integration.exam_question_dto import (
    SEVEN_PUBLIC_FIELDS,
    ExamQuestionDTO,
    GenerationMeta,
)


def _seven(number=1):
    return {
        "number": number,
        "question": "שאלה",
        "answer1": "א",
        "answer2": "ב",
        "answer3": "ג",
        "answer4": "ד",
        "correct_answer": 1,
    }


def test_llm_question_defaults_and_meta():
    dto = ExamQuestionDTO.from_generated(_seven(), number=7, category="היסטולוגיה")
    assert dto.origin == "llm"
    assert dto.id is None
    assert dto.category == dto.primary_category == "היסטולוגיה"
    assert dto.categories == ["היסטולוגיה"]
    assert dto.accuracy is None and dto.distinction is None
    assert dto.accuracy_list == [] and dto.distinction_list == []
    assert isinstance(dto.generation_meta, GenerationMeta)
    assert dto.instance_id  # unique per position


def test_two_llm_dtos_have_distinct_instance_ids():
    a = ExamQuestionDTO.from_generated(_seven(), number=1, category="מבוא")
    b = ExamQuestionDTO.from_generated(_seven(), number=2, category="מבוא")
    assert a.instance_id != b.instance_id


def test_generation_meta_excluded_from_docx_view():
    dto = ExamQuestionDTO.from_generated(
        _seven(), number=1, category="מבוא",
        generation_meta=GenerationMeta(attempts=2, retries_by_slot=1, cost_usd="0.12"),
    )
    docx = dto.docx_view()
    assert set(docx) == set(SEVEN_PUBLIC_FIELDS) | {"category"}
    assert "generation_meta" not in docx
    # but it IS in the full serialisation
    assert dto.to_dict()["generation_meta"]["attempts"] == 2


def test_db_question_dto_from_row():
    class FakeRow:
        id = 42
        question = "שאלת מאגר"
        answer1, answer2, answer3, answer4 = "א", "ב", "ג", "ד"
        correct_answer_id = 3
        category = "גזע המוח"
        categories = ["גזע המוח", "מבוא"]
        accuracy = 88.0
        distinction = 0.4
        accuracy_list = [90.0, 86.0]
        distinction_list = [0.4]

    dto = ExamQuestionDTO.from_db_question(FakeRow(), number=5, category="מבוא")
    assert dto.origin == "database"
    assert dto.id == 42
    assert dto.number == 5
    assert dto.category == "מבוא"           # quota this position fills
    assert dto.primary_category == "גזע המוח"  # DB primary
    assert dto.correct_answer == 3
    assert dto.accuracy == 88.0


def test_public_seven_is_exactly_seven():
    dto = ExamQuestionDTO.from_generated(_seven(), number=1, category="מבוא")
    assert tuple(dto.public_seven()) == SEVEN_PUBLIC_FIELDS


def test_llm_question_rejects_non_null_db_id():
    with pytest.raises(ValueError):
        ExamQuestionDTO(
            **_seven(), origin="llm", id=5, category="מבוא",
        )
