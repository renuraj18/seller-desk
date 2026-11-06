@echo off
title Seller Desk
cd /d "%~dp0"

rem ---- find Python (py launcher first, then python on PATH)
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found.
  echo Install Python 3.11 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" on the first screen of the installer.
  echo.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (
  echo Seller Desk needs Python 3.10 or newer. Please install the latest Python from python.org.
  pause
  exit /b 1
)

rem ---- first run: create a private Python environment and install packages
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Seller Desk for the first time. This takes a few minutes...
  %PY% -m venv .venv || (echo Could not create the Python environment. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt || (echo Package install failed. Check your internet connection and run start.bat again. & pause & exit /b 1)
)

echo.
echo  Seller Desk is running at http://localhost:8000
echo  Keep this window open while you work. Close it to stop Seller Desk.
echo.
start "" http://localhost:8000
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo.
echo Seller Desk stopped. If you saw "address already in use", Seller Desk is already open in another window.
pause
