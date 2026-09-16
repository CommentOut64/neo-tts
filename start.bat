@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND_PYTHON=%ROOT%.venv\Scripts\python.exe"
set "BACKEND_PORT=18600"
set "VITE_BACKEND_ORIGIN=http://127.0.0.1:%BACKEND_PORT%"
set "NEO_TTS_DEVICE=cpu"
set "NEO_TTS_DTYPE=float32"

title Neo TTS CPU Launcher
echo ================================================
echo Neo TTS CPU Launcher
echo Device: CPU
echo Precision: float32
echo ================================================

if not exist "%BACKEND_PYTHON%" (
    echo Error: Backend Python was not found at "%BACKEND_PYTHON%".
    exit /b 1
)

netstat -ano | findstr /c:":%BACKEND_PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Error: Port %BACKEND_PORT% is already in use.
    echo Stop the existing backend before starting the CPU launcher.
    exit /b 1
)

echo Starting CPU backend on port %BACKEND_PORT%...
start "Neo TTS Backend CPU" /D "%ROOT%" "%BACKEND_PYTHON%" -m backend.app.cli --port %BACKEND_PORT%

echo Waiting for the backend...
for /L %%I in (1,1,60) do (
    netstat -ano | findstr /c:":%BACKEND_PORT%" | findstr /c:"LISTENING" >nul 2>&1
    if not errorlevel 1 goto start_frontend
    timeout /t 2 /nobreak >nul
)

echo Error: The backend did not start within 120 seconds.
echo Check the backend window and the latest file in logs for details.
exit /b 1

:start_frontend
echo Starting frontend...
cd /d "%ROOT%frontend"
call npm run dev
