# Setup Instructions - הוראות התקנה

## Prerequisites - דרישות מוקדמות

### Required Software - תוכנות נדרשות
1. **Python 3.11+** - Download from [python.org](https://python.org)
2. **Node.js 18+** - Download from [nodejs.org](https://nodejs.org)
3. **Git** (optional) - For version control

### Verify Installation - אימות התקנה
```bash
python --version    # Should show Python 3.11+
node --version      # Should show Node.js 18+
npm --version       # Should show npm version
```

## Step-by-Step Setup - הוראות התקנה שלב אחר שלב

### Step 1: Extract Files - חילוץ קבצים
1. Extract the zip file to your desired location
2. Open terminal/command prompt in the extracted folder

### Step 2: Backend Setup - הגדרת Backend

**Recommended (WP18): one root-based, reproducible install** that also wires in
the pinned `exam_generator` submodule used for LLM question generation:

```bash
# from the repository root (needs the submodule checked out:
#   git submodule update --init --recursive )
./scripts/dev_install.sh
source .venv/bin/activate

cd backend && python run.py         # http://localhost:4567
```

`scripts/dev_install.sh` installs `backend/requirements.txt`, then the pinned
generator package (editable, `--no-deps`), then the generator's **runtime**
libraries constrained to `exam_generator/constraints.txt`. It runs `pip check`
and an import smoke test.

> **Known dependency conflict (not auto-resolved):** the generator's
> `constraints.txt` pins `pytest==9.1.1` while the backend needs `pytest==7.4.2`
> + `pytest-flask==1.2.0`. Neither pin file is changed. The integrated backend
> env keeps pytest 7.4.2; the generator's own test suite runs under its own
> constraints in a separate env.

**LLM generation** additionally needs `OPENAI_API_KEY` exported in the backend's
environment (its *presence* is checked at `GET /api/exam-jobs/readiness`; the
value is never read or logged). Without it — or without the generator's local
`Data/` — the database-only features keep working; LLM job creation is refused
with a safe reason.

#### Local course data required for LLM generation

1. `git clone --recurse-submodules` (or `git submodule update --init --recursive`)
   fetches the pinned `exam_generator` code, but it does **not** download
   `exam_generator/Data/` — that course source data and its derived search index
   are not part of either Git repository.
2. To enable LLM generation, the owner must securely copy or rebuild that data at
   the exact paths the generator adapter expects:
   `exam_generator/Data/index/` (the pre-built search index directory) and
   `exam_generator/Data/Course_Material_Summary.pdf` (the source PDF).
3. This copied data must stay Git-ignored (already covered by
   `exam_generator/.gitignore`) and must never be committed or pushed to either
   repository.
4. To check availability without exposing course text or any secret, call
   `GET /api/exam-jobs/readiness` — its `local_data` check (and the `data`
   section of the response) reports only boolean presence of the index
   directory and the PDF, never their contents.
5. Missing local data disables LLM generation only (`ready_for_llm: false`,
   with a safe reason listed in `blocking_reasons`); it never blocks DB-only
   exam functionality (`db_only_available` is always `true`).

<details><summary>Manual / legacy setup (backend only, no generator)</summary>

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
mkdir -p src/database
python run.py
```
</details>

**Expected Output:**
```
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:4567
 * Running on http://[::1]:4567
```

### Step 3: Frontend Setup - הגדרת Frontend

Open a **new terminal window** and:

```bash
# Navigate to frontend directory
cd frontend

# Install Node.js dependencies
npm install

# Start the development server
npm run dev
```

**Expected Output:**
```
  Local:   http://localhost:3000/
  Network: http://192.168.x.x:3000/
```

### Step 4: Access the Application - גישה לאפליקציה

1. Open your web browser
2. Go to `http://localhost:3000`
3. You should see the Hebrew exam system interface

## Troubleshooting - פתרון בעיות

### Common Issues - בעיות נפוצות

#### Backend Issues:

**Error: "Python not found"**
- Install Python 3.11+ from python.org
- Make sure Python is added to PATH

**Error: "pip not found"**
- Reinstall Python with pip included
- Or install pip separately

**Error: "Module not found"**
- Make sure virtual environment is activated
- Run `pip install -r requirements.txt` again

**Error: "Port 4567 already in use"**
- Change port in `run.py`: `app.run(host='0.0.0.0', port=4568)`
- Update frontend API URL accordingly

#### Frontend Issues:

**Error: "Node not found"**
- Install Node.js 18+ from nodejs.org
- Restart terminal after installation

**Error: "npm not found"**
- Node.js installation should include npm
- Try reinstalling Node.js

**Error: "Port 3000 already in use"**
- Vite will automatically suggest another port
- Or specify port: `npm run dev -- --port 3001`

**Error: "Cannot connect to backend"**
- Make sure backend is running on port 4567
- Check API_BASE_URL in `src/App.jsx`

### Database Issues - בעיות בסיס נתונים

**Error: "Database locked"**
- Close all applications using the database
- Restart both backend and frontend

**Error: "No such table"**
- Delete `src/database/app.db` if it exists
- Restart backend to recreate tables

### Excel Upload Issues - בעיות העלאת Excel

**Error: "Invalid file format"**
- Make sure file is .xlsx or .xls format
- Check that all required columns exist
- Use the provided template

**Error: "Hebrew text not displaying"**
- Make sure Excel file is saved with UTF-8 encoding
- Check browser language settings

## Development Mode - מצב פיתוח

### Backend Development:
- Flask runs in debug mode by default
- Changes to Python files will auto-reload
- Database file: `backend/src/database/app.db`

### Frontend Development:
- Vite provides hot module replacement
- Changes to React files will auto-reload
- Build for production: `npm run build`

## File Structure - מבנה קבצים

```
hebrew-exam-system/
├── backend/                 # Flask backend
│   ├── src/
│   │   ├── database/       # SQLite database files
│   │   ├── models/         # Database models
│   │   ├── routes/         # API routes
│   │   └── main.py         # Flask app
│   ├── requirements.txt    # Python dependencies
│   └── run.py             # Entry point
├── frontend/               # React frontend
│   ├── src/
│   │   ├── components/    # UI components
│   │   ├── App.jsx        # Main component
│   │   └── App.css        # Styles
│   ├── package.json       # Node dependencies
│   └── index.html         # HTML template
├── README.md              # Main documentation
└── SETUP.md              # This file
```

## Named Exams, History, Branches, and Exclusions - שמות מבחנים, היסטוריה, גרסאות והחרגות

Since WP26, creating a new exam ("יצירת מבחן") asks for either a **structured
name** (קורס / שנה / סוג / מועד) or a **custom name**, and optionally accepts
an `.xlsx` file listing DB questions to exclude from selection (headers
`מזהה_שאלה`/`id`, `שאלה`/`question`, `נושא`/`קטגוריה`/`category`) — the file
itself is never stored, only the resolved question ids. Since WP26R, the
exclusion workbook accepts **at most 100 non-blank data rows** (the header
row doesn't count); a 101st non-blank row rejects the whole file with a clear
Hebrew message — no partial exclusion list is ever accepted.

Every created exam is saved to a history list (visible in the "יצירת מבחן"
tab) showing its name, date, status and short id, regardless of whether it
completed. Opening an older exam from that list is **read-only** — to keep
working from it without changing the original, use "יצירת גרסה חדשה" to
create an independent, editable branch that starts with the same questions
and no prior LLM cost. Every question/category/analytics field shown for a
saved exam (including a branch) is frozen at the moment it was selected — it
never changes even if the source question in the bank is later edited or
deleted.

## Two-Phase Exam Creation - יצירת מבחן בשני שלבים

Since WP27, creating an exam with both database and AI-generated questions
happens in two explicit steps instead of one automatic run:

1. **DB review (`ממתין לאישור שאלות המאגר`).** Submitting the "יצירת מבחן"
   form immediately selects and shows every requested database question —
   nothing is generated by AI yet, and no `OPENAI_API_KEY`/pricing check
   happens at this step. If the exam requested zero AI questions, it is
   already complete at this point (no further step exists). Otherwise the
   screen shows the planned number of new AI questions, the current
   cumulative AI cost (normally $0.00), and a prominent
   **"המשך ליצירת שאלות חדשות באמצעות בינה מלאכותית"** button.
2. **Continue.** Clicking that button is the one explicit, paid operation
   that starts generating the originally requested AI questions — readiness
   (API key, pricing, generator data) is checked at this point, immediately
   before the first call. Clicking it twice, refreshing mid-run, or
   restarting the backend never starts a second batch or re-generates an
   already-accepted question.

During DB review, both **"החלף בשאלה מהמאגר"** (swap in a different DB
question) and **"צור שאלה אחרת"** (generate one AI replacement immediately,
a paid call) remain available on every question — using either does not
change how many AI questions Continue will later generate, and does not end
DB review. A DB-review exam is saved and reopenable indefinitely, exactly
like any other exam in the history list; "יצירת גרסה חדשה" (branching) stays
disabled until the exam is fully complete.

**WP27R:** the Continue step's claim is now committed to disk *before* the
button's request even returns, so reopening or refreshing the page always
shows the true state — never a stale "waiting" screen for a batch that has
actually already started. If AI generation stops partway through (the
backend restarted, or the cost ceiling was reached before every planned
question was tried), the exam shows a distinct "יצירת השאלות בבינה מלאכותית
הופסקה" (AI question generation was paused) banner with its own **"המשך
ליצירת שאלות חדשות באמצעות בינה מלאכותית"** button — pressing it resumes
exactly the remaining planned questions; nothing already generated is ever
redone. A single failed/paused question can also be retried on its own from
the per-topic progress list, independently of resuming the whole batch.

## Warning Acceptance, Manual Editing, and Failed Replacement (WP28)

**Warning acceptance.** A generated question with exactly one weak-but-real
distractor (a real, source-grounded, category-appropriate term that is
definitely wrong for the question but only structurally/type-mismatched or
low-plausibility — e.g. offering a deep cerebellar nucleus as one of three
cortex *layers*) is now **accepted immediately**, not rejected/regenerated.
It shows a **"דורש בדיקה"** (requires review) badge, highlights the exact
affected answer, and explains the mismatch in Hebrew. It is never generated
again purely because of the warning, and the topic itself is never treated
as forbidden — two or more weak distractors, or any more serious defect,
still hard-rejects and regenerates as before.

**Hard-rejection memory.** When a candidate *is* hard-rejected, this exam job
now remembers a small, bounded record of the specific defect (never the
topic) per category, and a later same-category operation (a retry, or
"צור שאלה אחרת") is told not to repeat it. Nothing about this ever appears
in a public export — it only shapes what the generator tries next.

**Manual editing.** Every current AI-generated question now has an
**"ערוך שאלה"** button (database-origin questions never get one). It opens
an inline form for the stem, all four answers, and the correct-answer
selector; saving requires no `OPENAI_API_KEY` and makes no AI call — the
owner's edit is authoritative. Editing the exact answer a warning named
resolves that warning (shown as a quieter **"תוקן ידנית"** state); editing
anything else leaves an unrelated warning open. Every edit is kept in an
immutable history and survives reload/restart; DOCX and Excel exports always
use the current edited text, never the original AI draft.

**Export confirmation.** Exporting (DOCX or either Excel format) while any
question still shows an unresolved "דורש בדיקה" warning asks for one
explicit confirmation first, naming how many; cancelling downloads nothing,
confirming exports normally. A fully resolved/clean exam exports with no
extra prompt, same as before WP28.

**Failed replacement.** If "צור שאלה אחרת" exhausts its attempts without
producing an accepted question, the original question is kept exactly as it
was — the exam now says so explicitly
(**"לא נוצרה שאלה חלופית. השאלה המקורית נשמרה."**) with the attempt
count/cost when available, instead of leaving it ambiguous whether anything
changed.

## Question Categories - קטגוריות שאלות

A question's **full category list** (`categories`) is the only thing that
makes it eligible for a requested category when building an exam — the
single **primary category** (`category`, shown as the question's main topic)
is always just the first entry of that list and can never by itself make a
question eligible for a category it isn't otherwise tagged with. Every entry
in a question's category list must be one of the 20 canonical topics; an
Excel import row, manual edit, or category rename that would produce an
empty, unknown, or duplicate category list is rejected with a clear error
message rather than silently accepted.

## Next Steps - צעדים הבאים

1. **Upload Questions**: Use the Excel template to upload your questions
2. **Create Tests**: Generate tests using the test creation interface, optionally naming them and excluding specific DB questions
3. **Manage Performance**: Add performance data for questions used in exams
4. **Export Data**: Export questions and test results to Excel

## Support - תמיכה

If you encounter issues:
1. Check this troubleshooting guide
2. Verify all prerequisites are installed
3. Make sure both backend and frontend are running
4. Check browser console for error messages

---

**Good luck with your Hebrew exam system! בהצלחה עם מערכת השאלות בעברית!**

