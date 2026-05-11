import { useEffect, useState, useCallback, useRef } from "react";
import ChatPanel, { type Message } from "./components/ChatPanel";
import ChatHistory from "./components/ChatHistory";
import SearchPanel from "./components/SearchPanel";
import FileBrowser from "./components/FileBrowser";
import RightPanel from "./components/RightPanel";
import ResizeHandle from "./components/ResizeHandle";
import SettingsPanel from "./components/SettingsPanel";
import WelcomeScreen from "./components/WelcomeScreen";
import RunPanel from "./components/RunPanel";
import OutputExplorer from "./components/OutputExplorer";
import HpcBrowser from "./components/HpcBrowser";
import {
  healthAPI,
  createSessionAPI,
  getSessionAPI,
  updateSessionAPI,
  type SourceSnippet,
  type HealthResponse,
} from "./lib/api";

type Tab = "chat" | "search" | "runs" | "inputs" | "outputs" | "hpc" | "settings";
type Mode = "general" | "docs" | "code" | "inputs" | "outputs";

const MODES: { value: Mode; label: string }[] = [
  { value: "general", label: "General" },
  { value: "docs", label: "Docs" },
  { value: "code", label: "Code" },
  { value: "inputs", label: "Inputs" },
  { value: "outputs", label: "Outputs" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [mode, setMode] = useState<Mode>("general");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceSnippet[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [showWelcome, setShowWelcome] = useState<boolean | null>(true);

  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resizable panel widths
  const [sidebarWidth, setSidebarWidth] = useState(220);
  const [rightWidth, setRightWidth] = useState(380);

  const handleSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((w) => Math.max(140, Math.min(400, w + delta)));
  }, []);
  const handleRightResize = useCallback((delta: number) => {
    setRightWidth((w) => Math.max(200, Math.min(1200, w - delta)));
  }, []);

  useEffect(() => {
    healthAPI()
      .then((h) => {
        setHealth(h);
      })
      .catch(() => {});
  }, []);

  // NOTE: We intentionally do NOT cancel runs on beforeunload.
  // Runs should survive browser refresh, sleep, and tab close so that
  // long-running GAMS solves are not killed unexpectedly.
  // Users can cancel individual runs from the Run ReEDS panel.

  // Auto-save messages to the active session (debounced)
  const prevMsgCountRef = useRef(0);
  useEffect(() => {
    if (!sessionId || messages.length === 0) return;
    // Only save if messages actually changed
    if (messages.length === prevMsgCountRef.current) return;
    prevMsgCountRef.current = messages.length;

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      // Auto-title from first user message
      const firstUserMsg = messages.find((m) => m.role === "user");
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 60) + (firstUserMsg.content.length > 60 ? "…" : "")
        : "New Chat";
      updateSessionAPI(sessionId, messages, title)
        .then(() => setHistoryRefreshKey((k) => k + 1))
        .catch(() => {});
    }, 500);
  }, [messages, sessionId]);

  // Create a new session when user sends the first message (if no active session)
  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const s = await createSessionAPI("New Chat");
    setSessionId(s.id);
    setHistoryRefreshKey((k) => k + 1);
    return s.id;
  }, [sessionId]);

  // Wrap setMessages to auto-create session on first message
  const handleSetMessages: typeof setMessages = useCallback(
    (action) => {
      setMessages((prev) => {
        const next = typeof action === "function" ? action(prev) : action;
        // If going from 0 to >0 messages and no session, create one
        if (prev.length === 0 && next.length > 0 && !sessionId) {
          createSessionAPI("New Chat").then((s) => {
            setSessionId(s.id);
            setHistoryRefreshKey((k) => k + 1);
          });
        }
        return next;
      });
    },
    [sessionId],
  );

  async function handleSelectSession(id: string) {
    try {
      const s = await getSessionAPI(id);
      setSessionId(s.id);
      setMessages(s.messages as Message[]);
      prevMsgCountRef.current = s.messages.length;
      setTab("chat");
    } catch {
      // session may have been deleted
    }
  }

  function handleNewChat() {
    setSessionId(null);
    setMessages([]);
    prevMsgCountRef.current = 0;
    setSources([]);
    setTab("chat");
  }

  // Show nothing while checking
  if (showWelcome === null) return null;

  // Show welcome/onboarding if no API key
  if (showWelcome) {
    return (
      <WelcomeScreen
        health={health}
        onComplete={() => setShowWelcome(false)}
      />
    );
  }

  function handleSelectFile(path: string) {
    setSelectedFile(path);
  }

  const sidebarItems: { key: Tab; label: string }[] = [
    { key: "chat", label: "💬  Chat" },
    { key: "search", label: "🔍  Search" },
    { key: "inputs", label: "📥  Inputs Explorer" },
    { key: "runs", label: "🚀  Run ReEDS" },
    { key: "outputs", label: "📤  Outputs Explorer" },
    { key: "hpc", label: "🖥️  HPC Explorer" },
    { key: "settings", label: "⚙️  Settings" },
  ];

  return (
    <div className="app-shell">
      {/* ── Sidebar ──────────────────────────────────── */}
      <nav className="sidebar" style={{ width: sidebarWidth, minWidth: sidebarWidth }}>
        <div className="sidebar-brand">
          <img src="/reeds-logo.png" alt="ReEDS" className="sidebar-logo" />
          <h1>ReEDS-Copilot</h1>
        </div>
        {sidebarItems.map((item) => (
          <button
            key={item.key}
            className={tab === item.key ? "active" : ""}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <ResizeHandle direction="horizontal" onResize={handleSidebarResize} />

      {/* ── Chat history (visible on chat tab) ───────── */}
      {tab === "chat" && (
        <ChatHistory
          activeSessionId={sessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          refreshKey={historyRefreshKey}
        />
      )}

      {/* ── Main content ─────────────────────────────── */}
      <div className="main-area">
        {/* Mode bar for chat */}
        {tab === "chat" && (
          <div className="mode-bar">
            {MODES.map((m) => (
              <button
                key={m.value}
                className={mode === m.value ? "active" : ""}
                onClick={() => setMode(m.value)}
              >
                {m.label}
              </button>
            ))}
            {selectedFile && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: "0.8rem",
                  color: "var(--accent)",
                  alignSelf: "center",
                }}
              >
                📎 {selectedFile}
                <span
                  style={{ cursor: "pointer", marginLeft: 6 }}
                  onClick={() => setSelectedFile(null)}
                >
                  ✕
                </span>
              </span>
            )}
          </div>
        )}

        <div className="content-row">
          {/* Center */}
          {tab === "chat" && (
            <ChatPanel
              mode={mode}
              selectedPath={selectedFile}
              onSources={setSources}
              messages={messages}
              setMessages={handleSetMessages}
              onNavigate={(t) => setTab(t as Tab)}
            />
          )}
          {tab === "search" && <SearchPanel onSelectFile={handleSelectFile} />}
          {tab === "runs" && <RunPanel />}
          {tab === "inputs" && (
            <FileBrowser rootPath="inputs" onSelectFile={handleSelectFile} />
          )}
          {tab === "outputs" && (
            <OutputExplorer onSelectFile={handleSelectFile} />
          )}
          {tab === "hpc" && <HpcBrowser />}
          {tab === "settings" && <SettingsPanel />}

          {/* Right panel – always visible except on settings */}
          {tab !== "settings" && tab !== "runs" && tab !== "hpc" && (
            <>
              <ResizeHandle direction="horizontal" onResize={handleRightResize} />
              <RightPanel
                selectedFile={selectedFile}
                sources={sources}
                onSelectFile={handleSelectFile}
                width={rightWidth}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
