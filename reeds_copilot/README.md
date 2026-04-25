# ReEDS-Copilot

An AI-powered assistant for the ReEDS (Regional Energy Deployment System) repository.  
Browse documentation, search source code, inspect inputs/outputs, and chat with an LLM that is grounded in the local repo context.

---

## Quick Start

### One-click launch (recommended)

```bash
# Windows
reeds_copilot\launch.bat

# Linux / macOS
bash reeds_copilot/launch.sh
```

This installs dependencies, starts backend + frontend, and opens the browser automatically.

### Manual setup

#### Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| npm | ≥ 9 |

#### 1. Set environment variables

```bash
# Required for real LLM responses (mock mode works without it)
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional overrides (shown with defaults)
export REEDS_COPILOT_LLM_PROVIDER=anthropic
export REEDS_COPILOT_MODEL=claude-opus-4-1
export REEDS_COPILOT_MAX_RESULTS=10
```

On Windows (PowerShell):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

### 2. Start the backend

```bash
cd reeds_copilot/backend

# Create a virtual environment (recommended)
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The API is now available at **http://localhost:8001**.  
Check health: `GET http://localhost:8001/health`

### 3. Start the frontend

```bash
cd reeds_copilot/frontend
npm install
npm run dev
```

Open **http://localhost:5173** in a browser.

The Vite dev server proxies `/api/*` requests to the backend at port 8001 automatically.

---

## Architecture

```
reeds_copilot/
  backend/
    app/
      main.py              # FastAPI app factory & lifespan
      core/config.py       # Pydantic settings from env vars
      api/
        chat.py            # POST /chat
        search.py          # POST /search
        files.py           # GET  /files/list, /files/preview
        health.py          # GET  /health
      services/
        llm.py             # LLM provider abstraction (Anthropic first)
        retrieval.py       # Text search over the indexed repo
        repo_index.py      # In-memory file catalogue
        file_inspector.py  # File listing, preview, CSV inspection
      models/
        schemas.py         # Pydantic request/response models
    requirements.txt
  frontend/
    src/
      App.tsx              # Shell layout with sidebar + tabs
      components/
        ChatPanel.tsx      # Chat thread and input
        SearchPanel.tsx    # Search bar and results
        FileBrowser.tsx    # Directory browser
        RightPanel.tsx     # Sources / file preview
        SettingsPanel.tsx  # Health/status check
      lib/
        api.ts             # Typed API client
    package.json
    vite.config.ts         # Proxy config
  README.md
```

### Key design decisions

- **No vector DB required** – the first-pass retrieval uses filename matching and brute-force text search. The code is modular so embeddings can be added later.
- **Mock mode** – if no `ANTHROPIC_API_KEY` is set, the chat endpoint returns a placeholder response so the UI can still be developed and tested.
- **Pluggable LLM** – `services/llm.py` defines an abstract `LLMProvider`; add new providers by subclassing.
- **Path safety** – file inspection endpoints resolve paths relative to the repo root and reject path traversal attempts.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Backend status, repo root, LLM config |
| `POST` | `/chat` | Send a message; receive an LLM answer + sources |
| `POST` | `/search` | Full-text search across the repo |
| `GET` | `/files/list?path=inputs` | List directory contents |
| `GET` | `/files/preview?path=inputs/scalars.csv` | Preview a text or CSV file |

### POST /chat

```json
{
  "message": "What switches control the capacity credit calculation?",
  "mode": "code",
  "selected_path": null
}
```

### POST /search

```json
{
  "query": "capacity credit",
  "category": "code",
  "max_results": 10
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key. Without it the app runs in mock mode. |
| `REEDS_COPILOT_LLM_PROVIDER` | `anthropic` | LLM provider name. |
| `REEDS_COPILOT_MODEL` | `claude-opus-4-1` | Model identifier. |
| `REEDS_COPILOT_MAX_RESULTS` | `10` | Max retrieval results per query. |
| `OPENAI_API_KEY` | *(empty)* | Reserved for future OpenAI support. |

---

## Extending

- **Add a new LLM provider**: subclass `LLMProvider` in `services/llm.py` and register it in `build_llm_provider`.
- **Add embedding-based retrieval**: extend `services/retrieval.py` with a vector search path.
- **Custom file categories**: adjust `_classify()` in `services/repo_index.py`.

---

## License

This tool is part of the ReEDS repository and follows the same license terms.
