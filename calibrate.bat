@echo off
rem Kalibrierung - Beispiele:  .\calibrate.bat --faction uef   |   .\calibrate.bat --only colors.enemy
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst install.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m supcombot calibrate %*
pause
