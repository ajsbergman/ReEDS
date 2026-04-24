#!/usr/bin/env bash
# ReEDS-Copilot — one-click launcher (Linux / macOS / Git Bash on Windows)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  ReEDS-Copilot  —  Starting up..."
echo "============================================"
echo

# ── Backend setup ────────────────────────────
echo "[1/4] Setting up backend Python environment..."
if [ ! -d "backend/.venv" ]; then
    echo "       Creating virtual environment..."
    python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate

echo "[2/4] Installing backend dependencies..."
pip install -q -r backend/requirements.txt

# ── Frontend setup ───────────────────────────
echo "[3/4] Installing frontend dependencies..."
if [ ! -d "frontend/node_modules" ]; then
    (cd frontend && npm install)
else
    echo "       node_modules already present, skipping."
fi

# ── Launch servers ───────────────────────────
echo "[4/4] Starting servers..."
echo

# Start backend in background
(cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

sleep 2

# Start frontend in background
(cd frontend && npm run dev) &
FRONTEND_PID=$!

sleep 4

# ── Open browser ─────────────────────────────
URL="http://localhost:5173"
echo
echo "============================================"
echo "  ReEDS-Copilot is running!"
echo "  Backend  : http://127.0.0.1:8000"
echo "  Frontend : $URL"
echo "============================================"
echo

if command -v xdg-open &>/dev/null; then
    xdg-open "$URL"
elif command -v open &>/dev/null; then
    open "$URL"
else
    echo "  Open $URL in your browser."
fi

echo
echo "Press Ctrl+C to stop both servers."

# Clean up on exit
cleanup() {
    echo
    echo "Stopping servers..."
    kill "$BACKEND_PID" 2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

wait
