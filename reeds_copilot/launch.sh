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

# Detect platform once for the auto-install helpers below.
case "$(uname -s)" in
    Darwin*) PLATFORM="macos" ;;
    Linux*)  PLATFORM="linux" ;;
    *)       PLATFORM="other" ;;
esac

# ── auto_install <friendly-name> <macos-brew-pkg> <linux-apt-pkg> <linux-dnf-pkg>
# Tries to install a missing tool using the OS package manager. Returns
# non-zero if no supported package manager is available or the install fails
# (typically because admin rights are required on a managed machine).
auto_install() {
    local name="$1" brew_pkg="$2" apt_pkg="$3" dnf_pkg="$4"
    echo "        $name not found. Attempting auto-install..."
    case "$PLATFORM" in
        macos)
            if ! command -v brew &>/dev/null; then
                echo "  ERROR: Homebrew is required for auto-install on macOS."
                echo "  Install Homebrew first: https://brew.sh/"
                return 1
            fi
            brew install "$brew_pkg"
            ;;
        linux)
            if command -v apt-get &>/dev/null; then
                sudo apt-get update -y && sudo apt-get install -y $apt_pkg
            elif command -v dnf &>/dev/null; then
                sudo dnf install -y $dnf_pkg
            elif command -v yum &>/dev/null; then
                sudo yum install -y $dnf_pkg
            else
                echo "  ERROR: No supported package manager (apt-get / dnf / yum) found."
                return 1
            fi
            ;;
        *)
            echo "  ERROR: Auto-install is not supported on this OS."
            return 1
            ;;
    esac
}

# Print a friendly "needs admin" message when auto_install fails.
admin_help() {
    local name="$1" url="$2"
    echo
    echo "  ========================================"
    echo "      Could not install $name automatically"
    echo "  ========================================"
    echo
    echo "  This usually means your computer requires administrator"
    echo "  rights to install new software (common on work laptops)."
    echo
    echo "  What to do:"
    echo "    - Personal computer: re-run this launcher with sudo, or install"
    echo "      $name manually from: $url"
    echo "    - Work / managed computer: please contact your IT admin and"
    echo "      ask them to install $name from: $url"
    echo
    echo "  Once $name is installed, re-run this launcher."
}

# ── Check Python ─────────────────────────────
echo "  [1/5] Checking Python..."
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    if ! auto_install "Python 3" "python@3.12" "python3 python3-pip python3-venv" "python3 python3-pip"; then
        admin_help "Python 3.10+" "https://www.python.org/downloads/"
        exit 1
    fi
fi
PY=$(command -v python3 || command -v python)
echo "        Found $($PY --version)"

# ── Check Node.js ────────────────────────────
echo "  [2/5] Checking Node.js..."
if ! command -v node &>/dev/null; then
    if ! auto_install "Node.js" "node" "nodejs npm" "nodejs npm"; then
        admin_help "Node.js 18+" "https://nodejs.org/"
        exit 1
    fi
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

BACKEND_PORT=8001

# Kill leftover processes on the ports
if command -v lsof &>/dev/null; then
    lsof -ti:$BACKEND_PORT 2>/dev/null | xargs kill -9 2>/dev/null || true
    lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
elif command -v ss &>/dev/null; then
    ss -tlnp "sport = :$BACKEND_PORT" 2>/dev/null | awk 'NR>1{split($6,a,","); gsub(/pid=/,"",a[2]); system("kill -9 "a[2])}' 2>/dev/null || true
    ss -tlnp "sport = :5173" 2>/dev/null | awk 'NR>1{split($6,a,","); gsub(/pid=/,"",a[2]); system("kill -9 "a[2])}' 2>/dev/null || true
fi
sleep 1

# Start backend
(cd backend && $PY -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT) &
BACKEND_PID=$!

# Wait for backend
echo "  Waiting for backend..."
until curl -s http://127.0.0.1:$BACKEND_PORT/health >/dev/null 2>&1; do sleep 1; done
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
echo "  ║   API:     http://127.0.0.1:$BACKEND_PORT         ║"
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
