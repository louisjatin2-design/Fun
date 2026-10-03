@echo off
rem Holt die neueste Version von GitHub (Branch main) und aktualisiert die Abhaengigkeiten.
cd /d "%~dp0"
git fetch origin
git checkout main
git pull origin main
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
