import { useEffect, useState } from "react";
import {
  listSessionsAPI,
  createSessionAPI,
  deleteSessionAPI,
  type SessionSummary,
} from "../lib/api";

interface Props {
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  refreshKey: number; // increment to trigger refresh
}

export default function ChatHistory({
  activeSessionId,
  onSelectSession,
  onNewChat,
  refreshKey,
}: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    listSessionsAPI()
      .then(setSessions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [refreshKey]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Delete this chat?")) return;
    await deleteSessionAPI(id).catch(() => {});
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSessionId === id) onNewChat();
  }

  function formatTime(ts: number): string {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  return (
    <div className="chat-history">
      <button className="new-chat-btn" onClick={onNewChat}>
        + New Chat
      </button>

      {loading && <div className="loading" style={{ padding: "8px 0" }}>Loading…</div>}

      <div className="session-list">
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === activeSessionId ? "active" : ""}`}
            onClick={() => onSelectSession(s.id)}
            title={s.title}
          >
            <div className="session-title">{s.title}</div>
            <div className="session-meta">
              <span>{s.message_count} msgs</span>
              <span>{formatTime(s.updated_at)}</span>
            </div>
            <button
              className="session-delete"
              onClick={(e) => handleDelete(e, s.id)}
              title="Delete"
            >
              ✕
            </button>
          </div>
        ))}
        {!loading && sessions.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: "0.8rem", padding: "8px 4px" }}>
            No chat history yet.
          </div>
        )}
      </div>
    </div>
  );
}
