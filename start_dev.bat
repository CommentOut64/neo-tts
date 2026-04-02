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

:: Start backend in a separate window
:start_backend
echo [1/2] Starting backend on port 8000 (separate window)...
start "GPT-SoVITS Backend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && python -m backend.app.cli --port 8000"

:: Wait for backend to be ready
echo      Waiting for backend to be ready...
:wait_backend
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto wait_backend
echo      Backend is ready.

:: Start frontend in current window (logs visible here)
echo [2/2] Starting frontend (logs below)
echo ================================================
cd /d %~dp0frontend
npm run dev
