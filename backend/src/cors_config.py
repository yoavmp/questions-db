"""The app's single CORS policy (WP31 Part C).

Factored out of ``src/main.py`` so it is diagnosable and testable on its own,
without importing ``src.main`` (which runs database migrations against a
fixed path at import time -- see ``backend/tests/conftest.py``) and without
any route adding its own ad hoc CORS headers.

An explicit allowlist of the project's documented local-dev frontend origins
(README.md / SETUP.md: Vite on port 3000, both the ``localhost`` and
``127.0.0.1`` forms) -- never an unrestricted wildcard. ``ALLOWED_METHODS``
must list every HTTP method any route actually uses, PATCH included (the
question-edit route in ``src/routes/exam_jobs.py``): ``flask_cors`` only
emits ``Access-Control-Allow-Methods`` / ``-Headers`` on a preflight whose
``Access-Control-Request-Method`` is itself a member of this list (see
``flask_cors.core.get_cors_headers``) -- PATCH's prior absence here is
exactly why the browser's edit preflight came back without either header and
the browser never sent the real PATCH.
"""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

DEV_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
ALLOWED_HEADERS = ["Content-Type", "Authorization"]


def configure_cors(app: Flask) -> None:
    """Apply the app's one CORS policy. Call exactly once per app instance."""
    CORS(
        app,
        origins=DEV_FRONTEND_ORIGINS,
        methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
    )
