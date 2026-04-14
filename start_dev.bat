@echo off
title GPT-SoVITS Dev Launcher
set "BACKEND_PYTHON=%~dp0.venv\Scripts\python.exe"
set "BACKEND_PORT=18600"
set "VITE_BACKEND_ORIGIN=http://127.0.0.1:%BACKEND_PORT%"

echo ================================================
echo   GPT-SoVITS Dev Launcher
echo ================================================
echo [compat] start_dev.bat is a compatibility entrypoint.
echo [compat] Recommended main entrypoint: launcher.
echo.

if not exist "%BACKEND_PYTHON%" (
    echo [x] Missing backend virtualenv python: "%BACKEND_PYTHON%"
    echo     Please create or repair the project .venv before starting dev services.
    exit /b 1
)

:: Check if backend port is already in use
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [!] Port %BACKEND_PORT% already in use, skipping backend start
    goto start_frontend
)

:: Start backend in a separate window
:start_backend
echo [1/2] Starting backend on port %BACKEND_PORT% (separate window)...
start "GPT-SoVITS Backend" /D "%~dp0" "%BACKEND_PYTHON%" -m backend.app.cli --port %BACKEND_PORT%

:: Wait for backend to be ready
echo      Waiting for backend to be ready...
:wait_backend
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto wait_backend
echo      Backend is ready.

:: Start frontend in current window (logs visible here)
:start_frontend
echo [2/2] Starting frontend (logs below)
echo      VITE_BACKEND_ORIGIN=%VITE_BACKEND_ORIGIN%
echo ================================================
cd /d %~dp0frontend
npm run dev
