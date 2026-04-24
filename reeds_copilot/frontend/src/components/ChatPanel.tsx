import { useState, useRef, useEffect, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { chatAPI, type ChatResponse, type SourceSnippet } from "../lib/api";

interface Props {
  mode: string;
  selectedPath: string | null;
  onSources: (sources: SourceSnippet[]) => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPanel({ mode, selectedPath, onSources }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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
        { role: "assistant", content: res.answer },
      ]);
      onSources(res.sources);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

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
              <ReactMarkdown>{m.content}</ReactMarkdown>
            ) : (
              m.content
            )}
          </div>
        ))}
        {loading && <div className="loading">Thinking…</div>}
        <div ref={bottomRef} />
      </div>
      <form className="chat-input-bar" onSubmit={handleSubmit}>
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
