# Startet Bot + Overlay. Optional: .\start.ps1 --map "Seton" --debug
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "Bitte zuerst .\install.bat ausfuehren."; exit 1 }
$extra = $args
& .\.venv\Scripts\python.exe -m supcombot run @extra
