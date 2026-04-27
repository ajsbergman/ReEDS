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

This installs dependencies, starts backend (port 8001) + frontend (port 5173), and opens the browser automatically.

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.10 | Backend runtime |
| Node.js | ≥ 18 | Frontend dev server |
| npm | ≥ 9 | Package management |

**For running ReEDS models** (optional):
| Tool | Notes |
|------|-------|
| Conda | With an environment containing ReEDS dependencies (default name: `reeds2`) |
| GAMS | Licensed, on PATH or auto-detected |
| Julia | Version matching `Project.toml` (managed via juliaup) |

### Manual setup

#### 1. Set environment variables (optional)

API keys can also be entered in the browser UI at runtime — no env vars required.

```bash
# Optional: pre-set LLM key so it loads automatically
export ANTHROPIC_API_KEY="sk-ant-..."
# Or use OpenAI / Google
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="AI..."
```

### 2. Start the backend

```bash
cd reeds_copilot/backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 3. Start the frontend

```bash
cd reeds_copilot/frontend
npm install
npm run dev
```

Open **http://localhost:5173** in a browser.  
The Vite dev server proxies `/api/*` requests to the backend at port 8001.

---

## Architecture

```
reeds_copilot/
  launch.bat / launch.sh   # One-click launchers
  backend/
    app/
      main.py              # FastAPI app factory & lifespan
      core/config.py       # Pydantic settings from env vars
      api/
        chat.py            # POST /chat
        search.py          # POST /search
        files.py           # GET  /files/list, /files/preview
        health.py          # GET  /health, POST /config/api-key, GET /config/models
        sessions.py        # Chat session CRUD
        runs.py            # Run ReEDS management endpoints
      services/
        llm.py             # LLM provider abstraction (Anthropic, OpenAI, Google)
        retrieval.py       # Text search over the indexed repo
        repo_index.py      # In-memory file catalogue
        file_inspector.py  # File listing, preview, CSV inspection
        chat_store.py      # Chat history persistence
        env_check.py       # Environment health checks & auto-fixes
        run_manager.py     # Run lifecycle management
      models/
        schemas.py         # Pydantic request/response models
    requirements.txt
  frontend/
    src/
      App.tsx              # Shell layout with sidebar + tabs
      components/
        ChatPanel.tsx      # Chat thread and input
        ChatHistory.tsx    # Saved conversations
        SearchPanel.tsx    # Search bar and results
        FileBrowser.tsx    # Directory browser
        RunPanel.tsx       # Launch & monitor ReEDS runs
        OutputExplorer.tsx # Browse run outputs
        RightPanel.tsx     # Sources / file preview
        SettingsPanel.tsx  # Health/status check
        WelcomeScreen.tsx  # First-time setup
      lib/
        api.ts             # Typed API client
        providers.ts       # LLM provider definitions
    package.json
    vite.config.ts         # Proxy config → backend:8001
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
| `POST` | `/config/api-key` | Set LLM provider, model, and API key |
| `GET` | `/config/models` | List models from active provider |
| `POST` | `/chat` | Send a message; receive LLM answer + sources |
| `POST` | `/search` | Full-text search across the repo |
| `GET` | `/files/list?path=` | List directory contents |
| `GET` | `/files/preview?path=` | Preview a text or CSV file |
| `GET` | `/chat/sessions` | List saved chat sessions |
| `POST` | `/chat/sessions` | Create a new chat session |
| `DELETE`| `/chat/sessions/{id}` | Delete a chat session |
| `POST` | `/runs` | Start a ReEDS run |
| `GET` | `/runs` | List active/recent runs |
| `GET` | `/runs/{id}` | Get run status and logs |
| `POST` | `/runs/{id}/cancel` | Cancel a running job |
| `GET` | `/runs/conda-envs` | List available conda environments |
| `GET` | `/runs/env-check` | Run environment health checks |
| `POST` | `/runs/env-fix` | Auto-fix a failing check |
| `GET` | `/runs/folders/list` | List completed run folders |

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

## Acknowledgments

Initially created by **Yunzhi Chen** (yunzhi.chen@nlr.gov).

---

## License

This tool is part of the ReEDS repository and follows the same license terms.
