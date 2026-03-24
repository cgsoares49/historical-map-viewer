$root = 'C:\Users\csoar\OneDrive\Desktop\ClaudeTest\mapper'
$port = 8080

$mimeTypes = @{
    '.html' = 'text/html'
    '.js'   = 'application/javascript'
    '.css'  = 'text/css'
    '.txt'  = 'text/plain; charset=utf-8'
    '.prn'  = 'text/plain; charset=utf-8'
    '.asc'  = 'text/plain; charset=utf-8'
    '.dat'  = 'text/plain; charset=utf-8'
}

try {
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add("http://localhost:$port/")
    $listener.Start()
    Write-Host "Serving mapper at http://localhost:$port/mapper.html" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
} catch {
    Write-Host "ERROR starting listener: $_" -ForegroundColor Red
    Write-Host "Try running this PowerShell window as Administrator." -ForegroundColor Yellow
    pause
    exit
}

while ($listener.IsListening) {
    try {
        $ctx = $listener.GetContext()
        $localPath = $ctx.Request.Url.LocalPath
        if ($localPath -eq '/') { $localPath = '/mapper.html' }
        $filePath = Join-Path $root ($localPath.TrimStart('/').Replace('/', '\'))
        Write-Host "GET $localPath"
        if (Test-Path $filePath -PathType Leaf) {
            $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
            $mime = if ($mimeTypes[$ext]) { $mimeTypes[$ext] } else { 'application/octet-stream' }
            $bytes = [System.IO.File]::ReadAllBytes($filePath)
            $ctx.Response.ContentType = $mime
            $ctx.Response.ContentLength64 = $bytes.Length
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $ctx.Response.StatusCode = 404
            Write-Host "  404 not found: $filePath" -ForegroundColor Red
        }
        $ctx.Response.OutputStream.Close()
    } catch {
        Write-Host "Request error: $_" -ForegroundColor Red
    }
}
