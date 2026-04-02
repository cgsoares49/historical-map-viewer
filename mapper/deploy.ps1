# deploy.ps1
# Rebuilds geodata from PAR/primaries, then commits and pushes all mapper changes.
# Run from any directory — it finds the repo root automatically.

$RepoRoot  = Split-Path $PSScriptRoot -Parent
$MapperDir = $PSScriptRoot

Set-Location $RepoRoot

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Mapper Deploy Script" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Rebuild geodata if primaries.txt or PAR files changed ─────────────
$rebuild = Read-Host "Rebuild geodata from PAR/primaries? (y/n)"
if ($rebuild -match '^[Yy]') {
    Write-Host ""
    Write-Host "Running build_geodata.py..." -ForegroundColor Yellow
    python "$MapperDir\build_geodata.py"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in build_geodata.py" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }

    Write-Host ""
    Write-Host "Running merge_geodata.py..." -ForegroundColor Yellow
    python "$MapperDir\merge_geodata.py"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in merge_geodata.py" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }

    Write-Host ""
    Write-Host "Running add_whe_refs.py..." -ForegroundColor Yellow
    python "$MapperDir\add_whe_refs.py"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in add_whe_refs.py" -ForegroundColor Red; Read-Host "Press Enter to exit"; exit 1 }

    Write-Host ""
    Write-Host "Geodata rebuild complete." -ForegroundColor Green
}

# ── Step 2: Show what changed ─────────────────────────────────────────────────
Write-Host ""
Write-Host "Changed files:" -ForegroundColor Yellow
git status --short

# ── Step 3: Commit message ────────────────────────────────────────────────────
Write-Host ""
$msg = Read-Host "Commit message (Enter for timestamp)"
if ([string]::IsNullOrWhiteSpace($msg)) {
    $msg = "Update mapper data and code — $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

# ── Step 4: Write app version into version.json ───────────────────────────────
$versionFile = "$MapperDir\version.json"
$versionObj  = Get-Content $versionFile -Raw | ConvertFrom-Json
$versionObj.app = Get-Date -Format 'yyyy-MM-dd'
$versionObj | ConvertTo-Json | Set-Content $versionFile
Write-Host "App version stamped: $($versionObj.app)" -ForegroundColor Cyan

# ── Step 5: Stage, commit, push ───────────────────────────────────────────────
Write-Host ""
Write-Host "Staging files..." -ForegroundColor Yellow
git add mapper/

Write-Host "Committing..." -ForegroundColor Yellow
git commit -m $msg

if ($LASTEXITCODE -ne 0) {
    Write-Host "Nothing to commit or commit failed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
git push

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Done! Beta site will update in ~1 minute." -ForegroundColor Green
Write-Host "  https://cgsoares49.github.io/historical-map-viewer/mapper/mapper.html" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close"
