import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import {
  listHpcFilesAPI,
  previewHpcFileAPI,
  disconnectHpcAPI,
  listHpcCasesFilesAPI,
  startRunAPI,
  listRunsAPI,
  getRunAPI,
  cancelRunAPI,
  deleteRunAPI,
  type FileEntry,
  type FileListResponse,
  type FilePreviewResponse,
  type CasesFile,
  type RunRecord,
} from "../lib/api";

type SortKey = "name" | "type" | "size" | "modified";
type SortDir = "asc" | "desc";

const HPC_CLUSTERS: { label: string; host: string }[] = [
  { label: "Kestrel", host: "kestrel.hpc.nrel.gov" },
  { label: "Eagle", host: "eagle.hpc.nrel.gov" },
  { label: "Custom", host: "" },
];

function getExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
}

function formatSize(size: number | null | undefined): string {
  if (size == null) return "";
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

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function statusBadge(s: string) {
  const map: Record<string, { bg: string; label: string }> = {
    queued: { bg: "#555", label: "Queued" },
    running: { bg: "#2196f3", label: "Running" },
    completed: { bg: "#4caf50", label: "Completed" },
    failed: { bg: "#e05252", label: "Failed" },
    cancelled: { bg: "#ff9800", label: "Cancelled" },
  };
  const { bg, label } = map[s] ?? { bg: "#888", label: s };
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: "0.75rem", fontWeight: 600, color: "#fff", background: bg,
    }}>
      {label}
    </span>
  );
}

/* ─── Main component ──────────────────────────────────────────────────────── */

export default function HpcBrowser() {
  /* ── Connection state ─────────────────────────────── */
  const [cluster, setCluster] = useState("kestrel");
  const [hpcHost, setHpcHost] = useState("kestrel.hpc.nrel.gov");
  const [hpcUser, setHpcUser] = useState("");
  const [hpcPassword, setHpcPassword] = useState("");
  const [connected, setConnected] = useState(false);

  /* ── File browser state ───────────────────────────── */
  const [currentPath, setCurrentPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  /* ── Preview state ────────────────────────────────── */
  const [preview, setPreview] = useState<FilePreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  /* ── Run form state (mirrors RunPanel) ────────────── */
  const [reedsPath, setReedsPath] = useState("");
  const [casesFiles, setCasesFiles] = useState<CasesFile[]>([]);
  const [selectedSuffix, setSelectedSuffix] = useState("");
  const [availableCases, setAvailableCases] = useState<string[]>([]);
  const [selectedCases, setSelectedCases] = useState<string[]>([]);
  const [batchName, setBatchName] = useState(
    () => `v${new Date().toISOString().slice(0, 10).replace(/-/g, "")}_hpc`,
  );
  const [simultRuns, setSimultRuns] = useState(1);
  const [overwrite, setOverwrite] = useState(false);
  const [slurmAccount, setSlurmAccount] = useState("");
  const [slurmWalltime, setSlurmWalltime] = useState("2-00:00:00");
  const [slurmPartition, setSlurmPartition] = useState("");
  const [slurmMemory, setSlurmMemory] = useState("246000");
  const [slurmMailUser, setSlurmMailUser] = useState("");
  const [slurmMailBegin, setSlurmMailBegin] = useState(false);
  const [slurmMailEnd, setSlurmMailEnd] = useState(false);
  const [slurmMailFail, setSlurmMailFail] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [runError, setRunError] = useState("");

  /* ── Run history state ────────────────────────────── */
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<RunRecord | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── Active view: "browser" or "run" ──────────────── */
  const [activeView, setActiveView] = useState<"browser" | "run">("browser");

  /* ── File browser logic ─────────────────────────────  */
  const loadDirectory = useCallback(
    (path: string) => {
      if (!hpcHost || !hpcUser) return;
      setLoading(true);
      setError(null);
      listHpcFilesAPI(hpcHost, hpcUser, path, hpcPassword)
        .then((res: FileListResponse) => {
          setEntries(res.entries);
          setCurrentPath(path);
          setConnected(true);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : String(err));
          setEntries([]);
        })
        .finally(() => setLoading(false));
    },
    [hpcHost, hpcUser, hpcPassword],
  );

  function handleClusterChange(value: string) {
    setCluster(value);
    const match = HPC_CLUSTERS.find((c) => c.label.toLowerCase() === value);
    if (match && match.host) setHpcHost(match.host);
  }

  function handleConnect() {
    if (!hpcHost || !hpcUser) { setError("Please enter both hostname and username"); return; }
    loadDirectory("/");
  }

  function handleDisconnect() {
    disconnectHpcAPI(hpcHost, hpcUser).catch(() => {});
    setConnected(false);
    setEntries([]);
    setPreview(null);
    setSelectedFile(null);
    setHpcPassword("");
    setError(null);
    setCasesFiles([]);
  }

  function handleClick(entry: FileEntry) {
    if (entry.is_dir) {
      loadDirectory(entry.rel_path);
      setPreview(null);
      setSelectedFile(null);
    } else {
      const ext = getExtension(entry.name);
      if (!ext) {
        listHpcFilesAPI(hpcHost, hpcUser, entry.rel_path, hpcPassword)
          .then((res) => {
            setEntries(res.entries);
            setCurrentPath(entry.rel_path);
            setPreview(null);
            setSelectedFile(null);
          })
          .catch(() => showPreview(entry));
      } else {
        showPreview(entry);
      }
    }
  }

  function showPreview(entry: FileEntry) {
    setSelectedFile(entry.rel_path);
    setPreviewLoading(true);
    previewHpcFileAPI(hpcHost, hpcUser, entry.rel_path, hpcPassword)
      .then(setPreview)
      .catch((err) => {
        setPreview({
          rel_path: entry.rel_path,
          file_type: getExtension(entry.name),
          content: `Error loading preview: ${err instanceof Error ? err.message : String(err)}`,
          truncated: false,
        });
      })
      .finally(() => setPreviewLoading(false));
  }

  function navigateUp() {
    const parts = currentPath.split("/").filter(Boolean);
    if (parts.length >= 1) {
      parts.pop();
      loadDirectory("/" + parts.join("/") || "/");
    }
  }

  function navigateTo(path: string) {
    loadDirectory(path);
    setPreview(null);
    setSelectedFile(null);
  }

  /* ── Sorting ────────────────────────────────────────  */
  const sortedEntries = useMemo(() => {
    const dirs = entries.filter((e) => e.is_dir);
    const files = entries.filter((e) => !e.is_dir);
    const cmp = (a: FileEntry, b: FileEntry): number => {
      let result = 0;
      switch (sortKey) {
        case "name": result = a.name.localeCompare(b.name, undefined, { sensitivity: "base" }); break;
        case "type": result = getExtension(a.name).localeCompare(getExtension(b.name)) || a.name.localeCompare(b.name); break;
        case "size": result = (a.size ?? 0) - (b.size ?? 0); break;
        case "modified": result = (a.modified_at ?? 0) - (b.modified_at ?? 0); break;
      }
      return sortDir === "asc" ? result : -result;
    };
    return [...dirs.sort(cmp), ...files.sort(cmp)];
  }, [entries, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }
  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  const pathParts = currentPath.split("/").filter(Boolean);

  /* ── Run form logic (mirrors RunPanel) ──────────────  */
  function loadCasesFiles(path: string) {
    if (!hpcHost || !hpcUser || !path) return;
    listHpcCasesFilesAPI(hpcHost, hpcUser, path, hpcPassword)
      .then((files) => {
        setCasesFiles(files);
        const small = files.find((f) => f.suffix === "small");
        const first = small || files[0];
        if (first) {
          setSelectedSuffix(first.suffix);
          setAvailableCases(first.cases);
          setSelectedCases(first.cases);
        }
      })
      .catch(() => setCasesFiles([]));
  }

  function handleSuffixChange(suffix: string) {
    setSelectedSuffix(suffix);
    const file = casesFiles.find((f) => f.suffix === suffix);
    const cases = file?.cases ?? [];
    setAvailableCases(cases);
    setSelectedCases(cases);
  }

  function toggleCase(c: string) {
    setSelectedCases((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c],
    );
  }

  function setReedsPathFromBrowser() {
    setReedsPath(currentPath);
    loadCasesFiles(currentPath);
  }

  // Load cases when reedsPath changes via typing + Enter
  function handleReedsPathKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && reedsPath) loadCasesFiles(reedsPath);
  }

  async function handleLaunch() {
    if (!reedsPath.trim()) { setRunError("Set the ReEDS path first"); return; }
    if (!slurmAccount.trim()) { setRunError("Slurm account (allocation) is required"); return; }
    setRunError("");
    setLaunching(true);
    try {
      await startRunAPI({
        batch_name: batchName.trim(),
        cases_suffix: selectedSuffix || "_default",
        cases: selectedCases.length > 0 ? selectedCases : undefined,
        simult_runs: simultRuns,
        target: "hpc",
        overwrite,
        hpc_host: hpcHost,
        hpc_user: hpcUser,
        hpc_password: hpcPassword,
        hpc_reeds_path: reedsPath.trim(),
        slurm_account: slurmAccount.trim(),
        slurm_walltime: slurmWalltime.trim(),
        slurm_partition: slurmPartition.trim() || undefined,
        slurm_memory: slurmMemory.trim(),
        slurm_mail_user: slurmMailUser.trim() || undefined,
        slurm_mail_type: (() => {
          const types: string[] = [];
          if (slurmMailBegin) types.push("BEGIN");
          if (slurmMailEnd) types.push("END");
          if (slurmMailFail) types.push("FAIL");
          return types.length > 0 && slurmMailUser.trim() ? types.join(",") : undefined;
        })(),
      });
      refreshRuns();
    } catch (e: any) {
      setRunError(e.message ?? "Failed to start run");
    } finally {
      setLaunching(false);
    }
  }

  /* ── Run history logic ──────────────────────────────  */
  function refreshRuns() {
    listRunsAPI().then((all) => {
      // Only show HPC runs
      setRuns(all.filter((r) => r.target === "hpc"));
    }).catch(() => {});
    if (expandedRun) {
      getRunAPI(expandedRun).then(setExpandedDetail).catch(() => {});
    }
  }

  useEffect(() => {
    if (connected) refreshRuns();
  }, [connected]);

  /* Clear SSH session & password when user closes/refreshes the page */
  useEffect(() => {
    const cleanup = () => {
      if (hpcHost && hpcUser) {
        // Use sendBeacon for reliability during page unload
        const payload = JSON.stringify({ host: hpcHost, user: hpcUser });
        navigator.sendBeacon(
          `${import.meta.env.VITE_API_URL ?? "http://localhost:8001/api"}/files/hpc/disconnect`,
          new Blob([payload], { type: "application/json" }),
        );
      }
    };
    window.addEventListener("beforeunload", cleanup);
    return () => window.removeEventListener("beforeunload", cleanup);
  }, [hpcHost, hpcUser]);

  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === "running" || r.status === "queued");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(refreshRuns, 5000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runs]);

  async function handleCancel(id: string) {
    await cancelRunAPI(id).catch(() => {});
    refreshRuns();
  }
  async function handleDelete(id: string) {
    await deleteRunAPI(id).catch(() => {});
    refreshRuns();
  }
  async function toggleExpand(id: string) {
    if (expandedRun === id) { setExpandedRun(null); setExpandedDetail(null); return; }
    setExpandedRun(id);
    try { setExpandedDetail(await getRunAPI(id)); } catch { setExpandedDetail(null); }
  }

  /* ── Render ─────────────────────────────────────────  */
  return (
    <div className="hpc-browser">
      {/* ── Connection bar ────────────────────────────── */}
      <div className="hpc-connection-bar">
        <div className="hpc-connection-row">
          <label>Cluster</label>
          <select value={cluster} onChange={(e) => handleClusterChange(e.target.value)}>
            {HPC_CLUSTERS.map((c) => (
              <option key={c.label} value={c.label.toLowerCase()}>{c.label}</option>
            ))}
          </select>
          <label>Host</label>
          <input type="text" value={hpcHost} onChange={(e) => setHpcHost(e.target.value)}
            placeholder="login.hpc.example.com" disabled={cluster !== "custom"} />
          <label>User</label>
          <input type="text" value={hpcUser} onChange={(e) => setHpcUser(e.target.value)}
            placeholder="username" />
          <label>Password</label>
          <input type="password" value={hpcPassword} onChange={(e) => setHpcPassword(e.target.value)}
            placeholder="optional if SSH key set" />
          <button className="btn-connect" onClick={handleConnect} disabled={loading}>
            {loading && !connected ? "Connecting…" : connected ? "🟢 Connected" : "Connect"}
          </button>
          {connected && (
            <button className="btn-disconnect" onClick={handleDisconnect}>Disconnect</button>
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!connected && !loading && (
        <div className="hpc-empty-state">
          <p>🖥️ Connect to an HPC cluster to browse remote files and launch runs</p>
          <p style={{ fontSize: "0.85rem", opacity: 0.7 }}>
            Enter your credentials and click Connect. Password-based or SSH key auth supported.
          </p>
        </div>
      )}

      {/* ── View toggle ──────────────────────────────── */}
      {connected && (
        <div className="hpc-view-toggle">
          <button className={activeView === "browser" ? "active" : ""} onClick={() => setActiveView("browser")}>
            📂 File Browser
          </button>
          <button className={activeView === "run" ? "active" : ""} onClick={() => setActiveView("run")}>
            🚀 Launch Run
          </button>
        </div>
      )}

      {/* ── File Browser View ─────────────────────────  */}
      {connected && activeView === "browser" && (
        <>
          <div className="hpc-connection-bar" style={{ borderTop: "none" }}>
            <div className="hpc-path-input-row">
              <label>Path</label>
              <input type="text" value={currentPath} onChange={(e) => setCurrentPath(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") loadDirectory(currentPath); }}
                placeholder="/home/user/ReEDS" />
              <button onClick={() => loadDirectory(currentPath)}>Go</button>
            </div>
          </div>

          <div className="hpc-content-split">
            {/* Left: file listing */}
            <div className="hpc-file-list">
              <div className="breadcrumb">
                <span onClick={() => navigateTo("/")}>/</span>
                {pathParts.map((part, i) => {
                  const sub = "/" + pathParts.slice(0, i + 1).join("/");
                  return (
                    <span key={sub}>
                      {" / "}
                      <span onClick={() => navigateTo(sub)}>{part}</span>
                    </span>
                  );
                })}
                {pathParts.length > 0 && (
                  <span onClick={navigateUp} style={{ marginLeft: 12, cursor: "pointer" }}>⬆ up</span>
                )}
              </div>

              <div className="file-sort-bar">
                <span className="sort-col sort-col--name" onClick={() => toggleSort("name")}>Name{sortIndicator("name")}</span>
                <span className="sort-col sort-col--type" onClick={() => toggleSort("type")}>Type{sortIndicator("type")}</span>
                <span className="sort-col sort-col--size" onClick={() => toggleSort("size")}>Size{sortIndicator("size")}</span>
                <span className="sort-col sort-col--date" onClick={() => toggleSort("modified")}>Modified{sortIndicator("modified")}</span>
              </div>

              {loading && <div className="loading">Loading…</div>}
              {!loading && sortedEntries.length === 0 && (
                <div className="loading" style={{ opacity: 0.6 }}>Empty directory</div>
              )}
              {sortedEntries.map((e) => (
                <div key={e.rel_path}
                  className={`file-entry${selectedFile === e.rel_path ? " selected" : ""}`}
                  onClick={() => handleClick(e)}>
                  <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
                  <span className="name">{e.name}</span>
                  <span className="ext">{e.is_dir ? "" : getExtension(e.name)}</span>
                  <span className="size">{formatSize(e.size)}</span>
                  <span className="date">{formatDate(e.modified_at)}</span>
                </div>
              ))}
            </div>

            {/* Right: inline preview */}
            <div className="hpc-preview-pane">
              {!preview && !previewLoading && (
                <div className="hpc-empty-state" style={{ padding: "2rem" }}><p>Select a file to preview</p></div>
              )}
              {previewLoading && <div className="loading">Loading preview…</div>}
              {preview && !previewLoading && (
                <div className="hpc-preview-content">
                  <div className="hpc-preview-header">
                    <strong>{preview.rel_path.split("/").pop()}</strong>
                    <span style={{ marginLeft: 8, opacity: 0.6 }}>{preview.file_type}</span>
                    {preview.truncated && (
                      <span style={{ marginLeft: 8, color: "var(--accent)", fontSize: "0.8rem" }}>(truncated)</span>
                    )}
                  </div>
                  {preview.columns && preview.rows ? (
                    <div className="csv-preview-wrapper" style={{ overflow: "auto", maxHeight: "calc(100vh - 200px)" }}>
                      <table className="csv-preview">
                        <thead><tr>{preview.columns.map((col) => <th key={col}>{col}</th>)}</tr></thead>
                        <tbody>
                          {preview.rows.map((row, i) => (
                            <tr key={i}>{preview.columns!.map((col) => <td key={col}>{String(row[col] ?? "")}</td>)}</tr>
                          ))}
                        </tbody>
                      </table>
                      {preview.total_rows != null && (
                        <div style={{ padding: "4px 8px", fontSize: "0.8rem", opacity: 0.6 }}>
                          Showing {preview.rows.length} of {preview.total_rows} rows
                        </div>
                      )}
                    </div>
                  ) : (
                    <pre className="hpc-preview-text">{preview.content}</pre>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Launch Run View (mirrors RunPanel) ─────────  */}
      {connected && activeView === "run" && (
        <div className="run-panel">
          <section className="run-form">
            <h2>Launch ReEDS Run on HPC</h2>

            {/* ReEDS Path */}
            <div className="run-field">
              <label>ReEDS Path on HPC *</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input type="text" value={reedsPath} onChange={(e) => setReedsPath(e.target.value)}
                  onKeyDown={handleReedsPathKeyDown}
                  placeholder="/projects/reeds/ReEDS" style={{ flex: 1 }} />
                <button className="btn-set-path" onClick={setReedsPathFromBrowser}
                  title="Use current browsed directory">📂 Use Current Dir</button>
              </div>
              <span className="run-field-hint">Press Enter or click "Use Current Dir" to load cases files</span>
            </div>

            {/* Slurm config */}
            <div className="slurm-config">
              <label style={{ fontWeight: 600, marginBottom: 4, display: "block" }}>
                Slurm Configuration
              </label>
              <div className="run-field">
                <label>Account (Allocation) *</label>
                <input type="text" value={slurmAccount}
                  onChange={(e) => setSlurmAccount(e.target.value)}
                  placeholder="your-project-allocation" />
              </div>
              <div className="run-field">
                <label>Walltime</label>
                <input type="text" value={slurmWalltime}
                  onChange={(e) => setSlurmWalltime(e.target.value)}
                  placeholder="2-00:00:00" />
                <span className="run-field-hint">Format: D-HH:MM:SS</span>
              </div>
              <div className="run-field">
                <label>Partition (optional)</label>
                <input type="text" value={slurmPartition}
                  onChange={(e) => setSlurmPartition(e.target.value)}
                  placeholder="(leave blank for default)" />
              </div>
              <div className="run-field">
                <label>Memory (MB)</label>
                <input type="text" value={slurmMemory}
                  onChange={(e) => setSlurmMemory(e.target.value)}
                  placeholder="246000" />
                <span className="run-field-hint">Up to 246000 (normal) or 2000000 (bigmem) on Kestrel</span>
              </div>
              <div className="run-field">
                <label>Email Notifications</label>
                <input type="email" value={slurmMailUser}
                  onChange={(e) => setSlurmMailUser(e.target.value)}
                  placeholder="your.email@nrel.gov" />
                <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
                  <label style={{ fontSize: "0.85rem", fontWeight: 400 }}>
                    <input type="checkbox" checked={slurmMailBegin}
                      onChange={(e) => setSlurmMailBegin(e.target.checked)} /> BEGIN
                  </label>
                  <label style={{ fontSize: "0.85rem", fontWeight: 400 }}>
                    <input type="checkbox" checked={slurmMailEnd}
                      onChange={(e) => setSlurmMailEnd(e.target.checked)} /> END
                  </label>
                  <label style={{ fontSize: "0.85rem", fontWeight: 400 }}>
                    <input type="checkbox" checked={slurmMailFail}
                      onChange={(e) => setSlurmMailFail(e.target.checked)} /> FAIL
                  </label>
                </div>
                <span className="run-field-hint">Leave email blank to disable notifications</span>
              </div>
            </div>

            {/* Batch name */}
            <div className="run-field">
              <label>Batch Name</label>
              <input type="text" value={batchName} onChange={(e) => setBatchName(e.target.value)}
                placeholder="v20260509_hpc" />
            </div>

            {/* Cases file selector */}
            <div className="run-field">
              <label>Cases File</label>
              {casesFiles.length > 0 ? (
                <select value={selectedSuffix} onChange={(e) => handleSuffixChange(e.target.value)}>
                  {casesFiles.map((f) => (
                    <option key={f.suffix} value={f.suffix}>
                      {f.filename} ({f.cases.length} case{f.cases.length !== 1 ? "s" : ""})
                    </option>
                  ))}
                </select>
              ) : (
                <span className="run-field-hint" style={{ display: "block", padding: "6px 0" }}>
                  Set the ReEDS path above to load available cases files
                </span>
              )}
            </div>

            {/* Case selection chips */}
            {availableCases.length > 0 && (
              <div className="run-field">
                <label>
                  Cases to Run
                  <span className="run-field-hint">
                    {selectedCases.length}/{availableCases.length} selected
                  </span>
                  <span className="case-select-btns">
                    <button onClick={() => setSelectedCases([...availableCases])}>All</button>
                    <button onClick={() => setSelectedCases([])}>None</button>
                  </span>
                </label>
                <div className="case-chips">
                  {availableCases.map((c) => (
                    <button key={c}
                      className={`case-chip ${selectedCases.includes(c) ? "selected" : ""}`}
                      onClick={() => toggleCase(c)} title={c}>
                      {c}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Simultaneous runs */}
            <div className="run-field">
              <label>Simultaneous Runs</label>
              <input type="number" min={1} max={32} value={simultRuns}
                onChange={(e) => setSimultRuns(Math.max(1, +e.target.value))}
                style={{ width: 80 }} />
            </div>

            <label className="run-overwrite-toggle">
              <input type="checkbox" checked={overwrite}
                onChange={(e) => setOverwrite(e.target.checked)} />
              Overwrite existing run folders
            </label>

            {runError && <div className="run-error">{runError}</div>}

            <button className="run-launch-btn" onClick={handleLaunch} disabled={launching}>
              {launching ? "Submitting…" : "🚀 Submit to HPC"}
            </button>
          </section>

          {/* ── Run history ───────────────────────────── */}
          <section className="run-history">
            <div className="run-history-header">
              <h2>HPC Run History</h2>
              <button className="run-refresh-btn" onClick={refreshRuns} title="Refresh">↻</button>
            </div>

            {runs.length === 0 && (
              <p className="run-empty">No HPC runs yet. Launch one above!</p>
            )}

            {runs.map((r) => (
              <div key={r.id} className={`run-card ${r.status}`}>
                <div className="run-card-header" onClick={() => toggleExpand(r.id)}>
                  <div className="run-card-title">
                    <strong>{r.batch_name}</strong>
                    <span className="run-card-suffix">cases_{r.cases_suffix}.csv</span>
                  </div>
                  <div className="run-card-meta">
                    <span style={{
                      fontSize: "0.7rem", padding: "1px 6px", borderRadius: 3,
                      background: "#7c4dff", color: "#fff", fontWeight: 600, marginRight: 4,
                    }}>HPC</span>
                    {statusBadge(r.status)}
                    <span className="run-card-time">{fmtTime(r.created_at)}</span>
                  </div>
                </div>

                <div className="run-card-actions">
                  {(r.status === "running" || r.status === "queued") && (
                    <button className="run-action cancel" onClick={() => handleCancel(r.id)}>Cancel</button>
                  )}
                  {r.status !== "running" && r.status !== "queued" && (
                    <button className="run-action delete" onClick={() => handleDelete(r.id)}>Delete</button>
                  )}
                </div>

                {expandedRun === r.id && expandedDetail && (
                  <div className="run-detail">
                    <div className="run-detail-row"><span>Cases:</span><span>{expandedDetail.cases.join(", ") || "all"}</span></div>
                    <div className="run-detail-row"><span>Workers:</span><span>{expandedDetail.simult_runs}</span></div>
                    {expandedDetail.slurm_job_ids?.length > 0 && (
                      <div className="run-detail-row"><span>Slurm Jobs:</span><span>{expandedDetail.slurm_job_ids.join(", ")}</span></div>
                    )}
                    {expandedDetail.error && (
                      <div className="run-detail-row error"><span>Error:</span><span>{expandedDetail.error}</span></div>
                    )}
                    {expandedDetail.log_tail && (
                      <div className="run-log">
                        <label>Log Output (last 100 lines)</label>
                        <pre>{expandedDetail.log_tail}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
