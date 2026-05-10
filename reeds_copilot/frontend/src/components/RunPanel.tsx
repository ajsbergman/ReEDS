import { useEffect, useRef, useState } from "react";
import {
  listCasesFilesAPI,
  listCondaEnvsAPI,
  envCheckAPI,
  envFixAPI,
  getGamsLicenseAPI,
  saveGamsLicenseAPI,
  startRunAPI,
  listRunsAPI,
  getRunAPI,
  cancelRunAPI,
  deleteRunAPI,
  type CasesFile,
  type CondaEnv,
  type RunRecord,
  type EnvCheckResult,
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

  /* Environment checks */
  const [envChecks, setEnvChecks] = useState<EnvCheckResult[]>([]);
  const [envLoading, setEnvLoading] = useState(false);
  const [fixing, setFixing] = useState<string | null>(null);
  const [fixMsg, setFixMsg] = useState("");

  /* GAMS license */
  const [showLicenseInput, setShowLicenseInput] = useState(false);
  const [licenseText, setLicenseText] = useState("");
  const [licenseSaving, setLicenseSaving] = useState(false);

  /* HPC connection */
  const [hpcCluster, setHpcCluster] = useState<"kestrel" | "eagle" | "custom">("kestrel");
  const [hpcHost, setHpcHost] = useState("kestrel.hpc.nrel.gov");
  const [hpcUser, setHpcUser] = useState("");
  const [hpcReedsPath, setHpcReedsPath] = useState("");

  /* HPC / Slurm config */
  const [slurmAccount, setSlurmAccount] = useState("");
  const [slurmWalltime, setSlurmWalltime] = useState("2-00:00:00");
  const [slurmPartition, setSlurmPartition] = useState("");
  const [slurmMemory, setSlurmMemory] = useState("246000");

  /* Runs list & detail */
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<RunRecord | null>(null);
  const [launching, setLaunching] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
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
    runEnvChecks("reeds2");
  }, []);

  /* Re-run env checks when conda env changes */
  function runEnvChecks(env: string) {
    setEnvLoading(true);
    envCheckAPI(env)
      .then(setEnvChecks)
      .catch(() => {})
      .finally(() => setEnvLoading(false));
  }

  async function handleFix(checkName: string) {
    // For gams_license, show the license input instead of calling env-fix
    if (checkName === "gams_license") {
      // Load existing content if any
      try {
        const lic = await getGamsLicenseAPI();
        setLicenseText(lic.content || "");
      } catch { /* ignore */ }
      setShowLicenseInput(true);
      return;
    }
    setFixing(checkName);
    setFixMsg("");
    try {
      const res = await envFixAPI(checkName, selectedEnv);
      setFixMsg(res.detail || (res.ok ? "Fixed!" : "Fix attempted"));
      // Re-check after a short delay (background tasks need time)
      setTimeout(() => runEnvChecks(selectedEnv), 2000);
    } catch (e: any) {
      setFixMsg(e.message || "Fix request failed");
    } finally {
      setFixing(null);
    }
  }

  async function handleSaveLicense() {
    setLicenseSaving(true);
    try {
      await saveGamsLicenseAPI(licenseText);
      setShowLicenseInput(false);
      runEnvChecks(selectedEnv);
    } catch {
      // ignore
    } finally {
      setLicenseSaving(false);
    }
  }

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
    // Also refresh expanded run detail (log + status)
    if (expandedRun) {
      getRunAPI(expandedRun).then(setExpandedDetail).catch(() => {});
    }
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
    if (target === "hpc" && !slurmAccount.trim()) {
      setError("Slurm account (allocation) is required for HPC runs");
      return;
    }
    if (target === "hpc" && !hpcHost.trim()) {
      setError("HPC login node is required");
      return;
    }
    if (target === "hpc" && !hpcUser.trim()) {
      setError("HPC username is required");
      return;
    }
    if (target === "hpc" && !hpcReedsPath.trim()) {
      setError("Remote ReEDS path on the HPC is required");
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
        overwrite,
        ...(target === "hpc" && {
          hpc_host: hpcHost.trim(),
          hpc_user: hpcUser.trim(),
          hpc_reeds_path: hpcReedsPath.trim(),
          slurm_account: slurmAccount.trim(),
          slurm_walltime: slurmWalltime.trim(),
          slurm_partition: slurmPartition.trim() || undefined,
          slurm_memory: slurmMemory.trim(),
        }),
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

        {/* Conda environment */}
        <div className="run-field">
          <label>Conda Environment</label>
          <select
            value={selectedEnv}
            onChange={(e) => { setSelectedEnv(e.target.value); runEnvChecks(e.target.value); }}
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

        {/* Environment health checks */}
        <div className="env-checks">
          <div className="env-checks-header">
            <label>Environment Status</label>
            <button
              className="env-recheck-btn"
              onClick={() => runEnvChecks(selectedEnv)}
              disabled={envLoading}
              title="Re-check"
            >
              {envLoading ? "⏳" : "↻"}
            </button>
          </div>
          {envChecks.length === 0 && !envLoading && (
            <span className="env-check-empty">Click ↻ to check environment</span>
          )}
          {fixMsg && (
            <div className="fix-msg">{fixMsg}</div>
          )}
          {envChecks.map((c) => (
            <div key={c.name} className={`env-check-row ${c.ok ? "pass" : "fail"}`}>
              <span className="env-check-icon">{c.ok ? "✅" : "❌"}</span>
              <span className="env-check-label">{c.label}</span>
              <span className="env-check-detail">{c.detail}</span>
              {!c.ok && c.fixable && (
                <button
                  className="env-fix-btn"
                  onClick={() => handleFix(c.name)}
                  disabled={fixing === c.name}
                >
                  {c.name === "gams_license"
                    ? "📝 Enter License"
                    : fixing === c.name
                      ? "Fixing…"
                      : "🔧 Fix"}
                </button>
              )}
            </div>
          ))}

          {/* GAMS license input panel */}
          {showLicenseInput && (
            <div className="license-input-panel">
              <label>Paste your GAMS license (gamslice.txt content):</label>
              <textarea
                className="license-textarea"
                value={licenseText}
                onChange={(e) => setLicenseText(e.target.value)}
                placeholder={"Paste your GAMS license lines here...\nExample:\n12345678\nYour Name\nYour Company\n..."}
                rows={8}
              />
              <div className="license-actions">
                <button
                  className="license-save-btn"
                  onClick={handleSaveLicense}
                  disabled={licenseSaving || !licenseText.trim()}
                >
                  {licenseSaving ? "Saving…" : "💾 Save License"}
                </button>
                <button
                  className="license-cancel-btn"
                  onClick={() => setShowLicenseInput(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Batch name (original) */}
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
              <span className="case-select-btns">
                <button onClick={() => setSelectedCases([...availableCases])}>All</button>
                <button onClick={() => setSelectedCases([])}>None</button>
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

        <label className="run-overwrite-toggle">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
          />
          Overwrite existing run folders
        </label>

        {error && <div className="run-error">{error}</div>}

        <button
          className="run-launch-btn"
          onClick={handleLaunch}
          disabled={launching}
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
                {r.target === "hpc" && (
                  <span style={{
                    fontSize: "0.7rem", padding: "1px 6px", borderRadius: 3,
                    background: "#7c4dff", color: "#fff", fontWeight: 600, marginRight: 4,
                  }}>HPC</span>
                )}
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
                {expandedDetail.target === "hpc" && expandedDetail.slurm_job_ids?.length > 0 && (
                  <div className="run-detail-row">
                    <span>Slurm Jobs:</span>
                    <span>{expandedDetail.slurm_job_ids.join(", ")}</span>
                  </div>
                )}
                {expandedDetail.target === "hpc" && (
                  <div className="run-detail-row">
                    <span>Target:</span>
                    <span>HPC (Slurm)</span>
                  </div>
                )}
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
    </div>
  );
}
