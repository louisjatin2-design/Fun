@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst install.ps1 ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m supcombot run %*
pause
