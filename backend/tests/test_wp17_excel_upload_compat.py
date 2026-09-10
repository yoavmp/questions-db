"""WP17 section 7 -- exported LLM questions stay compatible with /api/upload-excel.

An ``ExamQuestionDTO`` built from a generator seven-field question is written out
with the exact Hebrew headers the current upload route expects, then uploaded.
It must import cleanly and land in the DB with the right fields.
"""

from __future__ import annotations

import io

from openpyxl import Workbook

from src.integration.exam_question_dto import ExamQuestionDTO, GenerationMeta

# the header set /api/upload-excel maps (nושא/שאלה/תשובה.../תשובה_נכונה + optional)
UPLOAD_HEADERS = ["נושא", "שאלה", "תשובה1", "תשובה2", "תשובה3", "תשובה4", "תשובה_נכונה"]


def _generated_dto(number, category):
    seven = {
        "number": number,
        "question": f"שאלת LLM {number} על {category}",
        "answer1": "תשובה נכונה",
        "answer2": "מסיח 1",
        "answer3": "מסיח 2",
        "answer4": "מסיח 3",
        "correct_answer": 1,
    }
    return ExamQuestionDTO.from_generated(
        seven, number=number, category=category,
        generation_meta=GenerationMeta(attempts=1, cost_usd="0.03"),
    )


def _xlsx_from_dtos(dtos):
    wb = Workbook()
    ws = wb.active
    ws.append(UPLOAD_HEADERS)
    for dto in dtos:
        v = dto.docx_view()  # seven fields + category, NO generation_meta
        ws.append([
            v["category"], v["question"],
            v["answer1"], v["answer2"], v["answer3"], v["answer4"],
            v["correct_answer"],
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_exported_llm_questions_upload_cleanly(client, app):
    from src.models.user import db
    from src.models.question import Question

    dtos = [_generated_dto(1, "היסטולוגיה"), _generated_dto(2, "גרעיני הבסיס")]
    buf = _xlsx_from_dtos(dtos)

    resp = client.post(
        "/api/upload-excel",
        data={"file": (buf, "generated_questions.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["success"] is True

    with app.app_context():
        rows = Question.query.order_by(Question.id).all()
        assert len(rows) == 2
        assert rows[0].category == "היסטולוגיה"
        assert rows[0].correct_answer_id == 1
        assert rows[0].question.startswith("שאלת LLM 1")
        assert rows[1].category == "גרעיני הבסיס"
        # generated questions carry no performance history
        assert rows[0].accuracy_list == []
        assert rows[0].distinction_list == []


def test_docx_view_never_leaks_generation_meta_into_a_row():
    dto = _generated_dto(1, "מבוא")
    row_keys = set(dto.docx_view())
    assert "generation_meta" not in row_keys
    assert row_keys == {"number", "question", "answer1", "answer2", "answer3",
                        "answer4", "correct_answer", "category"}
