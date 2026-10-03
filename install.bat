@echo off
rem SupComBot Installation - Doppelklick oder in cmd/PowerShell: .\install.bat
cd /d "%~dp0"
if not exist "install.ps1" (
  echo install.ps1 fehlt. Bist du auf dem Branch "main"?  Ausfuehren:  git checkout main
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
