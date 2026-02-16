# Release creation script for MapgeoAddon
# Usage: .\create_release.ps1 -Version "0.1.2"

param(
    [Parameter(Mandatory=$true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

Write-Host "Creating release v$Version..." -ForegroundColor Cyan

# 1. Create git tag
Write-Host "`n[1/5] Creating git tag v$Version..." -ForegroundColor Yellow
git tag "v$Version"
git push origin "v$Version"

# 2. Create zip file
Write-Host "`n[2/5] Creating zip archive..." -ForegroundColor Yellow
$zipName = "MapgeoAddon_v$Version.zip"
Compress-Archive -Path * -DestinationPath $zipName -Force

# 3. Create GitHub release
Write-Host "`n[3/5] Creating GitHub release..." -ForegroundColor Yellow
gh release create "v$Version" $zipName -t "v$Version" -n "Release v$Version"

# 4. Clean up zip file
Write-Host "`n[4/5] Cleaning up zip file..." -ForegroundColor Yellow
Remove-Item $zipName

# 5. Done
Write-Host "`n[5/5] Release v$Version created successfully!" -ForegroundColor Green
Write-Host "View at: https://github.com/TheKillerey/MapgeoAddon/releases/tag/v$Version" -ForegroundColor Cyan
