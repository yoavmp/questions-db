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

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Create database directory
mkdir -p src/database

# Start the backend server
python run.py
```

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

## Next Steps - צעדים הבאים

1. **Upload Questions**: Use the Excel template to upload your questions
2. **Create Tests**: Generate tests using the test creation interface
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

