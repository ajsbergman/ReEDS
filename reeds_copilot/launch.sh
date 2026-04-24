#!/usr/bin/env bash
# ReEDS-Copilot — one-click launcher (Linux / macOS / Git Bash)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         ReEDS-Copilot  Launcher          ║"
echo "  ╚══════════════════════════════════════════╝"
echo

# ── Check Python ─────────────────────────────
echo "  [1/5] Checking Python..."
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "  ERROR: Python not found. Install Python 3.10+."
    exit 1
fi
PY=$(command -v python3 || command -v python)
echo "        Found $($PY --version)"

# ── Check Node.js ────────────────────────────
echo "  [2/5] Checking Node.js..."
if ! command -v node &>/dev/null; then
    echo "  ERROR: Node.js not found. Install Node.js 18+ from https://nodejs.org"
    exit 1
fi
echo "        Found Node $(node --version)"

# ── Backend dependencies ─────────────────────
echo "  [3/5] Installing backend dependencies..."
$PY -m pip install -q -r backend/requirements.txt
echo "        Done."

# ── Frontend dependencies ────────────────────
echo "  [4/5] Installing frontend dependencies..."
if [ ! -d "frontend/node_modules/vite" ]; then
    echo "        Running npm install (first time only)..."
    (cd frontend && npm install --silent)
else
    echo "        Already installed, skipping."
fi

# ── Launch servers ───────────────────────────
echo "  [5/5] Starting servers..."
echo

# Kill leftover processes
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true

# Start backend
(cd backend && $PY -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

# Wait for backend
echo "  Waiting for backend..."
until curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; do sleep 1; done
echo "        Backend ready."

# Start frontend
(cd frontend && npm run dev) &
FRONTEND_PID=$!

# Wait for frontend
echo "  Waiting for frontend..."
until curl -s http://localhost:5173 >/dev/null 2>&1; do sleep 1; done
echo "        Frontend ready."

sleep 1

# Open browser
URL="http://localhost:5173"
if command -v xdg-open &>/dev/null; then
    xdg-open "$URL"
elif command -v open &>/dev/null; then
    open "$URL"
else
    echo "  Open $URL in your browser."
fi

echo
echo "  ╔══════════════════════════════════════════╗"
echo "  ║       ReEDS-Copilot is running!          ║"
echo "  ║                                          ║"
echo "  ║   App:     http://localhost:5173          ║"
echo "  ║   API:     http://127.0.0.1:8000         ║"
echo "  ║                                          ║"
echo "  ║   Press Ctrl+C to stop and exit.         ║"
echo "  ╚══════════════════════════════════════════╝"
echo

cleanup() {
    echo
    echo "  Stopping servers..."
    kill "$BACKEND_PID" 2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null
    echo "  Done. Goodbye!"
}
trap cleanup EXIT INT TERM

wait
