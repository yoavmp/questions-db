@echo off
echo Starting Hebrew Exam System Backend...
echo.

cd backend

echo Creating virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt

echo Creating database directory...
if not exist "src\database" mkdir src\database

echo Starting backend server...
echo Backend will be available at: http://localhost:5000
echo.
python run.py

pause

