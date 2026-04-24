import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import SearchPanel from "./components/SearchPanel";
import FileBrowser from "./components/FileBrowser";
import RightPanel from "./components/RightPanel";
import SettingsPanel from "./components/SettingsPanel";
import type { SourceSnippet } from "./lib/api";

type Tab = "chat" | "search" | "inputs" | "outputs" | "settings";
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

  function handleSelectFile(path: string) {
    setSelectedFile(path);
  }

  const sidebarItems: { key: Tab; label: string }[] = [
    { key: "chat", label: "💬  Chat" },
    { key: "search", label: "🔍  Search" },
    { key: "inputs", label: "📥  Inputs Explorer" },
    { key: "outputs", label: "📤  Outputs Explorer" },
    { key: "settings", label: "⚙️  Settings" },
  ];

  return (
    <div className="app-shell">
      {/* ── Sidebar ──────────────────────────────────── */}
      <nav className="sidebar">
        <h1>ReEDS-Copilot</h1>
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
            />
          )}
          {tab === "search" && <SearchPanel onSelectFile={handleSelectFile} />}
          {tab === "inputs" && (
            <FileBrowser rootPath="inputs" onSelectFile={handleSelectFile} />
          )}
          {tab === "outputs" && (
            <FileBrowser rootPath="." onSelectFile={handleSelectFile} />
          )}
          {tab === "settings" && <SettingsPanel />}

          {/* Right panel – always visible except on settings */}
          {tab !== "settings" && (
            <RightPanel
              selectedFile={selectedFile}
              sources={sources}
              onSelectFile={handleSelectFile}
            />
          )}
        </div>
      </div>
    </div>
  );
}
