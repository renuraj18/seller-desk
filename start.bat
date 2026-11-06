@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Setting up Seller Desk for the first time...
  python -m venv .venv || (echo Python not found. Install Python 3.11+ from python.org and tick "Add Python to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r backend\requirements.txt || (pause & exit /b 1)
)
echo Seller Desk is running at http://localhost:8000  (close this window to stop)
start "" http://localhost:8000
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
