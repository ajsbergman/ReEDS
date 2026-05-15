@echo off
setlocal enabledelayedexpansion
title ReEDS-Copilot
cd /d "%~dp0"

echo.
echo   ========================================
echo       ReEDS-Copilot  Launcher
echo   ========================================
echo.

:: ── Check Python ─────────────────────────────
echo   [1/5] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found. Install Python 3.10+ and add it to PATH.
    goto :fail
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo         Found %%i

:: ── Check Node.js ────────────────────────────
echo   [2/5] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Node.js not found. Install from https://nodejs.org
    goto :fail
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo         Found Node %%i

:: ── Backend dependencies ─────────────────────
echo   [3/5] Installing backend dependencies...
pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo   ERROR: Failed to install backend dependencies.
    goto :fail
)
echo         Done.

:: ── Frontend dependencies ────────────────────
echo   [4/5] Installing frontend dependencies...
cd frontend
if not exist "node_modules\.bin\vite" (
    echo         Running npm install...
    call npm install
) else (
    echo         Already installed, skipping.
)
cd /d "%~dp0"

:: ── Start servers ────────────────────────────
echo   [5/5] Starting servers...
echo.

:: Store the working directory
set "COPILOT_DIR=%~dp0"
set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5173"

:: Kill any process already using the backend port
echo   Cleaning up port %BACKEND_PORT%...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%BACKEND_PORT% "') do (
    taskkill /F /T /PID %%p >nul 2>&1
)

:: Kill any process already using the frontend port
echo   Cleaning up port %FRONTEND_PORT%...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%FRONTEND_PORT% "') do (
    taskkill /F /T /PID %%p >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Start backend in a minimized window (cmd /c so the window auto-closes
:: when uvicorn exits — supports the in-app Shutdown button)
start "ReEDS-Copilot Backend" /min cmd /c "cd /d "%COPILOT_DIR%" && python -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --app-dir backend"

:: Wait for backend (max 30 seconds)
echo   Waiting for backend...
set /a TRIES=0
:wait_backend
if !TRIES! geq 30 (
    echo   ERROR: Backend did not start in 30 seconds.
    goto :fail_with_cleanup
)
timeout /t 1 /nobreak >nul
set /a TRIES+=1
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/health')" >nul 2>&1
if errorlevel 1 goto :wait_backend
echo         Backend ready.

:: Start frontend in a minimized window (cmd /c so the window auto-closes
:: when vite exits)
start "ReEDS-Copilot Frontend" /min cmd /c "cd /d "%COPILOT_DIR%frontend" && npm run dev"

:: Wait for frontend (max 30 seconds)
echo   Waiting for frontend...
set /a TRIES=0
:wait_frontend
if !TRIES! geq 30 (
    echo   ERROR: Frontend did not start in 30 seconds.
    goto :fail_with_cleanup
)
timeout /t 1 /nobreak >nul
set /a TRIES+=1
python -c "import urllib.request; urllib.request.urlopen('http://localhost:5173')" >nul 2>&1
if errorlevel 1 goto :wait_frontend
echo         Frontend ready.

:: Open browser
timeout /t 1 /nobreak >nul
start "" http://localhost:5173

echo.
echo   ========================================
echo       ReEDS-Copilot is running!
echo.
echo       App:  http://localhost:5173
echo       API:  http://127.0.0.1:%BACKEND_PORT%
echo.
echo       Press any key to STOP and exit.
echo   ========================================
echo.
pause >nul

:: Cleanup
echo   Stopping servers...
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Backend*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Frontend*" /f >nul 2>&1
echo   Done. Goodbye!
timeout /t 2 /nobreak >nul
exit /b 0

:fail_with_cleanup
echo   Cleaning up partial start...
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Backend*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Frontend*" /f >nul 2>&1
goto :fail

:fail
echo.
echo   Something went wrong. See the error above.
echo   Press any key to exit.
pause >nul
exit /b 1
