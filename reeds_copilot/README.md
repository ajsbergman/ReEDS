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

### LLM API Key (required for AI chat)

ReEDS-Copilot uses commercial LLM APIs for its chat functionality. You need an API key from **at least one** of the providers below. Personal API usage is very affordable — typical interactive use costs **less than $1/month**.

> **Note:** An API key is different from a regular ChatGPT, Claude, or Gemini chat account. API keys are obtained from the provider's **developer console** (links below) and are billed separately on a pay-per-use basis.

| Provider | Sign Up | Pricing (approximate) | Notes |
|----------|---------|----------------------|-------|
| **Google Gemini** | [aistudio.google.com](https://aistudio.google.com/apikey) | Free tier available; paid starts at ~$0.15/million input tokens | Generous free tier, fast |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | ~$3–15/million input tokens depending on model | Best tool-use quality |
| **OpenAI** | [platform.openai.com](https://platform.openai.com/api-keys) | ~$2.50–10/million input tokens depending on model | Widely used, good all-around |

**How to get started:**
1. Create an account at one of the links above
2. Generate an API key from the provider's dashboard
3. Either set it as an environment variable (see below) or enter it directly in the ReEDS-Copilot **Settings** panel in the browser

> **Cost note:** A typical chat message uses roughly 2,000–5,000 input tokens. At Google Gemini's free tier or paid rate, you could send hundreds of messages per day for pennies. Even with Anthropic's most capable model, a full day of heavy usage rarely exceeds $1.

---

## What Can It Do?

- **AI Chat** — Ask questions about ReEDS in plain English. The AI reads the actual repo files and gives grounded answers with source citations.
- **Search** — Full-text search across all ReEDS code, documentation, and input files.
- **Browse Files** — Explore the repository structure, preview CSVs and text files directly in the browser.
- **Run ReEDS** — Configure and launch ReEDS runs, monitor progress, and cancel jobs — all from the UI.
- **Explore Inputs** — Browse and inspect model input files (load, fuel prices, plant costs, etc.).
- **Explore Outputs** — View output figures, tables, and data from completed runs. Ask the AI to show you plots or summarize results.
- **Post-Processing** — Generate Bokeh reports and run Compare Cases with a few clicks.

---

## Future Development

Feature requests and roadmap ideas are tracked in the
[shared development list](https://nrel-my.sharepoint.com/:x:/g/personal/ychen10_nrel_gov/IQAA7I3lW2KZRaiSCwFNPS1hAUozwyOPW-kRIx6XzVh53n8) (accessible to NLR staff).

---

## Acknowledgments

Initially created by Yunzhi Chen (yunzhi.chen@nlr.gov) from the ReEDS team.

---

## License

This tool is part of the ReEDS repository and follows the same license terms.
