import { useEffect, useState } from "react";
import {
  listRunFoldersAPI,
  listFilesAPI,
  type RunFolder,
  type FileEntry,
  type FileListResponse,
} from "../lib/api";

interface Props {
  onSelectFile: (path: string) => void;
}

export default function OutputExplorer({ onSelectFile }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // When a folder is expanded, browse into it
  const [activePath, setActivePath] = useState<string | null>(null);
  const [browseEntries, setBrowseEntries] = useState<FileEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  function refresh() {
    setLoading(true);
    setError(null);
    listRunFoldersAPI()
      .then(setFolders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, []);

  // Browse inside a run folder
  useEffect(() => {
    if (!activePath) {
      setBrowseEntries([]);
      return;
    }
    let cancelled = false;
    setBrowseLoading(true);
    listFilesAPI(activePath)
      .then((res: FileListResponse) => {
        if (!cancelled) setBrowseEntries(res.entries);
      })
      .catch(() => {
        if (!cancelled) setBrowseEntries([]);
      })
      .finally(() => {
        if (!cancelled) setBrowseLoading(false);
      });
    return () => { cancelled = true; };
  }, [activePath]);

  function handleFolderClick(f: RunFolder) {
    // Toggle: click same folder to collapse
    const relPath = `runs/${f.name}`;
    setActivePath((prev) => (prev === relPath ? null : relPath));
  }

  function handleBrowseClick(entry: FileEntry) {
    if (entry.is_dir) {
      setActivePath(entry.rel_path);
    } else {
      onSelectFile(entry.rel_path);
    }
  }

  function navigateUp() {
    if (!activePath) return;
    const parts = activePath.split("/");
    if (parts.length <= 2) {
      // back to folder list
      setActivePath(null);
    } else {
      parts.pop();
      setActivePath(parts.join("/"));
    }
  }

  function formatSize(size: number | null): string {
    if (size === null) return "";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
  }

  function statusLabel(f: RunFolder) {
    if (f.has_outputs) return { text: "Completed", cls: "output-status-done" };
    if (f.has_gamslog) return { text: "In Progress", cls: "output-status-running" };
    if (f.has_meta) return { text: "Setting Up", cls: "output-status-setup" };
    return { text: "Unknown", cls: "output-status-unknown" };
  }

  // breadcrumb when browsing inside a run
  const breadcrumbParts = activePath ? activePath.split("/") : [];

  return (
    <div className="output-explorer">
      <div className="output-explorer-header">
        <h2>Outputs Explorer</h2>
        <button className="refresh-btn" onClick={refresh} title="Refresh">↻</button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading">Loading…</div>}

      {!loading && folders.length === 0 && !activePath && (
        <div className="output-empty">
          <div className="output-empty-icon">📂</div>
          <p>No run cases found yet.</p>
          <p className="output-empty-hint">
            Go to <strong>Run ReEDS</strong> to start a model run.<br />
            Run outputs will appear here under <code>runs/</code>.
          </p>
        </div>
      )}

      {/* ── Folder list view ─── */}
      {!activePath && folders.length > 0 && (
        <div className="output-folder-list">
          {folders.map((f) => {
            const st = statusLabel(f);
            return (
              <div
                key={f.name}
                className="output-folder-card"
                onClick={() => handleFolderClick(f)}
              >
                <div className="output-folder-main">
                  <span className="output-folder-icon">📁</span>
                  <span className="output-folder-name">{f.name}</span>
                  <span className={`output-status-badge ${st.cls}`}>{st.text}</span>
                </div>
                <div className="output-folder-meta">
                  <span className="output-folder-time">
                    {new Date(f.modified_at * 1000).toLocaleString()}
                  </span>
                  <span className="output-folder-badges">
                    {f.has_outputs && <span className="folder-badge outputs">outputs</span>}
                    {f.has_gamslog && <span className="folder-badge log">gamslog</span>}
                    {f.has_meta && <span className="folder-badge meta">meta</span>}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Browsing inside a run folder ─── */}
      {activePath && (
        <div className="output-browse">
          <div className="breadcrumb">
            <span onClick={() => setActivePath(null)}>runs</span>
            {breadcrumbParts.slice(1).map((part, i) => {
              const sub = breadcrumbParts.slice(0, i + 2).join("/");
              return (
                <span key={sub}>
                  {" / "}
                  <span onClick={() => setActivePath(sub)}>{part}</span>
                </span>
              );
            })}
            <span onClick={navigateUp} style={{ marginLeft: 12, cursor: "pointer" }}>
              ⬆ up
            </span>
          </div>

          {browseLoading && <div className="loading">Loading…</div>}

          {browseEntries.map((e) => (
            <div
              key={e.rel_path}
              className="file-entry"
              onClick={() => handleBrowseClick(e)}
            >
              <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
              <span className="name">{e.name}</span>
              <span className="size">{formatSize(e.size)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
