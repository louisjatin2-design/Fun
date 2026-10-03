# SupComBot Installation (Windows). Am einfachsten: install.bat (Doppelklick oder .\install.bat).
# Direkt: powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== SupComBot Installation ==" -ForegroundColor Cyan

# 1. Python finden
$py = $null
foreach ($cand in @("py -3", "python", "python3")) {
    try {
        $v = & cmd /c "$cand --version 2>&1"
        if ($LASTEXITCODE -eq 0 -and $v -match "Python 3\.(\d+)") {
            if ([int]$Matches[1] -ge 10) { $py = $cand; break }
        }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.10+ nicht gefunden. Installieren von https://www.python.org/downloads/windows/ (Haken bei 'Add python.exe to PATH')." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# 2. Virtuelle Umgebung + Abhaengigkeiten
if (-not (Test-Path ".venv")) {
    & cmd /c "$py -m venv .venv"
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "Abhaengigkeiten installiert." -ForegroundColor Green

# 3. Spiel-Installation suchen
$found = & .\.venv\Scripts\python.exe -c "from supcombot.maps import steam_game_dir; d=steam_game_dir(); print(d if d else '')"
if ($found) {
    Write-Host "Forged Alliance gefunden: $found" -ForegroundColor Green
} else {
    Write-Host "Steam-Installation nicht automatisch gefunden. Trage 'game_dir' in %APPDATA%\SupComBot\settings.json ein." -ForegroundColor Yellow
}

# 4. Ollama pruefen
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
    $names = ($tags.models | ForEach-Object { $_.name }) -join ", "
    Write-Host "Ollama erreichbar. Modelle: $names" -ForegroundColor Green
} catch {
    Write-Host "Ollama nicht erreichbar (laeuft 'ollama serve'?). Der Bot funktioniert auch ohne, dann ohne KI-Anpassungen." -ForegroundColor Yellow
}

# 5. Settings-Datei anlegen
& .\.venv\Scripts\python.exe -c "from supcombot import config; s=config.load_settings(); config.save_settings(s); print('Einstellungen:', config.SETTINGS_FILE)"

Write-Host ""
Write-Host "Fertig. Naechste Schritte:" -ForegroundColor Cyan
Write-Host "  1. Spiel im Fenstermodus starten (Steam-Startoption: /windowed), Skirmish laden"
Write-Host "  2. .\calibrate.bat --faction uef   (einmalig pro Fraktion und Aufloesung)"
Write-Host "  3. .\start.bat                    (Bot + Overlay)"
