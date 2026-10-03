# Kalibrierungs-Assistent. Optional: .\calibrate.ps1 --faction cybran   |   --only ui.build.mex   |   --map-rect   |   --template victory
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) { Write-Host "Bitte zuerst .\install.ps1 ausfuehren."; exit 1 }
$extra = $args
& .\.venv\Scripts\python.exe -m supcombot calibrate @extra
