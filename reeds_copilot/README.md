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

> **First-time on a fresh computer?** The launcher will auto-install Python and Node.js for you using your system's package manager (`winget` on Windows, `brew` on macOS, `apt`/`dnf` on Linux). After they install, just close the window and double-click the launcher again — that's it.

### Prerequisites

| Tool    | Version | Notes                              |
| ------- | ------- | ---------------------------------- |
| Python  | ≥ 3.10 | Backend runtime — auto-installed if missing |
| Node.js | ≥ 18   | Frontend dev server (includes npm) — auto-installed if missing |

**For running ReEDS models:**

| Tool  | Notes                                                                       |
| ----- | --------------------------------------------------------------------------- |
| Conda | With an environment containing ReEDS dependencies (default name:`reeds2`) |
| GAMS  | Licensed, on PATH or auto-detected                                          |
| Julia | Version matching `Project.toml` (managed via juliaup)                     |

> The **Setup Wizard** inside ReEDS-Copilot detects what's missing and offers one-click install/configuration for each of these.

### LLM API Key (required for AI chat)

ReEDS-Copilot uses commercial LLM APIs for its chat functionality. You need an API key from **at least one** of the providers below.

> **NLR staff:** the easiest option is NLR's LiteLLM gateway, which lets you use Claude, GPT, and Gemini models through a single key billed to an NLR project charge code. The login page in ReEDS-Copilot walks you through obtaining the key step by step.

> **External users / personal use:** sign up directly with one of the providers below. Personal API usage is very affordable — typical interactive use costs **less than $10/month**.

> **Note:** An API key is different from a regular ChatGPT, Claude, or Gemini chat account. API keys are obtained from the provider's **developer console** (links below) and are billed separately on a pay-per-use basis.

| Provider                                     | Sign Up                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Pricing (approximate)                                           | Notes                                             |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------- |
| **NLR LiteLLM** *(NLR VPN required)* | [https://cloud.nlr.gov/](https://gcc02.safelinks.protection.outlook.com/?url=https%3A%2F%2Fcloud.nlr.gov%2F&data=05%7C02%7CYunzhi.Chen%40nlr.gov%7C31716e7c6831430d056708deb1e421e5%7Ca0f29d7e28cd4f5484427885aee7c080%7C0%7C0%7C639143790553772984%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=DNMJcs4wKyBHwQ8mMbTWNHv9eY1deMj%2Bk6PjggqeKqM%3D&reserved=0 "Original URL: https://cloud.nlr.gov/. Click or tap if you trust this link.") | Billed to an NLR charge code                                    | Access to Claude, GPT, and Gemini through one key |
| **Google Gemini**                      | [aistudio.google.com](https://aistudio.google.com/apikey)                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Free tier available; paid starts at ~$0.15/million input tokens | Generous free tier, fast                          |
| **Anthropic**                          | [console.anthropic.com](https://console.anthropic.com/)                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | ~$3–15/million input tokens depending on model                 | Best tool-use quality                             |
| **OpenAI**                             | [platform.openai.com](https://platform.openai.com/api-keys)                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | ~$2.50–10/million input tokens depending on model              | Widely used, good all-around                      |

---

## What Can It Do?

- **Setup Wizard** — Step-by-step guided setup for first-time users. Checks all prerequisites (Conda, GAMS, Julia, etc.) and offers one-click fixes for what's missing.
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

ReEDS-Copilot was initially prototyped by Yunzhi Chen as part of the ReEDS team. Future development is expected to involve contributions from the broader ReEDS developer and user community.

---

## License

This tool is part of the ReEDS repository and follows the same license terms.
