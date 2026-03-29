$port = 8080
$root = $PSScriptRoot

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://localhost:$port/")
$listener.Start()

Write-Host "Server running at http://localhost:$port/"
Write-Host "  Mapper       : http://localhost:$port/mapper/mapper.html"
Write-Host "  Tic Tac Toe  : http://localhost:$port/tictactoe.html"
Write-Host ""
Write-Host "Press Ctrl+C to stop."

try {
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $req = $ctx.Request
        $res = $ctx.Response

        $urlPath = $req.Url.LocalPath
        if ($urlPath -eq "/") { $urlPath = "/mapper/mapper.html" }

        $filePath = Join-Path $root $urlPath.TrimStart("/").Replace("/", "\")

        if (Test-Path $filePath -PathType Leaf) {
            $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
            $mime = switch ($ext) {
                ".html" { "text/html" }
                ".js"   { "application/javascript" }
                ".css"  { "text/css" }
                ".png"  { "image/png" }
                ".jpg"  { "image/jpeg" }
                ".ico"  { "image/x-icon" }
                ".txt"  { "text/plain; charset=utf-8" }
                ".prn"  { "text/plain; charset=utf-8" }
                ".asc"  { "text/plain; charset=utf-8" }
                default { "application/octet-stream" }
            }
            $bytes = [System.IO.File]::ReadAllBytes($filePath)
            $res.ContentType = $mime
            $res.ContentLength64 = $bytes.Length
            $res.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $res.StatusCode = 404
            $body = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found")
            $res.ContentLength64 = $body.Length
            $res.OutputStream.Write($body, 0, $body.Length)
        }

        $res.OutputStream.Close()
    }
} finally {
    $listener.Stop()
}
