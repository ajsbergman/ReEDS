import { useEffect, useRef, useState } from "react";
import {
  listCasesFilesAPI,
  listCondaEnvsAPI,
  listRunFoldersAPI,
  startRunAPI,
  listRunsAPI,
  getRunAPI,
  cancelRunAPI,
  deleteRunAPI,
  type CasesFile,
  type CondaEnv,
  type RunRecord,
  type RunFolder,
} from "../lib/api";

/* ─── helpers ─────────────────────────────────────────────────────────────── */

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
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: "0.75rem",
        fontWeight: 600,
        color: "#fff",
        background: bg,
      }}
    >
      {label}
    </span>
  );
}

/* ─── component ───────────────────────────────────────────────────────────── */

export default function RunPanel() {
  /* Config form state */
  const [target, setTarget] = useState<"local" | "hpc">("local");
  const [casesFiles, setCasesFiles] = useState<CasesFile[]>([]);
  const [selectedSuffix, setSelectedSuffix] = useState("");
  const [availableCases, setAvailableCases] = useState<string[]>([]);
  const [selectedCases, setSelectedCases] = useState<string[]>([]);
  const [batchName, setBatchName] = useState(
    () => `v${new Date().toISOString().slice(0, 10).replace(/-/g, "")}_copilot`,
  );
  const [simultRuns, setSimultRuns] = useState(1);
  const [condaEnvs, setCondaEnvs] = useState<CondaEnv[]>([]);
  const [selectedEnv, setSelectedEnv] = useState("reeds2");

  /* Runs list & detail */
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [runFolders, setRunFolders] = useState<RunFolder[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<RunRecord | null>(null);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* Load cases files and conda envs on mount */
  useEffect(() => {
    listCasesFilesAPI()
      .then((files) => {
        setCasesFiles(files);
        // Default to 'small' or first
        const small = files.find((f) => f.suffix === "small");
        if (small) {
          setSelectedSuffix(small.suffix);
          setAvailableCases(small.cases);
          setSelectedCases(small.cases);
        } else if (files.length > 0) {
          setSelectedSuffix(files[0].suffix);
          setAvailableCases(files[0].cases);
          setSelectedCases(files[0].cases);
        }
      })
      .catch(() => {});
    listCondaEnvsAPI()
      .then((envs) => {
        setCondaEnvs(envs);
        // Auto-select reeds2 if available
        const r2 = envs.find((e) => e.name === "reeds2");
        if (r2) setSelectedEnv(r2.name);
        else if (envs.length > 0) setSelectedEnv(envs[0].name);
      })
      .catch(() => {});
    refreshRuns();
  }, []);

  /* Poll for running jobs */
  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === "running" || r.status === "queued");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(refreshRuns, 5000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runs]);

  function refreshRuns() {
    listRunsAPI().then(setRuns).catch(() => {});
    listRunFoldersAPI().then(setRunFolders).catch(() => {});
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

  async function handleLaunch() {
    if (!batchName.trim()) {
      setError("Batch name is required");
      return;
    }
    if (target === "hpc") {
      setError("HPC runs are not yet supported. Coming soon!");
      return;
    }
    setError("");
    setLaunching(true);
    try {
      await startRunAPI({
        batch_name: batchName.trim(),
        cases_suffix: selectedSuffix,
        cases: selectedCases.length > 0 ? selectedCases : undefined,
        simult_runs: simultRuns,
        target,
        conda_env: selectedEnv,
      });
      refreshRuns();
    } catch (e: any) {
      setError(e.message ?? "Failed to start run");
    } finally {
      setLaunching(false);
    }
  }

  async function handleCancel(id: string) {
    await cancelRunAPI(id).catch(() => {});
    refreshRuns();
  }

  async function handleDelete(id: string) {
    await deleteRunAPI(id).catch(() => {});
    refreshRuns();
  }

  async function toggleExpand(id: string) {
    if (expandedRun === id) {
      setExpandedRun(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedRun(id);
    try {
      const d = await getRunAPI(id);
      setExpandedDetail(d);
    } catch {
      setExpandedDetail(null);
    }
  }

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <div className="run-panel">
      {/* ── Launch form ───────────────────────────────────────────────────── */}
      <section className="run-form">
        <h2>Launch ReEDS Run</h2>

        {/* Target selector */}
        <div className="run-field">
          <label>Run Target</label>
          <div className="run-target-toggle">
            <button
              className={target === "local" ? "active" : ""}
              onClick={() => setTarget("local")}
            >
              💻 Local
            </button>
            <button
              className={target === "hpc" ? "active" : ""}
              onClick={() => setTarget("hpc")}
            >
              🖥️ HPC
              <span className="coming-soon">soon</span>
            </button>
          </div>
        </div>

        {/* Conda environment */}
        <div className="run-field">
          <label>Conda Environment</label>
          <select
            value={selectedEnv}
            onChange={(e) => setSelectedEnv(e.target.value)}
          >
            {condaEnvs.length === 0 && (
              <option value="reeds2">reeds2 (default)</option>
            )}
            {condaEnvs.map((env) => (
              <option key={env.name} value={env.name}>
                {env.name}{env.name === "reeds2" ? " (recommended)" : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Batch name */}
        <div className="run-field">
          <label>Batch Name</label>
          <input
            type="text"
            value={batchName}
            onChange={(e) => setBatchName(e.target.value)}
            placeholder="v20260424_test"
          />
        </div>

        {/* Cases file selector */}
        <div className="run-field">
          <label>Cases File</label>
          <select
            value={selectedSuffix}
            onChange={(e) => handleSuffixChange(e.target.value)}
          >
            {casesFiles.map((f) => (
              <option key={f.suffix} value={f.suffix}>
                {f.filename} ({f.cases.length} case{f.cases.length !== 1 ? "s" : ""})
              </option>
            ))}
          </select>
        </div>

        {/* Case selection */}
        {availableCases.length > 0 && (
          <div className="run-field">
            <label>
              Cases to Run
              <span className="run-field-hint">
                {selectedCases.length}/{availableCases.length} selected
              </span>
            </label>
            <div className="case-chips">
              {availableCases.map((c) => (
                <button
                  key={c}
                  className={`case-chip ${selectedCases.includes(c) ? "selected" : ""}`}
                  onClick={() => toggleCase(c)}
                  title={c}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Simultaneous runs */}
        <div className="run-field">
          <label>Simultaneous Runs</label>
          <input
            type="number"
            min={1}
            max={32}
            value={simultRuns}
            onChange={(e) => setSimultRuns(Math.max(1, +e.target.value))}
            style={{ width: 80 }}
          />
        </div>

        {error && <div className="run-error">{error}</div>}

        <button
          className="run-launch-btn"
          onClick={handleLaunch}
          disabled={launching || target === "hpc"}
        >
          {launching ? "Launching…" : "🚀 Launch Run"}
        </button>
      </section>

      {/* ── Run history ───────────────────────────────────────────────────── */}
      <section className="run-history">
        <div className="run-history-header">
          <h2>Run History</h2>
          <button className="run-refresh-btn" onClick={refreshRuns} title="Refresh">
            ↻
          </button>
        </div>

        {runs.length === 0 && (
          <p className="run-empty">No runs yet. Launch one above!</p>
        )}

        {runs.map((r) => (
          <div key={r.id} className={`run-card ${r.status}`}>
            <div className="run-card-header" onClick={() => toggleExpand(r.id)}>
              <div className="run-card-title">
                <strong>{r.batch_name}</strong>
                <span className="run-card-suffix">
                  cases_{r.cases_suffix}.csv
                </span>
              </div>
              <div className="run-card-meta">
                {statusBadge(r.status)}
                <span className="run-card-time">{fmtTime(r.created_at)}</span>
              </div>
            </div>

            {/* Actions */}
            <div className="run-card-actions">
              {(r.status === "running" || r.status === "queued") && (
                <button
                  className="run-action cancel"
                  onClick={() => handleCancel(r.id)}
                >
                  Cancel
                </button>
              )}
              {r.status !== "running" && r.status !== "queued" && (
                <button
                  className="run-action delete"
                  onClick={() => handleDelete(r.id)}
                >
                  Delete
                </button>
              )}
            </div>

            {/* Expanded detail */}
            {expandedRun === r.id && expandedDetail && (
              <div className="run-detail">
                <div className="run-detail-row">
                  <span>Cases:</span>
                  <span>{expandedDetail.cases.join(", ") || "all"}</span>
                </div>
                <div className="run-detail-row">
                  <span>Workers:</span>
                  <span>{expandedDetail.simult_runs}</span>
                </div>
                {expandedDetail.error && (
                  <div className="run-detail-row error">
                    <span>Error:</span>
                    <span>{expandedDetail.error}</span>
                  </div>
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

      {/* ── Run Folders (from repo/runs/) ─────────────────────────────────── */}
      <section className="run-folders">
        <div className="run-history-header">
          <h2>Run Folders <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", fontWeight: 400 }}>({runFolders.length} in runs/)</span></h2>
        </div>

        {runFolders.length === 0 && (
          <p className="run-empty">No run folders found in runs/ directory.</p>
        )}

        <div className="run-folder-list">
          {runFolders.map((f) => (
            <div key={f.name} className="run-folder-item">
              <div className="run-folder-name">📁 {f.name}</div>
              <div className="run-folder-badges">
                {f.has_outputs && <span className="folder-badge outputs">outputs</span>}
                {f.has_gamslog && <span className="folder-badge log">gamslog</span>}
                {f.has_meta && <span className="folder-badge meta">meta</span>}
                <span className="run-card-time">
                  {new Date(f.modified_at * 1000).toLocaleString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
