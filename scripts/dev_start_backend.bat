@echo off
setlocal

cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo [WorkMemory] Missing .venv. Run: python -m venv .venv
  exit /b 1
)

if not exist "backend\requirements.txt" (
  echo [WorkMemory] Missing backend\requirements.txt.
  exit /b 1
)

".venv\Scripts\python.exe" -c "import uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [WorkMemory] Backend dependencies are not installed.
  echo [WorkMemory] Run: .venv\Scripts\python -m pip install -r backend\requirements.txt
  exit /b 1
)

".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
