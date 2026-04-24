import { useState, type FormEvent } from "react";
import { updateApiKeyAPI, type HealthResponse } from "../lib/api";

const PROVIDERS = [
  {
    value: "anthropic",
    label: "Anthropic",
    icon: "🟣",
    desc: "Claude models",
    placeholder: "sk-ant-api03-…",
    models: [
      { value: "claude-opus-4-1", label: "Claude Opus 4.1" },
      { value: "claude-sonnet-4-1", label: "Claude Sonnet 4.1" },
      { value: "claude-sonnet-4-0", label: "Claude Sonnet 4" },
    ],
    helpUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    value: "openai",
    label: "OpenAI",
    icon: "🟢",
    desc: "GPT models",
    placeholder: "sk-…",
    models: [
      { value: "gpt-4o", label: "GPT-4o" },
      { value: "gpt-4o-mini", label: "GPT-4o Mini" },
      { value: "o3", label: "o3" },
    ],
    helpUrl: "https://platform.openai.com/api-keys",
  },
  {
    value: "google",
    label: "Google",
    icon: "🔵",
    desc: "Gemini models",
    placeholder: "AIza…",
    models: [
      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
      { value: "gemini-3-flash-preview", label: "Gemini 3 Flash (Preview)" },
    ],
    helpUrl: "https://aistudio.google.com/app/apikey",
  },
];

interface Props {
  health: HealthResponse | null;
  onComplete: () => void;
}

export default function WelcomeScreen({ health, onComplete }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [provider, setProvider] = useState(PROVIDERS[2]); // default Google
  const [model, setModel] = useState(PROVIDERS[2].models[0].value);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function selectProvider(p: typeof PROVIDERS[number]) {
    setProvider(p);
    setModel(p.models[0].value);
    setStep(2);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await updateApiKeyAPI(apiKey.trim(), provider.value, model);
      if (res.success) {
        setStep(3);
      } else {
        setError(res.message);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      height: "100vh",
      background: "var(--bg)",
      padding: 24,
    }}>
      <div style={{
        maxWidth: 520,
        width: "100%",
        background: "var(--bg-surface)",
        borderRadius: 12,
        border: "1px solid var(--border)",
        padding: "36px 32px",
      }}>
        {/* Header */}
        <h1 style={{ fontSize: "1.6rem", color: "var(--accent)", marginBottom: 4 }}>
          ReEDS-Copilot
        </h1>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginBottom: 28 }}>
          AI assistant for the ReEDS repository. Let's get you set up.
        </p>

        {/* Step indicators */}
        <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
          {[1, 2, 3].map((s) => (
            <div key={s} style={{
              flex: 1, height: 4, borderRadius: 2,
              background: s <= step ? "var(--accent)" : "var(--border)",
              transition: "background 0.3s",
            }} />
          ))}
        </div>

        {/* Step 1: Choose provider */}
        {step === 1 && (
          <div>
            <h3 style={{ marginBottom: 14, fontSize: "1rem" }}>Choose your LLM provider</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => selectProvider(p)}
                  style={{
                    display: "flex", alignItems: "center", gap: 14,
                    padding: "14px 18px",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    background: "var(--bg)",
                    color: "var(--text)",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "border-color 0.15s, background 0.15s",
                  }}
                  onMouseOver={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
                  onMouseOut={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                >
                  <span style={{ fontSize: "1.5rem" }}>{p.icon}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>{p.label}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{p.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Enter key + model */}
        {step === 2 && (
          <div>
            <h3 style={{ marginBottom: 6, fontSize: "1rem" }}>
              {provider.icon} {provider.label} — enter your API key
            </h3>
            <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: 16 }}>
              Get a key from{" "}
              <a href={provider.helpUrl} target="_blank" rel="noreferrer"
                style={{ color: "var(--accent)" }}>
                {provider.helpUrl.replace("https://", "")}
              </a>
            </p>

            {/* Model picker */}
            <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{
                width: "100%", padding: "8px 12px", marginBottom: 14,
                border: "1px solid var(--border)", borderRadius: 6,
                background: "var(--bg)", color: "var(--text)", fontSize: "0.88rem",
              }}
            >
              {provider.models.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>

            {/* Key input */}
            <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
              API Key
            </label>
            <form onSubmit={handleSave}>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={provider.placeholder}
                autoFocus
                style={{
                  width: "100%", padding: "10px 14px", marginBottom: 14,
                  border: "1px solid var(--border)", borderRadius: 6,
                  background: "var(--bg)", color: "var(--text)", fontSize: "0.9rem",
                }}
              />
              {error && (
                <div style={{ color: "var(--danger)", fontSize: "0.84rem", marginBottom: 10 }}>
                  {error}
                </div>
              )}
              <div style={{ display: "flex", gap: 10 }}>
                <button type="button" onClick={() => setStep(1)} style={{
                  padding: "10px 20px", border: "1px solid var(--border)",
                  borderRadius: 6, background: "transparent",
                  color: "var(--text-muted)", cursor: "pointer", fontSize: "0.88rem",
                }}>
                  Back
                </button>
                <button type="submit" disabled={saving || !apiKey.trim()} style={{
                  flex: 1, padding: "10px 20px", border: "none",
                  borderRadius: 6, background: "var(--accent)",
                  color: "#fff", cursor: "pointer", fontWeight: 600, fontSize: "0.9rem",
                  opacity: saving || !apiKey.trim() ? 0.5 : 1,
                }}>
                  {saving ? "Connecting…" : "Connect & Start"}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Step 3: Success */}
        {step === 3 && (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "3rem", marginBottom: 12 }}>✅</div>
            <h3 style={{ marginBottom: 8, fontSize: "1.1rem" }}>You're all set!</h3>
            <p style={{ color: "var(--text-muted)", fontSize: "0.88rem", marginBottom: 24 }}>
              Connected to {provider.label} ({provider.models.find(m => m.value === model)?.label}).
              <br />Your key is stored in memory only — it won't leave your machine.
            </p>
            <button onClick={onComplete} style={{
              padding: "12px 36px", border: "none", borderRadius: 6,
              background: "var(--accent)", color: "#fff", cursor: "pointer",
              fontWeight: 600, fontSize: "1rem",
            }}>
              Start Chatting →
            </button>
          </div>
        )}

        {/* Skip link */}
        {step !== 3 && (
          <div style={{ textAlign: "center", marginTop: 20 }}>
            <button onClick={onComplete} style={{
              background: "none", border: "none", color: "var(--text-muted)",
              cursor: "pointer", fontSize: "0.8rem", textDecoration: "underline",
            }}>
              Skip — I'll configure later in Settings
            </button>
          </div>
        )}

        {/* Connection status */}
        {health && (
          <div style={{
            marginTop: 20, padding: "8px 12px", borderRadius: 6,
            background: "var(--bg)", fontSize: "0.78rem", color: "var(--text-muted)",
          }}>
            Backend: {health.status === "ok" ? "✓ connected" : "✗ not connected"}
            {" · "}Repo: {health.repo_exists ? "✓ found" : "✗ not found"}
          </div>
        )}
      </div>
    </div>
  );
}
