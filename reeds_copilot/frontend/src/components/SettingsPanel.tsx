import { useEffect, useState, type FormEvent } from "react";
import {
  healthAPI,
  updateApiKeyAPI,
  switchProviderAPI,
  deleteApiKeyAPI,
  shutdownPreviewAPI,
  shutdownBackendAPI,
  type HealthResponse,
} from "../lib/api";
import { PROVIDERS } from "../lib/providers";

export default function SettingsPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Shutdown
  const [shutdownState, setShutdownState] = useState<
    | { phase: "idle" }
    | { phase: "checking" }
    | { phase: "confirm"; activeRuns: { id: string; batch_name: string; status: string }[]; force: boolean }
    | { phase: "shutting" }
    | { phase: "done"; message: string }
    | { phase: "error"; message: string }
  >({ phase: "idle" });

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
  const storedKeys = health?.stored_keys ?? [];

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

  async function handleSwitchProvider(providerValue: string) {
    const prov = PROVIDERS.find((p) => p.value === providerValue);
    if (!prov) return;
    setSwitching(true);
    setSaveMsg(null);
    try {
      // Pass empty model so backend uses the per-provider remembered model
      const res = await switchProviderAPI(providerValue, "");
      setSaveMsg({ ok: res.success, text: res.message });
      if (res.success) refreshHealth();
    } catch (err: unknown) {
      setSaveMsg({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setSwitching(false);
    }
  }

  async function handleDeleteKey(providerValue: string) {
    try {
      await deleteApiKeyAPI(providerValue);
      refreshHealth();
    } catch (e) {
      setSaveMsg({
        ok: false,
        text: e instanceof Error ? e.message : `Failed to delete ${providerValue} key.`,
      });
    }
  }

  async function handleShutdownClick() {
    setShutdownState({ phase: "checking" });
    try {
      const preview = await shutdownPreviewAPI();
      if (preview.safe_to_shutdown) {
        // Nothing running locally – just confirm once
        setShutdownState({ phase: "confirm", activeRuns: [], force: false });
      } else {
        setShutdownState({
          phase: "confirm",
          activeRuns: preview.active_local_runs,
          force: true,
        });
      }
    } catch (e) {
      setShutdownState({ phase: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  async function handleShutdownConfirm(force: boolean) {
    setShutdownState({ phase: "shutting" });
    try {
      const res = await shutdownBackendAPI(force);
      if (!res.shutdown) {
        // Backend refused (active runs without force)
        setShutdownState({
          phase: "error",
          message: res.message || "Shutdown refused.",
        });
        return;
      }
      // Backend said it's exiting — verify by polling /health until it stops responding
      const cancelled = res.cancelled_local_runs ?? 0;
      const stoppedConfirmed = await waitForBackendDown(8000);
      if (stoppedConfirmed) {
        setShutdownState({
          phase: "done",
          message:
            (cancelled ? `Cancelled ${cancelled} local run(s). ` : "") +
            "Backend stopped. You can close this browser tab.",
        });
        // Notify App to take over with a dedicated stopped screen so the
        // WelcomeScreen never reappears as a side-effect of /health failing.
        window.dispatchEvent(new CustomEvent("reeds-backend-shutdown"));
      } else {
        setShutdownState({
          phase: "error",
          message:
            "Backend reported shutdown but is still responding after 8s. " +
            "Close the launcher windows manually (right-click the taskbar icon → Close window).",
        });
      }
    } catch (e) {
      // Network error usually means the backend already exited (good!)
      const stoppedConfirmed = await waitForBackendDown(4000);
      if (stoppedConfirmed) {
        setShutdownState({
          phase: "done",
          message: "Backend stopped. You can close this browser tab.",
        });
        window.dispatchEvent(new CustomEvent("reeds-backend-shutdown"));
      } else {
        setShutdownState({
          phase: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      }
    }
  }

  /** Poll /health until it stops responding (or returns 5xx) or timeout. */
  async function waitForBackendDown(timeoutMs: number): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const r = await fetch("/health", { method: "GET", cache: "no-store" });
        // Backend died → Vite proxy returns 502/504. Treat any non-2xx as down.
        if (!r.ok) return true;
        // Sanity check: ensure body is the expected JSON
        try {
          const j = await r.json();
          if (!j || typeof j !== "object" || j.status !== "ok") return true;
        } catch {
          return true; // non-JSON body = not the real backend
        }
        await new Promise((res) => setTimeout(res, 400));
      } catch {
        return true; // network error = backend down
      }
    }
    return false;
  }

  return (
    <div className="settings-panel">
      <h2>Settings</h2>

      {/* ── Provider + API key input ─────────────── */}
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ marginBottom: 8 }}>LLM Provider &amp; API Key</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 10 }}>
          Save API keys for multiple providers. Keys are stored locally in <code>.user/keys.json</code> (git-ignored).
          Switch between providers any time — even mid-conversation.
        </p>

        {/* ── Saved keys overview ── */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: 6, display: "block" }}>
            Saved Keys
          </label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {PROVIDERS.map((p) => {
              const hasSaved = storedKeys.includes(p.value);
              const isActive = health?.llm_provider === p.value;
              return (
                <div
                  key={p.value}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 12px",
                    borderRadius: "var(--radius)",
                    border: isActive
                      ? "2px solid var(--accent)"
                      : "1px solid var(--border)",
                    background: isActive ? "rgba(99,102,241,0.06)" : "transparent",
                  }}
                >
                  <span style={{ fontSize: "1rem" }}>{p.icon}</span>
                  <span style={{ flex: 1, fontSize: "0.85rem", fontWeight: isActive ? 600 : 400 }}>
                    {p.label}
                  </span>
                  {hasSaved ? (
                    <>
                      <span style={{
                        fontSize: "0.72rem",
                        padding: "2px 8px",
                        borderRadius: 99,
                        background: "rgba(74,222,128,0.12)",
                        color: "var(--success)",
                        fontWeight: 600,
                      }}>
                        ✓ Key saved
                      </span>
                      {!isActive && (
                        <button
                          type="button"
                          disabled={switching}
                          onClick={() => handleSwitchProvider(p.value)}
                          style={{
                            padding: "3px 10px",
                            fontSize: "0.76rem",
                            border: "1px solid var(--accent)",
                            borderRadius: "var(--radius)",
                            background: "transparent",
                            color: "var(--accent)",
                            cursor: "pointer",
                          }}
                        >
                          Use
                        </button>
                      )}
                      {isActive && (
                        <span style={{
                          fontSize: "0.72rem",
                          padding: "2px 8px",
                          borderRadius: 99,
                          background: "var(--accent)",
                          color: "#fff",
                          fontWeight: 600,
                        }}>
                          Active
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDeleteKey(p.value)}
                        title="Remove saved key"
                        style={{
                          padding: "2px 6px",
                          fontSize: "0.72rem",
                          border: "none",
                          borderRadius: "var(--radius)",
                          background: "transparent",
                          color: "var(--text-muted)",
                          cursor: "pointer",
                          opacity: 0.6,
                        }}
                      >
                        ✕
                      </button>
                    </>
                  ) : (
                    <span style={{
                      fontSize: "0.72rem",
                      color: "var(--text-muted)",
                    }}>
                      No key
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Add / update a key ── */}
        <div style={{
          padding: "12px 16px",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          background: "var(--bg-elevated)",
          marginBottom: 10,
        }}>
          <label style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginBottom: 6, display: "block" }}>
            Add or update a key
          </label>

          {/* Provider selector */}
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
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
                  padding: "5px 14px",
                  border: provider === p.value ? "2px solid var(--accent)" : "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  background: provider === p.value ? "var(--accent)" : "transparent",
                  color: provider === p.value ? "#fff" : "var(--text-muted)",
                  cursor: "pointer",
                  fontSize: "0.8rem",
                  fontWeight: provider === p.value ? 600 : 400,
                }}
              >
                {p.icon} {p.label}
              </button>
            ))}
          </div>

          {/* Model selector */}
          <div style={{ marginBottom: 8 }}>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{
                padding: "6px 10px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                background: "var(--bg)",
                color: "var(--text)",
                fontSize: "0.84rem",
                minWidth: 220,
              }}
            >
              {currentProvider.models.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* Key input + save */}
          <form onSubmit={handleSaveKey} style={{ display: "flex", gap: 8 }}>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={currentProvider.placeholder}
              style={{
                flex: 1,
                padding: "7px 12px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                background: "var(--bg)",
                color: "var(--text)",
                fontSize: "0.86rem",
              }}
            />
            <button
              type="submit"
              disabled={saving || !apiKey.trim()}
              style={{
                padding: "7px 16px",
                background: "var(--accent)",
                border: "none",
                borderRadius: "var(--radius)",
                color: "#fff",
                cursor: "pointer",
                fontWeight: 600,
                fontSize: "0.84rem",
                opacity: saving || !apiKey.trim() ? 0.5 : 1,
              }}
            >
              {saving ? "Saving…" : storedKeys.includes(provider) ? "Update Key" : "Save Key"}
            </button>
          </form>
          {saveMsg && (
            <div style={{ marginTop: 6, fontSize: "0.83rem", color: saveMsg.ok ? "var(--success)" : "var(--danger)" }}>
              {saveMsg.text}
            </div>
          )}
        </div>

        {/* ── How to get your API key ── */}
        <div className="settings-api-guide">
          <details>
            <summary className="settings-api-guide-toggle">
              🔑 How to get your API key
            </summary>
            <div className="settings-api-guide-body">

              {/* NLR users */}
              <div className="settings-api-card nlr">
                <div className="settings-api-card-header">
                  <span>🏢</span>
                  <strong>NLR Staff (LiteLLM)</strong>
                </div>
                <p>
                  NLR provides LLM access through its internal LiteLLM proxy.
                  Usage is billed to a <strong>project charge code</strong> that you provide when requesting access.
                </p>
                <ol>
                  <li>Go to <a href="https://cloud.nlr.gov/" target="_blank" rel="noopener noreferrer">cloud.nlr.gov</a></li>
                  <li>Navigate to <strong>Self Service → AI Model Request</strong></li>
                  <li>Submit a request (you'll need a <strong>project charge code</strong> to bill usage to)</li>
                  <li>Once approved, you'll receive an API key via email</li>
                  <li>Select <strong>"NLR LiteLLM"</strong> above and paste your key</li>
                </ol>
                <p className="settings-api-note">
                  ✅ Requests are audited but <strong>not</strong> exposed publicly and <strong>not</strong> used for model training.
                  VPN access required when offsite.
                </p>
              </div>

              {/* External providers */}
              <div className="settings-api-card">
                <div className="settings-api-card-header">
                  <span>🟣</span>
                  <strong>Anthropic (Claude)</strong>
                </div>
                <ol>
                  <li>Go to <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">console.anthropic.com</a></li>
                  <li>Create an account and add billing ($5 minimum)</li>
                  <li>Click <strong>"Create Key"</strong> and copy the key (starts with <code>sk-ant-</code>)</li>
                </ol>
                <p className="settings-api-note">💰 ~$3–15 / million tokens. Best tool-use quality.</p>
              </div>

              <div className="settings-api-card">
                <div className="settings-api-card-header">
                  <span>🟢</span>
                  <strong>OpenAI (GPT)</strong>
                </div>
                <ol>
                  <li>Go to <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">platform.openai.com/api-keys</a></li>
                  <li>Sign up and add billing ($5 minimum)</li>
                  <li>Click <strong>"Create new secret key"</strong> and copy it (starts with <code>sk-</code>)</li>
                </ol>
                <p className="settings-api-note">💰 ~$2.50–10 / million tokens. Widely used, good all-around.</p>
              </div>

              <div className="settings-api-card">
                <div className="settings-api-card-header">
                  <span>🔵</span>
                  <strong>Google (Gemini)</strong>
                </div>
                <ol>
                  <li>Go to <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer">aistudio.google.com</a></li>
                  <li>Sign in with your Google account</li>
                  <li>Click <strong>"Create API key"</strong> and copy it (starts with <code>AIza</code>)</li>
                </ol>
                <p className="settings-api-note">💰 Free tier available! Paid starts at ~$0.15 / million tokens. Fastest option.</p>
              </div>

              <p className="settings-api-cost-note">
                💡 <strong>Typical cost:</strong> A chat message uses ~2,000–5,000 tokens.
                Even heavy daily use rarely exceeds <strong>$1/day</strong> on any provider.
                Google Gemini's free tier handles most casual use at zero cost.
              </p>
            </div>
          </details>
        </div>
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

      {/* ── Shutdown ─────────────────────────────────────────── */}
      <div style={{ marginTop: 28, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
        <h3 style={{ marginBottom: 8 }}>Shut down ReEDS Copilot</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.83rem", marginBottom: 10 }}>
          Stops the backend (port 8001) and frees both terminals. HPC runs already submitted to a
          cluster will keep running on the cluster — only LOCAL runs are affected. After shutdown,
          re-launch with <code>launch.bat</code>.
        </p>

        {shutdownState.phase === "idle" && (
          <button
            type="button"
            onClick={handleShutdownClick}
            style={{
              padding: "8px 16px",
              border: "1px solid var(--danger, #e05252)",
              borderRadius: "var(--radius)",
              background: "transparent",
              color: "var(--danger, #e05252)",
              cursor: "pointer",
              fontSize: "0.86rem",
              fontWeight: 600,
            }}
          >
            🛑 Shut Down Backend
          </button>
        )}

        {shutdownState.phase === "checking" && (
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Checking active runs…</div>
        )}

        {shutdownState.phase === "confirm" && (
          <div style={{
            padding: 12,
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: "var(--bg-elevated)",
          }}>
            {shutdownState.activeRuns.length === 0 ? (
              <p style={{ margin: "0 0 10px 0", fontSize: "0.86rem" }}>
                No active local runs. Confirm shutdown?
              </p>
            ) : (
              <>
                <p style={{ margin: "0 0 6px 0", fontSize: "0.86rem", color: "var(--danger, #e05252)" }}>
                  ⚠️ {shutdownState.activeRuns.length} local run(s) still in progress:
                </p>
                <ul style={{ margin: "0 0 10px 18px", fontSize: "0.82rem", color: "var(--text-muted)" }}>
                  {shutdownState.activeRuns.slice(0, 5).map((r) => (
                    <li key={r.id}>
                      <strong>{r.batch_name || r.id.slice(0, 8)}</strong> — {r.status}
                    </li>
                  ))}
                  {shutdownState.activeRuns.length > 5 && (
                    <li>… and {shutdownState.activeRuns.length - 5} more</li>
                  )}
                </ul>
                <p style={{ margin: "0 0 10px 0", fontSize: "0.82rem" }}>
                  Shutting down will <strong>terminate these runs</strong>. Continue?
                </p>
              </>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                onClick={() => handleShutdownConfirm(shutdownState.force)}
                style={{
                  padding: "6px 14px",
                  background: "var(--danger, #e05252)",
                  color: "#fff",
                  border: "none",
                  borderRadius: "var(--radius)",
                  cursor: "pointer",
                  fontSize: "0.84rem",
                  fontWeight: 600,
                }}
              >
                {shutdownState.activeRuns.length > 0 ? "Force Shutdown" : "Confirm Shutdown"}
              </button>
              <button
                type="button"
                onClick={() => setShutdownState({ phase: "idle" })}
                style={{
                  padding: "6px 14px",
                  background: "transparent",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  cursor: "pointer",
                  fontSize: "0.84rem",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {shutdownState.phase === "shutting" && (
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Shutting down…</div>
        )}

        {shutdownState.phase === "done" && (
          <div style={{
            padding: 10,
            borderRadius: "var(--radius)",
            background: "rgba(74,222,128,0.10)",
            color: "var(--success)",
            fontSize: "0.85rem",
          }}>
            ✓ {shutdownState.message}
          </div>
        )}

        {shutdownState.phase === "error" && (
          <div style={{
            padding: 10,
            borderRadius: "var(--radius)",
            background: "rgba(224,82,82,0.10)",
            color: "var(--danger, #e05252)",
            fontSize: "0.85rem",
          }}>
            ✗ {shutdownState.message}
          </div>
        )}
      </div>
    </div>
  );
}
