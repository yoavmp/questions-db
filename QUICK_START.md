# Quick Start Guide - מדריך התחלה מהירה

## 🚀 Get Started in 3 Steps

### Step 1: Start Backend (Terminal 1)

**Windows:**
```bash
# Double-click start_backend.bat
# OR run in Command Prompt:
start_backend.bat
```

**macOS/Linux:**
```bash
# In terminal:
./start_backend.sh
```

**Manual (All platforms):**
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Step 2: Start Frontend (Terminal 2)

**Windows:**
```bash
# Double-click start_frontend.bat
# OR run in Command Prompt:
start_frontend.bat
```

**macOS/Linux:**
```bash
# In new terminal:
./start_frontend.sh
```

**Manual (All platforms):**
```bash
cd frontend
npm install
npm run dev
```

### Step 3: Open Browser

Go to: `http://localhost:3000`

## ✅ What You Should See

1. **Backend Terminal**: "Running on http://127.0.0.1:4567"
2. **Frontend Terminal**: "Local: http://localhost:3000/"
3. **Browser**: Hebrew exam system interface

## 📊 Upload Sample Questions

1. Click "העלאת שאלות" (Upload Questions)
2. Use the included `sample_questions_template.xlsx`
3. Click "העלה קובץ" (Upload File)

## 🎯 Create Your First Test

1. Click "יצירת מבחן" (Create Test)
2. Select questions per category
3. Click "צור מבחן" (Create Test)

## ❗ Troubleshooting

**Backend not starting?**
- Install Python 3.11+
- Check if port 4567 is free

**Frontend not starting?**
- Install Node.js 18+
- Check if port 3000 is free

**Can't connect?**
- Make sure both servers are running
- Check firewall settings

---

**Need help? Check SETUP.md for detailed instructions.**

