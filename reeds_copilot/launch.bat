@echo off
setlocal
title ReEDS-Copilot Launcher

cd /d "%~dp0"

echo ============================================
echo   ReEDS-Copilot  —  Starting up...
echo ============================================
echo.

:: ── Backend setup ────────────────────────────
echo [1/4] Setting up backend Python environment...
if not exist "backend\.venv\Scripts\python.exe" (
    echo       Creating virtual environment...
    python -m venv backend\.venv
)
call backend\.venv\Scripts\activate.bat

echo [2/4] Installing backend dependencies...
pip install -q -r backend\requirements.txt

:: ── Frontend setup ───────────────────────────
echo [3/4] Installing frontend dependencies...
cd frontend
if not exist "node_modules" (
    call npm install
) else (
    echo       node_modules already present, skipping.
)
cd ..

:: ── Launch servers ───────────────────────────
echo [4/4] Starting servers...
echo.

:: Start backend in a new minimized window
start "ReEDS-Copilot Backend" /min cmd /c "call backend\.venv\Scripts\activate.bat && uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend"

:: Give the backend a moment to bind
timeout /t 3 /nobreak >nul

:: Start frontend in a new minimized window
start "ReEDS-Copilot Frontend" /min cmd /c "cd frontend && npm run dev"

:: Wait for Vite to be ready
echo Waiting for frontend to start...
timeout /t 5 /nobreak >nul

:: Open browser
echo.
echo ============================================
echo   ReEDS-Copilot is running!
echo   Backend  : http://127.0.0.1:8000
echo   Frontend : http://localhost:5173
echo ============================================
echo.
echo   Opening browser...
start "" http://localhost:5173

echo.
echo Press any key to STOP both servers and exit.
pause >nul

:: Kill the server windows
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Backend" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq ReEDS-Copilot Frontend" /f >nul 2>&1
echo Servers stopped.
