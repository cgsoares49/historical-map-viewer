@echo off
:: Auto-elevate to admin if not already
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Starting mapper server at http://localhost:8080/mapper.html
echo Close this window to stop the server.
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0serve.ps1"
pause
