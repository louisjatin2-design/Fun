@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst install.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m supcombot run %*
pause
