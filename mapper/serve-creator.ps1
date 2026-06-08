$codeRoot = 'C:\My stuff\ClaudeTest\mapper'
$dataRoot = 'C:\My stuff\mapper'
$port     = 8081

$dataDirs = @('polareas','pols','coasts','niw','cities','inwaters','rivers')
$dataFiles = @('primaries.txt','newoffsets.txt')

$mimeTypes = @{
    '.html' = 'text/html'
    '.js'   = 'application/javascript'
    '.json' = 'application/json'
    '.css'  = 'text/css'
    '.txt'  = 'text/plain; charset=utf-8'
    '.prn'  = 'text/plain; charset=utf-8'
    '.asc'  = 'text/plain; charset=utf-8'
    '.dat'  = 'text/plain; charset=utf-8'
    '.png'  = 'image/png'
    '.ico'  = 'image/x-icon'
    '.bmp'  = 'image/bmp'
}

try {
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add("http://localhost:$port/")
    $listener.Start()
    Write-Host "CREATOR server at http://localhost:$port/mapper-local.html" -ForegroundColor Blue
    Write-Host "Data root : $dataRoot" -ForegroundColor DarkCyan
    Write-Host "Code root : $codeRoot" -ForegroundColor DarkCyan
    Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
} catch {
    Write-Host "ERROR starting listener: $_" -ForegroundColor Red
    Write-Host "Try running as Administrator." -ForegroundColor Yellow
    pause; exit
}

function Send-Json($ctx, $obj, $status = 200) {
    $json  = $obj | ConvertTo-Json -Depth 10 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $ctx.Response.ContentType     = 'application/json'
    $ctx.Response.StatusCode      = $status
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.OutputStream.Close()
}

while ($listener.IsListening) {
    try {
        $ctx       = $listener.GetContext()
        $method    = $ctx.Request.HttpMethod
        $localPath = $ctx.Request.Url.LocalPath
        $query     = $ctx.Request.QueryString

        if ($localPath -eq '/') { $localPath = '/mapper-local.html' }

        # ── POST /save-refs ───────────────────────────────────────────────────
        if ($method -eq 'POST' -and $localPath -eq '/save-refs') {
            $reader = New-Object System.IO.StreamReader($ctx.Request.InputStream)
            $body   = $reader.ReadToEnd(); $reader.Close()
            $refsPath = Join-Path $codeRoot 'refs.json'
            [System.IO.File]::WriteAllText($refsPath, $body, [System.Text.Encoding]::UTF8)
            Write-Host "POST /save-refs  ($($body.Length) bytes)" -ForegroundColor Cyan
            Send-Json $ctx @{ok=$true}; continue
        }

        # ── GET /search?q=TERM&type=par|pol|cst|all ───────────────────────────
        if ($method -eq 'GET' -and $localPath -eq '/search') {
            $q    = $query['q']
            $type = if ($query['type']) { $query['type'] } else { 'all' }
            if (-not $q) { Send-Json $ctx @{error='missing q'} 400; continue }

            $year = $query['year']
            $dirMap     = @{ par='polareas'; pol='pols'; niw='niw'; cities='cities' }
            $searchDirs = if ($dirMap[$type]) { @($dirMap[$type]) } else {
                @('polareas','pols','niw','cities','inwaters')
            }

            $results   = @()
            $truncated = $false

            try {
                foreach ($dir in $searchDirs) {
                    if ($truncated) { break }
                    $fullDir = Join-Path $dataRoot $dir
                    if (-not (Test-Path $fullDir)) { continue }
                    foreach ($file in (Get-ChildItem $fullDir -Recurse -File)) {
                        if ($truncated) { break }
                        $lines = [System.IO.File]::ReadAllLines($file.FullName)
                        # Year filter: skip file entirely if it doesn't contain the year string
                        if ($year) {
                            $fileText = [string]::Join(' ', $lines)
                            if ($fileText.IndexOf($year, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
                        }
                        for ($i = 0; $i -lt $lines.Count; $i++) {
                            if ($lines[$i].IndexOf($q, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                                $rel = $file.FullName.Substring($dataRoot.Length).TrimStart('\') -replace '\\','/'
                                $results += [PSCustomObject]@{ file=$rel; line=($i+1); content=$lines[$i].Trim() }
                                if ($results.Count -ge 500) { $truncated = $true; break }
                            }
                        }
                    }
                }
            } catch {
                Write-Host "Search error: $_" -ForegroundColor Red
            }

            $yearMsg = if ($year) { " year=$year" } else { '' }
            Write-Host "GET /search?q=$q type=$type$yearMsg  ($($results.Count) hits)" -ForegroundColor Cyan
            # Build JSON manually — avoids PS 5.1 ConvertTo-Json array/depth issues
            $itemsJson = ($results | ForEach-Object {
                $f = $_.file   -replace '\\','/' -replace '"','\"'
                $c = $_.content -replace '\\','\\' -replace '"','\"'
                "{`"file`":`"$f`",`"line`":$($_.line),`"content`":`"$c`"}"
            }) -join ','
            $trunc = if ($truncated) { 'true' } else { 'false' }
            $json  = "{`"results`":[$itemsJson],`"count`":$($results.Count),`"truncated`":$trunc}"
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
            $ctx.Response.ContentType     = 'application/json'
            $ctx.Response.StatusCode      = 200
            $ctx.Response.ContentLength64 = $bytes.Length
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
            $ctx.Response.OutputStream.Close()
            continue
        }

        # ── POST /replace  {file, find, replace, preview} ────────────────────
        if ($method -eq 'POST' -and $localPath -eq '/replace') {
            $reader = New-Object System.IO.StreamReader($ctx.Request.InputStream)
            $body   = $reader.ReadToEnd(); $reader.Close()
            $req    = $body | ConvertFrom-Json

            $filePath = Join-Path $dataRoot ($req.file -replace '/','\\')
            if (-not (Test-Path $filePath)) {
                Send-Json $ctx @{error='file not found'} 404; continue
            }

            $content    = [System.IO.File]::ReadAllText($filePath, [System.Text.Encoding]::UTF8)
            $newContent = $content.Replace($req.find, $req.replace)
            $count      = ($content.Length - $newContent.Replace($req.replace,$req.find).Length) / [Math]::Max(1,$req.find.Length - $req.replace.Length + 1)
            $count      = ($content.Split($req.find).Count - 1)

            if (-not $req.preview) {
                [System.IO.File]::WriteAllText($filePath, $newContent, [System.Text.Encoding]::UTF8)
                Write-Host "POST /replace  $($req.file)  ($count replacements)" -ForegroundColor Cyan
            } else {
                Write-Host "POST /replace (preview)  $($req.file)  ($count matches)" -ForegroundColor DarkCyan
            }

            Send-Json $ctx @{count=$count; preview=[bool]$req.preview}
            continue
        }

        # ── GET static files — route data dirs to dataRoot ────────────────────
        $segment   = $localPath.TrimStart('/').Replace('/','\')
        $firstPart = ($segment -split '\\')[0]

        $filePath = if (($dataDirs -contains $firstPart) -or ($dataFiles -contains $segment)) {
            Join-Path $dataRoot $segment
        } else {
            Join-Path $codeRoot $segment
        }

        Write-Host "GET $localPath"
        if (Test-Path $filePath -PathType Leaf) {
            $ext   = [System.IO.Path]::GetExtension($filePath).ToLower()
            $mime  = if ($mimeTypes[$ext]) { $mimeTypes[$ext] } else { 'application/octet-stream' }
            $bytes = [System.IO.File]::ReadAllBytes($filePath)
            $ctx.Response.ContentType     = $mime
            $ctx.Response.ContentLength64 = $bytes.Length
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $ctx.Response.StatusCode = 404
            Write-Host "  404: $filePath" -ForegroundColor Red
        }
        $ctx.Response.OutputStream.Close()

    } catch {
        Write-Host "Request error: $_" -ForegroundColor Red
    }
}
