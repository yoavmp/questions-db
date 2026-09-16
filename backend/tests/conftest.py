"""Shared fixtures for WP17 backend contract/category/DTO/adapter tests.

Every test here runs against a TEMPORARY sqlite database created under pytest's
``tmp_path``. ``backend/src/database/app.db`` is never opened or mutated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Belt-and-braces: make sure nothing under test can pick the real DB via the
# TESTING env branch in src/main.py.
os.environ.pop("TESTING", None)


@pytest.fixture()
def app(tmp_path):
    """A minimal Flask app: the test-generation blueprint + a temp-file DB.

    We deliberately do NOT import ``src.main`` (it runs migrations against a
    fixed database path at import time).
    """
    from flask import Flask

    from src.models.user import db
    from src.routes.test_generation import test_gen_bp
    from src.routes.upload import upload_bp

    application = Flask(__name__)
    db_path = tmp_path / "wp17_contract_test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    application.config["TESTING"] = True
    application.register_blueprint(test_gen_bp, url_prefix="/api")
    application.register_blueprint(upload_bp, url_prefix="/api")

    db.init_app(application)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# WP18: exam-generation job fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def jobs_root(tmp_path, monkeypatch):
    """Point job persistence at a throwaway dir (never <repo>/artifacts)."""
    root = tmp_path / "exam_jobs"
    monkeypatch.setenv("EXAM_JOBS_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def _wp18_no_network(request, monkeypatch):
    """Block real sockets for every WP18 test; the fakes never need one."""
    if "wp18" not in request.node.nodeid:
        return
    import socket

    def _no_connect(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP18 test")

    monkeypatch.setattr(socket.socket, "connect", _no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_connect)


@pytest.fixture()
def llm_ready(monkeypatch):
    """Make readiness pass: an in-process sentinel key (never a real one). The
    generator data / pricing / category map are already present in the checked
    out submodule, so readiness_report() then returns ready_for_llm=True."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-wp18-in-process-sentinel-not-a-real-key")
    yield


@pytest.fixture()
def jobs_app(tmp_path, jobs_root):
    """Flask app with the exam-jobs blueprint + a temp DB seeded across
    categories. ``src.main`` is deliberately not imported."""
    from flask import Flask

    from src.models.user import db
    from src.models.question import Question
    from src.routes.exam_jobs import exam_jobs_bp
    from src.routes.exclusion_upload import exclusion_bp
    from src.routes.test_generation import test_gen_bp
    from src.routes.upload import upload_bp

    application = Flask(__name__)
    db_path = tmp_path / "wp18_jobs_test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    application.config["TESTING"] = True
    application.register_blueprint(exam_jobs_bp, url_prefix="/api")
    application.register_blueprint(exclusion_bp, url_prefix="/api")
    application.register_blueprint(test_gen_bp, url_prefix="/api")
    application.register_blueprint(upload_bp, url_prefix="/api")

    db.init_app(application)
    with application.app_context():
        db.create_all()

        def _add(category, n, start=0):
            for i in range(start, start + n):
                q = Question(
                    category=category, question=f"{category} DB q{i}",
                    answer1="א", answer2="ב", answer3="ג", answer4="ד",
                    correct_answer_id=1,
                )
                q.categories = [category]
                db.session.add(q)

        _add("היסטולוגיה", 6)
        _add("גרעיני הבסיס", 6)
        _add("מבוא", 6)
        db.session.commit()

        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def jobs_client(jobs_app):
    return jobs_app.test_client()


@pytest.fixture()
def seed_questions(app):
    """Insert a handful of questions across a few canonical categories."""
    from src.models.user import db
    from src.models.question import Question, Category

    def _add(category, n, secondary=None):
        for i in range(n):
            q = Question(
                category=category,
                question=f"{category} question {i}",
                answer1="a", answer2="b", answer3="c", answer4="d",
                correct_answer_id=1,
            )
            cats = [category] + ([secondary] if secondary else [])
            q.categories = cats
            db.session.add(q)

    with app.app_context():
        _add("מבוא", 3)
        _add("היסטולוגיה", 2, secondary="מבוא")   # also counts toward מבוא
        _add("גזע המוח", 1)
        db.session.add(Category(name="מבוא", question_count=999))  # stale on purpose
        db.session.commit()
    return True
