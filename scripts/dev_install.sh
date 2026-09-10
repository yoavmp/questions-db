#!/usr/bin/env bash
# WP18 -- reproducible root-based install for the integrated backend.
#
# Installs, into a single virtualenv:
#   1. the outer backend dependencies      (backend/requirements.txt)
#   2. the pinned exam_generator package   (editable, from the submodule)
#   3. the generator's RUNTIME deps, pinned to its own constraints.txt
#
# Reported dependency conflicts (WP18 §1) -- NEITHER pin file is changed:
#
#   1. exam_generator/constraints.txt pins pytest==9.1.1;  backend/requirements.txt
#      pins pytest==7.4.2 (+ pytest-flask==1.2.0). Incompatible. The integrated
#      backend env keeps pytest 7.4.2; the generator package is installed with
#      --no-deps and only its runtime libs are constrained. The generator's own
#      suite runs under its own constraints in a separate env
#      (exam_generator/docs/DEPENDENCY_LOCK.md).
#
#   2. exam_generator/constraints.txt pins MarkupSafe==3.0.3 while
#      backend/requirements.txt pins MarkupSafe==2.1.3. We do NOT constrain
#      MarkupSafe here: Jinja2 (pulled by Flask 2.3.3, >=3.1.2, which is all the
#      generator needs) works with MarkupSafe 2.1.3, so the backend pin stands.
#
# Only pydantic / pymupdf / pyyaml / openai / typer are pinned to the generator's
# constraints -- these are its own runtime deps and are absent from the backend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
PY="${PYTHON:-python3}"

echo "== questions-db integrated backend install =="
echo "repo root : $ROOT"
echo "virtualenv: $VENV"

if [ ! -f "$ROOT/exam_generator/src/exam_generator/__init__.py" ]; then
  echo "!! exam_generator submodule not checked out."
  echo "   run: git submodule update --init --recursive"
  exit 1
fi

"$PY" -m venv "$VENV"
PIP="$VENV/bin/python -m pip"
$PIP install --upgrade pip >/dev/null

echo "-- 1/3 backend dependencies (backend/requirements.txt)"
$PIP install -r "$ROOT/backend/requirements.txt"

echo "-- 2/3 pinned generator package (editable, no deps)"
$PIP install -e "$ROOT/exam_generator" --no-deps

echo "-- 3/3 generator runtime deps, pinned to exam_generator/constraints.txt"
$PIP install -c "$ROOT/exam_generator/constraints.txt" \
  pydantic pymupdf pyyaml openai typer

echo "-- pip check"
$VENV/bin/python -m pip check || {
  echo "!! pip reported a conflict -- review before changing any pin"; exit 1;
}

echo "-- import smoke test"
"$VENV/bin/python" - <<'PYEOF'
import flask, flask_sqlalchemy, openpyxl            # backend
from exam_generator.production import generate_exam_question   # pinned generator
from importlib.metadata import version
print("OK: backend + exam_generator", version("exam-generator"), "importable")
PYEOF

cat <<EOF

Done. Activate with:  source "$VENV/bin/activate"

Run the backend:      cd backend && python run.py         # http://localhost:4567
Run backend tests:    cd backend && python -m pytest -q
LLM readiness:        GET /api/exam-jobs/readiness  (needs OPENAI_API_KEY set;
                      DB-only functions work without it)
EOF
