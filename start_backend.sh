#!/bin/bash

echo "Starting Hebrew Exam System Backend..."
echo

cd backend

echo "Creating virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Creating database directory..."
mkdir -p src/database

echo "Starting backend server..."
echo "Backend will be available at: http://localhost:4567"
echo
python run.py

