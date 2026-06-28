# deploy.ps1
# Rebuilds geodata from PAR/primaries, commits code to GitHub, builds dist,
# and deploys to Cloudflare Workers (mapper.historymaps.org).
# Run from any directory — it finds the repo root automatically.

$RepoRoot  = Split-Path $PSScriptRoot -Parent
$MapperDir = $PSScriptRoot
$DataDir   = 'C:\My stuff\mapper'   # canonical data source
$DistDir   = Join-Path $RepoRoot 'dist\mapper'

Set-Location $RepoRoot

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Mapper Deploy Script" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Rebuild geodata from PAR/primaries (always) ───────────────────────
Write-Host "Running build_geodata.py..." -ForegroundColor Yellow
python "$MapperDir\build_geodata.py"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in build_geodata.py" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Running merge_geodata.py..." -ForegroundColor Yellow
python "$MapperDir\merge_geodata.py"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in merge_geodata.py" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Running export_geodata_csv.py..." -ForegroundColor Yellow
python "$MapperDir\export_geodata_csv.py"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in export_geodata_csv.py" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Running build_city_geodata.py..." -ForegroundColor Yellow
python "$MapperDir\build_city_geodata.py"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in build_city_geodata.py" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Running merge_city_geodata.py..." -ForegroundColor Yellow
python "$MapperDir\merge_city_geodata.py"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR in merge_city_geodata.py" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Geodata rebuild complete." -ForegroundColor Green
Write-Host "(WHE refs managed separately via whe_api_audit.py)" -ForegroundColor DarkGray

# ── Step 2: Show what changed ─────────────────────────────────────────────────
Write-Host ""
Write-Host "Changed files:" -ForegroundColor Yellow
git status --short

# ── Step 3: Commit message ────────────────────────────────────────────────────
$msg = "Update mapper data and code - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

# ── Step 4: Write app version into version.json ───────────────────────────────
$versionFile = "$MapperDir\version.json"
$versionObj  = Get-Content $versionFile -Raw | ConvertFrom-Json
$versionObj.app = Get-Date -Format 'yyyy-MM-dd'
$versionObj | ConvertTo-Json | Set-Content $versionFile
Write-Host "App version stamped: $($versionObj.app)" -ForegroundColor Cyan

# ── Step 5: Stage, commit, push (code only — data excluded by .gitignore) ─────
Write-Host ""
Write-Host "Staging files..." -ForegroundColor Yellow
git add mapper/

Write-Host "Committing..." -ForegroundColor Yellow
git commit -m $msg

if ($LASTEXITCODE -ne 0) {
    Write-Host "Nothing new to commit - continuing to deploy." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
git push

# ── Step 6: Build dist from canonical data ────────────────────────────────────
Write-Host ""
Write-Host "Building dist from $DataDir ..." -ForegroundColor Yellow

Copy-Item "$MapperDir\mapper.html"    "$DistDir\mapper.html"    -Force
Copy-Item "$MapperDir\version.json"  "$DistDir\version.json"   -Force
Copy-Item "$MapperDir\refs.json"     "$DistDir\refs.json"      -Force
Copy-Item "$MapperDir\sahm-logo.png" "$DistDir\sahm-logo.png"  -Force
Copy-Item "$MapperDir\map_2000CE.png" "$DistDir\map_2000CE.png" -Force
Copy-Item "$MapperDir\favicon.ico"   "$DistDir\favicon.ico"    -Force
Copy-Item "$MapperDir\js\*"          "$DistDir\js\"            -Recurse -Force

# robocopy: only copies files newer in source (/XO), including subdirs (/E)
# exit codes 0-7 are success; 8+ are errors
robocopy "$DataDir"          "$DistDir"          "primaries.txt" /XO | Out-Null
robocopy "$DataDir\polareas" "$DistDir\polareas" /E /XO | Out-Null
robocopy "$DataDir\pols"     "$DistDir\pols"     /E /XO | Out-Null
robocopy "$DataDir\coasts"   "$DistDir\coasts"   /E /XO | Out-Null
robocopy "$DataDir\niw"      "$DistDir\niw"      /E /XO | Out-Null
robocopy "$DataDir\cities"   "$DistDir\cities"   /E /XO | Out-Null
robocopy "$DataDir\inwaters"  "$DistDir\inwaters" /E /XO | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "ERROR: robocopy failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }

Write-Host "Dist built." -ForegroundColor Green

# ── Step 7: Deploy to Cloudflare ──────────────────────────────────────────────
Write-Host ""
Write-Host "Deploying to Cloudflare..." -ForegroundColor Yellow
npx wrangler deploy

Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Done! Live at mapper.historymaps.org" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
