# push-creator.ps1
# Syncs mapper/ code to the local creator repo clone and pushes to GitHub.
# Much faster than git subtree — no commit replay needed.
# Run from any directory.

$SourceDir   = $PSScriptRoot          # C:\my stuff\ClaudeTest\mapper
$CreatorRepo = "C:\my stuff\creator-repo"

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Creator Push" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Step 0: Stamp CREATOR's own app version date (independent of MAPPER's
#            version.json, which only deploy.ps1 touches) ────────────────────
$creatorVersionFile = Join-Path $SourceDir "creator-version.json"
$creatorVersion      = Get-Content $creatorVersionFile -Raw | ConvertFrom-Json
$creatorVersion.app  = Get-Date -Format 'yyyy-MM-dd'
$creatorVersion | ConvertTo-Json | Set-Content $creatorVersionFile
Write-Host "CREATOR app version stamped: $($creatorVersion.app)" -ForegroundColor Cyan

# ── Step 1: Robocopy mapper/ → creator repo (exclude .git and local-only files)
Write-Host "Syncing files to creator repo..." -ForegroundColor Yellow
robocopy $SourceDir $CreatorRepo /E /XO /XD ".git" "Work Area" "terrain" /XF "*.bmp" "*.vbp" "NVALUES.DAT" "offsets.txt" | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "ERROR: robocopy failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }
Write-Host "Sync complete." -ForegroundColor Green

# ── Step 2: Commit and push ───────────────────────────────────────────────────
$msg = "Update CREATOR code - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

Write-Host ""
Write-Host "Staging..." -ForegroundColor Yellow
git -C $CreatorRepo add -A

Write-Host "Committing..." -ForegroundColor Yellow
git -C $CreatorRepo commit -m $msg
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nothing new to commit." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
    git -C $CreatorRepo push
}

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Done! Creator repo updated." -ForegroundColor Green
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
