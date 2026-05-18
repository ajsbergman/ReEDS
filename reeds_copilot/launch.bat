@echo off
setlocal enabledelayedexpansion
title ReEDS-Copilot
cd /d "%~dp0"

echo.
echo   ========================================
echo       ReEDS-Copilot  Launcher
echo   ========================================
echo.

set "NEED_RESTART=0"

:: ── Check Python ───────────────────────────────────
rem [1/5] Checking Python...
echo   [1/5] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo         Python not found. Attempting auto-install via winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   ERROR: winget is not available on this machine.
        echo   Please install Python 3.10+ manually from:
        echo       https://www.python.org/downloads/
        echo   Then re-run this launcher.
        goto :fail
    )
    echo         Installing Python 3.12 ^(may take a couple of minutes^)...
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo   ========================================
        echo       Could not install Python automatically
        echo   ========================================
        echo.
        echo   This usually means your computer requires administrator
        echo   rights to install new software ^(common on work laptops^).
        echo.
        echo   What to do:
        echo     - Personal laptop: right-click launch.bat and choose
        echo       "Run as administrator", then try again.
        echo     - Work / managed laptop: please contact your IT admin and
        echo       ask them to install Python 3.10+ from:
        echo           https://www.python.org/downloads/
        echo.
        echo   Once Python is installed, re-run this launcher.
        goto :fail
    )
    echo         Python installed.
    set "NEED_RESTART=1"
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo         Found %%i
)

:: ── Check Node.js ──────────────────────────────────
echo   [2/5] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo         Node.js not found. Attempting auto-install via winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   ERROR: winget is not available on this machine.
        echo   Please install Node.js 18+ manually from:
        echo       https://nodejs.org/
        echo   Then re-run this launcher.
        goto :fail
    )
    echo         Installing Node.js LTS ^(may take a couple of minutes^)...
    winget install -e --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo   ========================================
        echo       Could not install Node.js automatically
        echo   ========================================
        echo.
        echo   This usually means your computer requires administrator
        echo   rights to install new software ^(common on work laptops^).
        echo.
        echo   What to do:
        echo     - Personal laptop: right-click launch.bat and choose
        echo       "Run as administrator", then try again.
        echo     - Work / managed laptop: please contact your IT admin and
        echo       ask them to install Node.js 18+ from:
        echo           https://nodejs.org/
        echo.
        echo   Once Node.js is installed, re-run this launcher.
        goto :fail
    )
    echo         Node.js installed.
    set "NEED_RESTART=1"
) else (
    for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo         Found Node %%i
)

:: If we installed anything, the current cmd session can't see the new PATH
:: entries until a new shell starts. Ask the user to relaunch — simplest and
:: most reliable way to pick up the newly installed tools.
if "%NEED_RESTART%"=="1" (
    echo.
    echo   ========================================
    echo       Setup complete!
    echo.
    echo       Required tools have been installed.
    echo       Please CLOSE this window and double-click
    echo       launch.bat again to start ReEDS-Copilot.
    echo   ========================================
    echo.
    pause
    exit /b 0
)

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
