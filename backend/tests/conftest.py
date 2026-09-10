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
