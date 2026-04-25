$json = $input | Out-String | ConvertFrom-Json
$f = $json.tool_input.file_path
if (-not $f -or -not $f.EndsWith('.js')) { exit 0 }
$result = node --check $f 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "JS SYNTAX ERROR in $f"
    Write-Host $result
    exit 1
}
