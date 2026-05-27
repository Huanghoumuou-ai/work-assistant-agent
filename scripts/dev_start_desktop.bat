@echo off
setlocal

cd /d "%~dp0.."

if not exist "node_modules" (
  echo [WorkMemory] Missing node_modules. Run: npm install
  exit /b 1
)

if not exist "apps\desktop\package.json" (
  echo [WorkMemory] Missing apps\desktop\package.json.
  exit /b 1
)

npm run dev -w apps/desktop
