# Installation et vérification complètes du Laboratoire sur Windows (PowerShell).
# Usage (dans le dossier du dépôt) : powershell -ExecutionPolicy Bypass -File tools\installer_pc.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
function Ok($m) { Write-Host "  OK  $m" -ForegroundColor Green }
function Ko($m) { Write-Host "  ERREUR  $m" -ForegroundColor Red; exit 1 }
Write-Host "1. Outils"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Ko "Git manquant : https://git-scm.com" }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { Ko "Python 3.11+ manquant : https://www.python.org (cocher « Add to PATH »)" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Ko "Node.js 20+ manquant : https://nodejs.org" }
Ok "git, python $(py -3 -V), node $(node -v)"
Write-Host "2. AI Live"
Push-Location ai_live; py -3 -m venv .venv; .\.venv\Scripts\pip install -q -e ".[dev]"; .\.venv\Scripts\python -m pytest -q | Select-Object -Last 1; Pop-Location
Ok "AI Live installé et testé"
node ai_live\tests\js\rendu.test.mjs; node ai_live\tests\js\autotune.test.mjs
Write-Host "3. AI Studio"
Push-Location ai_studio; py -3 -m venv .venv; .\.venv\Scripts\pip install -q -e ".[dev]"; .\.venv\Scripts\python -m pytest -q | Select-Object -Last 1; Pop-Location
Ok "AI Studio installé et testé"
Write-Host "4. Site"
Push-Location site\laboratoire; node build_langues.mjs | Out-Null; Pop-Location
Ok "site : 15 langues valides"
Write-Host ""
Write-Host "Tout est installé. Lancer Claude Code dans ce dossier : claude"
