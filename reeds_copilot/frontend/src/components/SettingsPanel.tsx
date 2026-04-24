import { useEffect, useState, type FormEvent } from "react";
import { healthAPI, updateApiKeyAPI, type HealthResponse } from "../lib/api";

const PROVIDERS: {
  value: string;
  label: string;
  placeholder: string;
  models: { value: string; label: string }[];
}[] = [
  {
    value: "anthropic",
    label: "Anthropic (Claude)",
    placeholder: "sk-ant-api03-…",
    models: [
      { value: "claude-opus-4-1", label: "Claude Opus 4.1" },
      { value: "claude-sonnet-4-1", label: "Claude Sonnet 4.1" },
      { value: "claude-sonnet-4-0", label: "Claude Sonnet 4" },
      { value: "claude-haiku-4", label: "Claude Haiku 4" },
      { value: "claude-3-5-sonnet-20241022", label: "Claude 3.5 Sonnet" },
    ],
  },
  {
    value: "openai",
    label: "OpenAI (GPT)",
    placeholder: "sk-…",
    models: [
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "gpt-4o-mini", label: "GPT-4o Mini" },
      { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
      { value: "o3", label: "o3" },
      { value: "o4-mini", label: "o4-mini" },
    ],
  },
  {
    value: "google",
    label: "Google (Gemini)",
    placeholder: "AIza…",
    models: [
      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
      { value: "gemini-3-flash-preview", label: "Gemini 3 Flash (Preview)" },
      { value: "gemini-3-pro-preview", label: "Gemini 3 Pro (Preview)" },
      { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
    ],
  },
];

export default function SettingsPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  function refreshHealth() {
    healthAPI()
      .then((h) => {
        setHealth(h);
        setProvider(h.llm_provider);
        setModel(h.model_name);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => { refreshHealth(); }, []);

  const currentProvider = PROVIDERS.find((p) => p.value === provider) ?? PROVIDERS[0];

  async function handleSaveKey(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim() || saving) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await updateApiKeyAPI(apiKey.trim(), provider, model);
      setSaveMsg({ ok: res.success, text: res.message });
      if (res.success) {
        setApiKey("");
        refreshHealth();
      }
    } catch (err: unknown) {
      setSaveMsg({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-panel">
      <h2>Settings</h2>

      {/* ── Provider + API key input ─────────────── */}
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ marginBottom: 8 }}>LLM Provider &amp; API Key</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 10 }}>
          Choose a provider and paste your API key. It takes effect immediately
           — no restart needed.
        </p>

        {/* Provider selector */}
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: 4, display: "block" }}>
            Provider
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            {PROVIDERS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => {
                  setProvider(p.value);
                  setModel(p.models[0].value);
                  setSaveMsg(null);
                }}
                style={{
                  padding: "6px 16px",
                  border: provider === p.value ? "2px solid var(--accent)" : "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  background: provider === p.value ? "var(--accent)" : "transparent",
                  color: provider === p.value ? "#fff" : "var(--text-muted)",
                  cursor: "pointer",
                  fontSize: "0.84rem",
                  fontWeight: provider === p.value ? 600 : 400,
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Model selector */}
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: 4, display: "block" }}>
            Model
          </label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            style={{
              padding: "7px 12px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "var(--bg)",
              color: "var(--text)",
              fontSize: "0.85rem",
              minWidth: 240,
            }}
          >
            {currentProvider.models.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>

        {/* Key input */}
        <form onSubmit={handleSaveKey} style={{ display: "flex", gap: 8, maxWidth: 560 }}>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={currentProvider.placeholder}
            style={{
              flex: 1,
              padding: "8px 12px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "var(--bg)",
              color: "var(--text)",
              fontSize: "0.88rem",
            }}
          />
          <button
            type="submit"
            disabled={saving || !apiKey.trim()}
            style={{
              padding: "8px 18px",
              background: "var(--accent)",
              border: "none",
              borderRadius: "var(--radius)",
              color: "#fff",
              cursor: "pointer",
              fontWeight: 600,
              fontSize: "0.85rem",
              opacity: saving || !apiKey.trim() ? 0.5 : 1,
            }}
          >
            {saving ? "Saving…" : "Save Key"}
          </button>
        </form>
        {saveMsg && (
          <div style={{ marginTop: 8, fontSize: "0.85rem", color: saveMsg.ok ? "var(--success)" : "var(--danger)" }}>
            {saveMsg.text}
          </div>
        )}
      </div>

      {error && <div className="error-banner" style={{ marginBottom: 14 }}>{error}</div>}

      {health && (
        <div className="status">
          <div>
            Backend:{" "}
            <span className={health.status === "ok" ? "ok" : "warn"}>
              {health.status}
            </span>
          </div>
          <div>
            Repo root: <code>{health.repo_root}</code>{" "}
            {health.repo_exists ? (
              <span className="ok">✓ exists</span>
            ) : (
              <span className="warn">✗ not found</span>
            )}
          </div>
          <div>
            LLM provider: <strong>{health.llm_provider}</strong>
          </div>
          <div>
            Model: <strong>{health.model_name}</strong>
          </div>
          <div>
            API key:{" "}
            {health.api_key_set ? (
              <span className="ok">✓ set</span>
            ) : (
              <span className="warn">✗ not set (mock mode)</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
