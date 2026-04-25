# Start Mapper Server

Start the local HTTP server for the mapper project.

## Steps

1. Check if a server is already running on port 8080 by running: `netstat -ano | findstr :8080`
2. If already running, tell the user and provide the URL: http://localhost:8080/mapper/mapper.html
3. If not running, tell the user to double-click **Mapper Server.bat** on the Desktop (it auto-elevates to admin)
4. Provide the URL to open once the server is started: http://localhost:8080/mapper/mapper.html

## Notes
- The server requires admin privileges — the .bat handles this automatically
- Keep the server window open; closing it stops the server
- The server root is `C:\Users\csoar\OneDrive\Desktop\ClaudeTest`
