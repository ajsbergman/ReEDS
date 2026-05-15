import { useRef, useEffect, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { chatAPI, rawFileURL, switchProviderAPI, healthAPI, type ChatResponse, type SourceSnippet, type ChatAttachment } from "../lib/api";
import { PROVIDERS } from "../lib/providers";

export interface Message {
  role: "user" | "assistant";
  content: string;
  attachments?: ChatAttachment[];
}

interface Props {
  mode: string;
  selectedPath: string | null;
  onSources: (sources: SourceSnippet[]) => void;
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  onNavigate?: (tab: string) => void;
  onSelectFile?: (path: string, line?: number) => void;
}

const RUN_KEYWORDS = /\b(run reeds|launch.*run|start.*run|execute.*model|run.*model|runbatch|cases[_ ]?csv|how.*run|can i run)\b/i;

// Heuristic: does this string look like a path to a repo file?
// Matches things like "docs/source/model_documentation.md", "b_inputs.gms",
// "inputs/tech-subset-table.csv", optionally with #L42 line anchors.
const FILE_PATH_RE = /^([\w./\-]+\.(?:md|rst|txt|gms|py|jl|r|sh|bat|csv|json|ya?ml|toml|cfg|ini|opt))(?:#L\d+(?:-L\d+)?)?$/i;

function stripLineAnchor(p: string): string {
  const i = p.indexOf("#");
  return i >= 0 ? p.slice(0, i) : p;
}

function parseLineAnchor(p: string): number | undefined {
  const m = /#L(\d+)/.exec(p);
  return m ? parseInt(m[1], 10) : undefined;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function AttachmentBlock({ att }: { att: ChatAttachment; onSelectFile?: (p: string) => void }) {
  if (att.type === "image" && att.path) {
    return (
      <div className="chat-attachment chat-att-image">
        <img
          src={rawFileURL(att.path)}
          alt={att.caption || att.path}
          style={{ maxWidth: "100%", borderRadius: "var(--radius)", marginTop: 6, cursor: "pointer" }}
          onClick={() => window.open(rawFileURL(att.path!), "_blank")}
        />
        {att.caption && (
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: 2 }}>{att.caption}</div>
        )}
      </div>
    );
  }

  if (att.type === "csv_table" && att.headers && att.rows) {
    return (
      <div className="chat-attachment chat-att-table" style={{ overflowX: "auto", marginTop: 8 }}>
        {att.title && (
          <div style={{ fontSize: "0.78rem", fontWeight: 600, marginBottom: 4 }}>{att.title}</div>
        )}
        <table style={{
          width: "100%", fontSize: "0.72rem", borderCollapse: "collapse",
          fontFamily: "var(--font-mono)",
        }}>
          <thead>
            <tr>
              {att.headers.map((h, i) => (
                <th key={i} style={{
                  padding: "3px 6px", borderBottom: "1px solid var(--border)",
                  textAlign: "left", whiteSpace: "nowrap", color: "var(--text-muted)",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {att.rows.map((row, ri) => (
              <tr key={ri}>
                {(row as unknown[]).map((cell, ci) => (
                  <td key={ci} style={{
                    padding: "2px 6px", borderBottom: "1px solid var(--border)",
                    whiteSpace: "nowrap", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis",
                  }}>{String(cell ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (att.type === "file_list" && att.files) {
    const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]);
    return (
      <div className="chat-attachment chat-att-files" style={{ marginTop: 8 }}>
        <div style={{
          display: "flex", flexDirection: "column", gap: 2,
          maxHeight: 200, overflowY: "auto", fontSize: "0.75rem",
          fontFamily: "var(--font-mono)",
        }}>
          {att.files.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {IMAGE_EXTS.has(f.suffix) ? "🖼️" : f.suffix === ".csv" ? "📊" : "📄"} {f.name}
              </span>
              <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>{formatSize(f.size)}</span>
              {IMAGE_EXTS.has(f.suffix) && (
                <a href={rawFileURL(f.path)} target="_blank" rel="noopener noreferrer"
                  style={{ color: "var(--accent)", fontSize: "0.7rem", flexShrink: 0 }}>View</a>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (att.type === "run_card") {
    return (
      <div className="chat-attachment chat-att-run" style={{
        marginTop: 8, padding: "8px 12px", borderRadius: "var(--radius)",
        background: "var(--bg-elevated)", border: "1px solid var(--border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%",
            background: att.status === "completed" ? "#4ade80" : att.status === "failed" ? "#f87171" : "#fbbf24",
          }} />
          <strong style={{ fontSize: "0.82rem" }}>{att.run_name}</strong>
          <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>{att.status}</span>
        </div>
      </div>
    );
  }

  return null;
}

export default function ChatPanel({ mode, selectedPath, onSources, messages, setMessages, onNavigate, onSelectFile }: Props) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Provider switcher state
  const [activeProvider, setActiveProvider] = useState("");
  const [storedKeys, setStoredKeys] = useState<string[]>([]);
  const [switchingProvider, setSwitchingProvider] = useState(false);

  useEffect(() => {
    healthAPI().then((h) => {
      setActiveProvider(h.llm_provider);
      setStoredKeys(h.stored_keys ?? []);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res: ChatResponse = await chatAPI(text, mode, selectedPath);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer,
          attachments: res.attachments?.length ? res.attachments : undefined,
        },
      ]);
      onSources(res.sources);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleSwitchInChat(providerValue: string) {
    if (providerValue === activeProvider || switchingProvider) return;
    const prov = PROVIDERS.find((p) => p.value === providerValue);
    if (!prov) return;
    setSwitchingProvider(true);
    try {
      // Pass empty model so backend uses the per-provider remembered model
      const res = await switchProviderAPI(providerValue, "");
      if (res.success) {
        setActiveProvider(providerValue);
      } else {
        setError(res.message);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSwitchingProvider(false);
    }
  }

  const availableProviders = PROVIDERS.filter((p) => storedKeys.includes(p.value));
  const activeProviderDef = PROVIDERS.find((p) => p.value === activeProvider);

  return (
    <div className="center-panel">
      {error && <div className="error-banner">{error}</div>}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div style={{ color: "var(--text-muted)", margin: "auto" }}>
            Ask anything about the ReEDS repository.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            {m.role === "assistant" ? (
              <>
                <ReactMarkdown
                  components={{
                    // Markdown links — if the href looks like a repo file, open it in the right panel
                    a({ href, children, ...rest }) {
                      const target = (href || "").trim();
                      if (onSelectFile && target && FILE_PATH_RE.test(target)) {
                        const line = parseLineAnchor(target);
                        return (
                          <a
                            href="#"
                            onClick={(e) => { e.preventDefault(); onSelectFile(stripLineAnchor(target), line); }}
                            style={{ color: "var(--accent)", textDecoration: "underline", cursor: "pointer" }}
                          >
                            {children}
                          </a>
                        );
                      }
                      return <a href={target} target="_blank" rel="noreferrer" {...rest}>{children}</a>;
                    },
                    // Inline code — if the text looks like a repo file path, make it clickable too
                    code({ children, className, ...rest }) {
                      const text = String(children ?? "").trim();
                      const isInline = !className;
                      if (isInline && onSelectFile && FILE_PATH_RE.test(text)) {
                        const line = parseLineAnchor(text);
                        return (
                          <code
                            onClick={() => onSelectFile(stripLineAnchor(text), line)}
                            style={{ cursor: "pointer", color: "var(--accent)", textDecoration: "underline dotted" }}
                            title="Open in viewer"
                          >
                            {children}
                          </code>
                        );
                      }
                      return <code className={className} {...rest}>{children}</code>;
                    },
                  }}
                >{m.content}</ReactMarkdown>
                {m.attachments?.map((att, j) => (
                  <AttachmentBlock key={j} att={att} onSelectFile={onNavigate ? undefined : undefined} />
                ))}
                {RUN_KEYWORDS.test(m.content) && onNavigate && (
                  <button
                    className="chat-action-link"
                    onClick={() => onNavigate("runs")}
                  >
                    🚀 Go to Run ReEDS
                  </button>
                )}
              </>
            ) : (
              m.content
            )}
          </div>
        ))}
        {loading && <div className="loading">Thinking…</div>}
        <div ref={bottomRef} />
      </div>
      <form className="chat-input-bar" onSubmit={handleSubmit}>
        {/* Provider switcher – only shown when 2+ providers have keys */}
        {availableProviders.length >= 2 && (
          <select
            value={activeProvider}
            onChange={(e) => handleSwitchInChat(e.target.value)}
            disabled={switchingProvider || loading}
            title="Switch LLM provider"
            className="chat-provider-switcher"
          >
            {availableProviders.map((p) => (
              <option key={p.value} value={p.value}>
                {p.icon} {p.label}
              </option>
            ))}
          </select>
        )}
        {/* Show active provider badge if only 1 key */}
        {availableProviders.length === 1 && activeProviderDef && (
          <span className="chat-provider-badge" title="Active LLM provider">
            {activeProviderDef.icon}
          </span>
        )}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ReEDS (${mode} mode)…`}
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
