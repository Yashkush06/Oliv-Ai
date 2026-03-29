# Oliv AI — Start Script
# Run this from the project root: .\start.ps1

Write-Host "Starting Oliv AI..." -ForegroundColor Cyan

# Start backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PSScriptRoot\backend'; .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload" `
    -WindowStyle Normal

Start-Sleep -Milliseconds 500

# Start frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PSScriptRoot\frontend'; npm run dev" `
    -WindowStyle Normal

Write-Host ""
Write-Host "  Backend  -> http://localhost:8000" -ForegroundColor Green
Write-Host "  Frontend -> http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "Opening dashboard in browser..." -ForegroundColor Cyan
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"
