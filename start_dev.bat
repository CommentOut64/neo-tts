@echo off
title GPT-SoVITS Dev Launcher

echo ================================================
echo   GPT-SoVITS Dev Launcher
echo ================================================
echo.

:: Check if backend port is already in use
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [!] Port 8000 already in use, skipping backend start
    goto start_frontend
)

:: Start frontend in a separate window
:start_frontend
echo [1/2] Starting frontend (separate window)...
start "GPT-SoVITS Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

:: Wait a moment then open browser
timeout /t 3 /nobreak >nul
start "" http://localhost:5173

:: Start backend in current window (logs visible here)
echo [2/2] Starting backend on port 8000 (logs below)
echo ================================================
cd /d %~dp0
python -m backend.app.cli --port 8000
pause
