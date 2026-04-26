import { useEffect, useState, useMemo } from "react";
import {
  listRunFoldersAPI,
  listFilesAPI,
  type RunFolder,
  type FileEntry,
  type FileListResponse,
} from "../lib/api";
import ComparePanel from "./ComparePanel";
import PostProcessPanel from "./PostProcessPanel";

type SortKey = "name" | "type" | "size" | "modified";
type SortDir = "asc" | "desc";

function getExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
}

interface Props {
  onSelectFile: (path: string) => void;
}

export default function OutputExplorer({ onSelectFile }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [ppMode, setPpMode] = useState(false);

  // When a folder is expanded, browse into it
  const [activePath, setActivePath] = useState<string | null>(null);
  const [browseEntries, setBrowseEntries] = useState<FileEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

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

  function formatDate(ts: number): string {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  const sortedBrowseEntries = useMemo(() => {
    const dirs = browseEntries.filter((e) => e.is_dir);
    const files = browseEntries.filter((e) => !e.is_dir);
    const cmp = (a: FileEntry, b: FileEntry): number => {
      let result = 0;
      switch (sortKey) {
        case "name":
          result = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
          break;
        case "type":
          result = getExtension(a.name).localeCompare(getExtension(b.name)) || a.name.localeCompare(b.name);
          break;
        case "size":
          result = (a.size ?? 0) - (b.size ?? 0);
          break;
        case "modified":
          result = (a.modified_at ?? 0) - (b.modified_at ?? 0);
          break;
      }
      return sortDir === "asc" ? result : -result;
    };
    return [...dirs.sort(cmp), ...files.sort(cmp)];
  }, [browseEntries, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  function statusLabel(f: RunFolder) {
    if (f.has_report) return { text: "Completed", cls: "output-status-done" };
    if (f.has_gamslog) return { text: "In Progress", cls: "output-status-running" };
    if (f.has_meta) return { text: "Setting Up", cls: "output-status-setup" };
    return { text: "Failed", cls: "output-status-failed" };
  }

  // breadcrumb when browsing inside a run
  const breadcrumbParts = activePath ? activePath.split("/") : [];

  return (
    <div className="output-explorer">
      <div className="output-explorer-header">
        <h2>Outputs Explorer</h2>
        <div style={{ display: "flex", gap: 6 }}>
          {!compareMode && !ppMode && folders.length >= 2 && (
            <>
              <button
                className="btn btn-outline"
                style={{ fontSize: "0.78rem", padding: "4px 10px" }}
                onClick={() => setCompareMode(true)}
                title="Compare outputs across cases"
              >
                ⚖ Compare
              </button>
              <button
                className="btn btn-outline"
                style={{ fontSize: "0.78rem", padding: "4px 10px" }}
                onClick={() => setPpMode(true)}
                title="Run post-processing tools (compare_cases.py, bokehpivot)"
              >
                📊 Post-Process
              </button>
            </>
          )}
          <button className="refresh-btn" onClick={refresh} title="Refresh">↻</button>
        </div>
      </div>

      {compareMode && <ComparePanel onClose={() => setCompareMode(false)} />}
      {ppMode && <PostProcessPanel onClose={() => setPpMode(false)} onSelectFile={onSelectFile} />}

      {!compareMode && !ppMode && error && <div className="error-banner">{error}</div>}
      {!compareMode && !ppMode && loading && <div className="loading">Loading…</div>}

      {!compareMode && !ppMode && !loading && folders.length === 0 && !activePath && (
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
      {!compareMode && !ppMode && !activePath && folders.length > 0 && (
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
                    {f.has_report && <span className="folder-badge outputs">report</span>}
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
      {!compareMode && !ppMode && activePath && (
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

          {/* Sort header */}
          {!browseLoading && sortedBrowseEntries.length > 0 && (
            <div className="file-sort-bar">
              <span className="sort-col sort-col--name" onClick={() => toggleSort("name")}>
                Name{sortIndicator("name")}
              </span>
              <span className="sort-col sort-col--type" onClick={() => toggleSort("type")}>
                Type{sortIndicator("type")}
              </span>
              <span className="sort-col sort-col--size" onClick={() => toggleSort("size")}>
                Size{sortIndicator("size")}
              </span>
              <span className="sort-col sort-col--date" onClick={() => toggleSort("modified")}>
                Modified{sortIndicator("modified")}
              </span>
            </div>
          )}

          {sortedBrowseEntries.map((e) => (
            <div
              key={e.rel_path}
              className="file-entry"
              onClick={() => handleBrowseClick(e)}
            >
              <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
              <span className="name">{e.name}</span>
              <span className="ext">{e.is_dir ? "" : getExtension(e.name)}</span>
              <span className="size">{formatSize(e.size)}</span>
              <span className="date">{formatDate(e.modified_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
