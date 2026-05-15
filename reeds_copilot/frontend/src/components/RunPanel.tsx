import { useEffect, useRef, useState } from "react";
import {
  listCasesFilesAPI,
  listHpcCasesFilesAPI,
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
  hpcConnectAPI,
  listHpcCondaEnvsAPI,
  hpcEnvCheckAPI,
  hpcSqueueAPI,
  listHpcFilesAPI,
  type CasesFile,
  type CondaEnv,
  type RunRecord,
  type EnvCheckResult,
  type HpcEnvCheck,
  type SlurmJob,
  type FileEntry,
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
  const [hpcHost, setHpcHost] = useState("kestrel.hpc.nlr.gov");
  const [hpcUser, setHpcUser] = useState("");
  const [hpcPassword, setHpcPassword] = useState("");
  const [hpcReedsPath, setHpcReedsPath] = useState("");
  const [hpcConnected, setHpcConnected] = useState(false);
  const [hpcLoading, setHpcLoading] = useState(false);
  const [hpcLoginOk, setHpcLoginOk] = useState(false);
  const [hpcHome, setHpcHome] = useState("");
  const [hpcSuggestedPaths, setHpcSuggestedPaths] = useState<string[]>([]);
  const [hpcLoginError, setHpcLoginError] = useState("");

  /* HPC conda envs + env checks */
  const [hpcCondaEnvs, setHpcCondaEnvs] = useState<{ name: string; prefix: string }[]>([]);
  const [hpcSelectedEnv, setHpcSelectedEnv] = useState("reeds2");
  const [hpcEnvChecks, setHpcEnvChecks] = useState<HpcEnvCheck[]>([]);
  const [hpcEnvLoading, setHpcEnvLoading] = useState(false);

  /* HPC Slurm queue */
  const [slurmQueue, setSlurmQueue] = useState<SlurmJob[]>([]);

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
        // Default to 'test' (cases_test.csv), then 'small', then first
        const preferred =
          files.find((f) => f.suffix === "test") ||
          files.find((f) => f.suffix === "small") ||
          files[0];
        if (preferred) {
          setSelectedSuffix(preferred.suffix);
          setAvailableCases(preferred.cases);
          setSelectedCases(preferred.cases);
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
      } catch (e) {
        // Pre-fill failure is non-fatal — surface in fixMsg
        setFixMsg(
          "Could not load existing license: " +
            (e instanceof Error ? e.message : String(e)),
        );
      }
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
      const res = await saveGamsLicenseAPI(licenseText);
      if (res.ok) {
        setShowLicenseInput(false);
        setFixMsg(res.detail || "License saved.");
        runEnvChecks(selectedEnv);
      } else {
        setFixMsg(res.detail || "Failed to save license.");
      }
    } catch (e) {
      setFixMsg(
        "Failed to save license: " + (e instanceof Error ? e.message : String(e)),
      );
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
    // Refresh Slurm queue if HPC connected
    if (target === "hpc" && hpcLoginOk && hpcHost && hpcUser) {
      hpcSqueueAPI(hpcHost, hpcUser, hpcPassword)
        .then((r) => setSlurmQueue(r.jobs))
        .catch(() => {});
    }
  }

  // Auto-poll Slurm queue every 15s while on HPC tab
  useEffect(() => {
    if (target !== "hpc" || !hpcLoginOk) return;
    const tick = () => {
      hpcSqueueAPI(hpcHost, hpcUser, hpcPassword)
        .then((r) => setSlurmQueue(r.jobs))
        .catch(() => {});
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => clearInterval(id);
  }, [target, hpcLoginOk, hpcHost, hpcUser, hpcPassword]);

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
          hpc_password: hpcPassword,
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
      {/* ── Local / HPC tab toggle ────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 0, marginBottom: 10 }}>
        <button
          onClick={() => {
            setTarget("local");
            // Reload local cases
            listCasesFilesAPI().then((files) => {
              setCasesFiles(files);
              const preferred =
                files.find((f) => f.suffix === "test") ||
                files.find((f) => f.suffix === "small") ||
                files[0];
              if (preferred) {
                setSelectedSuffix(preferred.suffix);
                setAvailableCases(preferred.cases);
                setSelectedCases(preferred.cases);
              }
            }).catch(() => {});
          }}
          style={{
            flex: 1, padding: "10px 0", fontSize: "0.9rem", fontWeight: 600,
            border: "1px solid var(--border)", cursor: "pointer",
            borderRadius: "6px 0 0 6px",
            background: target === "local" ? "var(--accent)" : "var(--bg-secondary)",
            color: target === "local" ? "#fff" : "var(--text-muted)",
          }}
        >
          💻 Local
        </button>
        <button
          onClick={() => {
            setTarget("hpc");
            // Clear cases until user connects
            if (!hpcConnected) {
              setCasesFiles([]);
              setAvailableCases([]);
              setSelectedCases([]);
              setSelectedSuffix("");
            }
          }}
          style={{
            flex: 1, padding: "10px 0", fontSize: "0.9rem", fontWeight: 600,
            border: "1px solid var(--border)", borderLeft: "none", cursor: "pointer",
            borderRadius: "0 6px 6px 0",
            background: target === "hpc" ? "var(--accent)" : "var(--bg-secondary)",
            color: target === "hpc" ? "#fff" : "var(--text-muted)",
          }}
        >
          🖥️ HPC
        </button>
      </div>

      {/* ── Launch form ───────────────────────────────────────────────────── */}
      <section className="run-form">
        <h2>Launch ReEDS Run</h2>

        {/* ── Local-only: Conda environment + env checks ── */}
        {target === "local" && (
          <>
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
          </>
        )}

        {/* ── HPC: separated step blocks ── */}
        {target === "hpc" && (
          <HpcConfigBlocks
            hpcCluster={hpcCluster} setHpcCluster={setHpcCluster}
            hpcHost={hpcHost} setHpcHost={setHpcHost}
            hpcUser={hpcUser} setHpcUser={setHpcUser}
            hpcPassword={hpcPassword} setHpcPassword={setHpcPassword}
            hpcReedsPath={hpcReedsPath} setHpcReedsPath={setHpcReedsPath}
            hpcLoginOk={hpcLoginOk} setHpcLoginOk={setHpcLoginOk}
            hpcHome={hpcHome} setHpcHome={setHpcHome}
            hpcSuggestedPaths={hpcSuggestedPaths} setHpcSuggestedPaths={setHpcSuggestedPaths}
            hpcLoginError={hpcLoginError} setHpcLoginError={setHpcLoginError}
            hpcConnected={hpcConnected} setHpcConnected={setHpcConnected}
            hpcLoading={hpcLoading} setHpcLoading={setHpcLoading}
            casesFiles={casesFiles} setCasesFiles={setCasesFiles}
            setSelectedSuffix={setSelectedSuffix}
            setAvailableCases={setAvailableCases}
            setSelectedCases={setSelectedCases}
            hpcCondaEnvs={hpcCondaEnvs} setHpcCondaEnvs={setHpcCondaEnvs}
            hpcSelectedEnv={hpcSelectedEnv} setHpcSelectedEnv={setHpcSelectedEnv}
            hpcEnvChecks={hpcEnvChecks} setHpcEnvChecks={setHpcEnvChecks}
            hpcEnvLoading={hpcEnvLoading} setHpcEnvLoading={setHpcEnvLoading}
            slurmAccount={slurmAccount} setSlurmAccount={setSlurmAccount}
            slurmWalltime={slurmWalltime} setSlurmWalltime={setSlurmWalltime}
            slurmPartition={slurmPartition} setSlurmPartition={setSlurmPartition}
            slurmMemory={slurmMemory} setSlurmMemory={setSlurmMemory}
            setError={setError}
          />
        )}

        {/* Cases & launch — only show when local OR (HPC fully connected) */}
        {(target === "local" || hpcConnected) && (
        <div className="run-block-cases" style={target === "hpc" ? hpcBlockStyle : undefined}>
          {target === "hpc" && <h3 style={hpcBlockTitleStyle}>📋 5. Case Configuration & Launch</h3>}

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
        </div>
        )}
      </section>

      {/* ── Run history ───────────────────────────────────────────────────── */}
      <section className="run-history">
        <div className="run-history-header">
          <h2>Run History</h2>
          <button className="run-refresh-btn" onClick={refreshRuns} title="Refresh">
            ↻
          </button>
        </div>

        {/* Slurm live queue (HPC only) */}
        {target === "hpc" && hpcLoginOk && (
          <SlurmQueueWidget
            jobs={slurmQueue}
            onRefresh={() => {
              hpcSqueueAPI(hpcHost, hpcUser, hpcPassword)
                .then((r) => setSlurmQueue(r.jobs))
                .catch(() => {});
            }}
          />
        )}

        {runs.filter((r) => target === "hpc" ? r.target === "hpc" : r.target !== "hpc").length === 0 && (
          <p className="run-empty">No {target === "hpc" ? "HPC" : "local"} runs yet. Launch one above!</p>
        )}

        {runs.filter((r) => target === "hpc" ? r.target === "hpc" : r.target !== "hpc").map((r) => (
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

/* ─── HPC step-block helpers ──────────────────────────────────────────────── */

const hpcBlockStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: 14,
  marginBottom: 14,
  background: "var(--bg-secondary)",
};

const hpcBlockTitleStyle: React.CSSProperties = {
  margin: "0 0 10px 0",
  fontSize: "0.95rem",
  fontWeight: 600,
};

const stepDoneBadge = (ok: boolean) => (
  <span style={{
    marginLeft: 8, fontSize: "0.72rem", fontWeight: 600,
    color: ok ? "#4caf50" : "var(--text-muted)",
  }}>
    {ok ? "✅ done" : "⏳ pending"}
  </span>
);

interface HpcConfigBlocksProps {
  hpcCluster: "kestrel" | "eagle" | "custom";
  setHpcCluster: (v: "kestrel" | "eagle" | "custom") => void;
  hpcHost: string; setHpcHost: (v: string) => void;
  hpcUser: string; setHpcUser: (v: string) => void;
  hpcPassword: string; setHpcPassword: (v: string) => void;
  hpcReedsPath: string; setHpcReedsPath: (v: string) => void;
  hpcLoginOk: boolean; setHpcLoginOk: (v: boolean) => void;
  hpcHome: string; setHpcHome: (v: string) => void;
  hpcSuggestedPaths: string[]; setHpcSuggestedPaths: (v: string[]) => void;
  hpcLoginError: string; setHpcLoginError: (v: string) => void;
  hpcConnected: boolean; setHpcConnected: (v: boolean) => void;
  hpcLoading: boolean; setHpcLoading: (v: boolean) => void;
  casesFiles: CasesFile[]; setCasesFiles: (v: CasesFile[]) => void;
  setSelectedSuffix: (v: string) => void;
  setAvailableCases: (v: string[]) => void;
  setSelectedCases: (v: string[]) => void;
  hpcCondaEnvs: { name: string; prefix: string }[];
  setHpcCondaEnvs: (v: { name: string; prefix: string }[]) => void;
  hpcSelectedEnv: string; setHpcSelectedEnv: (v: string) => void;
  hpcEnvChecks: HpcEnvCheck[]; setHpcEnvChecks: (v: HpcEnvCheck[]) => void;
  hpcEnvLoading: boolean; setHpcEnvLoading: (v: boolean) => void;
  slurmAccount: string; setSlurmAccount: (v: string) => void;
  slurmWalltime: string; setSlurmWalltime: (v: string) => void;
  slurmPartition: string; setSlurmPartition: (v: string) => void;
  slurmMemory: string; setSlurmMemory: (v: string) => void;
  setError: (v: string) => void;
}

function HpcConfigBlocks(p: HpcConfigBlocksProps) {
  function handleLogin() {
    p.setError("");
    p.setHpcLoginError("");
    p.setHpcLoading(true);
    hpcConnectAPI(p.hpcHost, p.hpcUser, p.hpcPassword)
      .then((info) => {
        p.setHpcLoginOk(true);
        p.setHpcHome(info.home);
        p.setHpcSuggestedPaths(info.suggested_paths);
        // Auto-fill repo path if empty and we have a candidate
        if (!p.hpcReedsPath && info.suggested_paths[0]) {
          p.setHpcReedsPath(info.suggested_paths[0]);
        }
        // Also load conda envs
        listHpcCondaEnvsAPI(p.hpcHost, p.hpcUser, p.hpcPassword)
          .then((envs) => p.setHpcCondaEnvs(envs))
          .catch(() => {});
      })
      .catch((e) => {
        p.setHpcLoginOk(false);
        p.setHpcLoginError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => p.setHpcLoading(false));
  }

  function handleLoadRepo() {
    p.setError("");
    p.setHpcLoading(true);
    listHpcCasesFilesAPI(p.hpcHost, p.hpcUser, p.hpcReedsPath, p.hpcPassword)
      .then((files) => {
        p.setCasesFiles(files);
        p.setHpcConnected(true);
        const small = files.find((f) => f.suffix === "small");
        if (small) {
          p.setSelectedSuffix(small.suffix);
          p.setAvailableCases(small.cases);
          p.setSelectedCases(small.cases);
        } else if (files.length > 0) {
          p.setSelectedSuffix(files[0].suffix);
          p.setAvailableCases(files[0].cases);
          p.setSelectedCases(files[0].cases);
        }
      })
      .catch((e) => p.setError(e instanceof Error ? e.message : String(e)))
      .finally(() => p.setHpcLoading(false));
  }

  function handleEnvCheck() {
    p.setHpcEnvLoading(true);
    hpcEnvCheckAPI(p.hpcHost, p.hpcUser, p.hpcReedsPath, p.hpcSelectedEnv, p.hpcPassword)
      .then((r) => p.setHpcEnvChecks(r.checks))
      .catch(() => p.setHpcEnvChecks([]))
      .finally(() => p.setHpcEnvLoading(false));
  }

  return (
    <>
      {/* ── Block 1: HPC Login ── */}
      <div style={hpcBlockStyle}>
        <h3 style={hpcBlockTitleStyle}>
          🔐 1. HPC Login {stepDoneBadge(p.hpcLoginOk)}
        </h3>
        <div className="run-field">
          <label>HPC Cluster</label>
          <div style={{ display: "flex", gap: 6 }}>
            <select value={p.hpcCluster} onChange={(e) => {
              const v = e.target.value as "kestrel" | "eagle" | "custom";
              p.setHpcCluster(v);
              if (v === "kestrel") p.setHpcHost("kestrel.hpc.nlr.gov");
              else if (v === "eagle") p.setHpcHost("eagle.hpc.nlr.gov");
            }} style={{ width: 120 }}>
              <option value="kestrel">Kestrel</option>
              <option value="eagle">Eagle</option>
              <option value="custom">Custom</option>
            </select>
            <input type="text" value={p.hpcHost} onChange={(e) => p.setHpcHost(e.target.value)}
              placeholder="hostname" style={{ flex: 1 }} />
          </div>
        </div>
        <div className="run-field">
          <label>Username</label>
          <input type="text" value={p.hpcUser} onChange={(e) => p.setHpcUser(e.target.value)}
            placeholder="HPC username" autoComplete="username" />
        </div>
        <div className="run-field">
          <label>Password</label>
          <input type="password" value={p.hpcPassword} onChange={(e) => p.setHpcPassword(e.target.value)}
            placeholder="password" autoComplete="current-password" />
        </div>
        <button
          className="run-launch-btn"
          style={{ background: p.hpcLoginOk ? "#4caf50" : undefined }}
          disabled={p.hpcLoading || !p.hpcHost || !p.hpcUser || !p.hpcPassword}
          onClick={handleLogin}
        >
          {p.hpcLoading ? "Connecting…" : p.hpcLoginOk ? "✅ Logged in — Reconnect" : "🔌 Connect"}
        </button>
        {p.hpcLoginError && (
          <div className="run-error" style={{ marginTop: 8 }}>{p.hpcLoginError}</div>
        )}
        {p.hpcLoginOk && p.hpcHome && (
          <div style={{ marginTop: 8, fontSize: "0.78rem", color: "var(--text-muted)" }}>
            $HOME = <code>{p.hpcHome}</code>
          </div>
        )}
      </div>

      {/* ── Block 2: ReEDS repo root ── */}
      <div style={{ ...hpcBlockStyle, opacity: p.hpcLoginOk ? 1 : 0.5 }}>
        <h3 style={hpcBlockTitleStyle}>
          📁 2. ReEDS Repo Root {stepDoneBadge(p.hpcConnected)}
        </h3>
        {p.hpcSuggestedPaths.length > 0 && (
          <div style={{ marginBottom: 8, fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Suggested:{" "}
            {p.hpcSuggestedPaths.map((path) => (
              <button
                key={path}
                onClick={() => p.setHpcReedsPath(path)}
                style={{
                  margin: "2px 4px 2px 0", padding: "2px 8px",
                  background: "var(--bg)", border: "1px solid var(--border)",
                  borderRadius: 4, fontSize: "0.75rem", cursor: "pointer",
                  color: "var(--accent)",
                }}
              >
                {path}
              </button>
            ))}
          </div>
        )}
        <div className="run-field">
          <label>Remote ReEDS Path</label>
          <input type="text" value={p.hpcReedsPath} onChange={(e) => p.setHpcReedsPath(e.target.value)}
            placeholder="/projects/reeds/ReEDS" disabled={!p.hpcLoginOk} />
        </div>

        {/* Mini HPC file explorer */}
        {p.hpcLoginOk && (
          <MiniHpcExplorer
            host={p.hpcHost}
            user={p.hpcUser}
            password={p.hpcPassword}
            home={p.hpcHome}
            onPick={(path) => p.setHpcReedsPath(path)}
          />
        )}

        <button
          className="run-launch-btn"
          style={{ background: p.hpcConnected ? "#4caf50" : undefined }}
          disabled={p.hpcLoading || !p.hpcLoginOk || !p.hpcReedsPath}
          onClick={handleLoadRepo}
        >
          {p.hpcLoading ? "Loading…" : p.hpcConnected ? "✅ Loaded — Reload Cases" : "📂 Verify & Load Cases"}
        </button>
      </div>

      {/* ── Block 3: Conda env + status ── */}
      <div style={{ ...hpcBlockStyle, opacity: p.hpcConnected ? 1 : 0.5 }}>
        <h3 style={hpcBlockTitleStyle}>
          🐍 3. Conda Environment & Status {stepDoneBadge(p.hpcEnvChecks.length > 0 && p.hpcEnvChecks.every((c) => c.ok || c.name === "julia"))}
        </h3>
        <div className="run-field">
          <label>Conda Environment</label>
          <select value={p.hpcSelectedEnv}
            onChange={(e) => p.setHpcSelectedEnv(e.target.value)}
            disabled={!p.hpcConnected}>
            {p.hpcCondaEnvs.length === 0 && (
              <option value="reeds2">reeds2 (default)</option>
            )}
            {p.hpcCondaEnvs.map((env) => (
              <option key={env.name} value={env.name}>{env.name}</option>
            ))}
          </select>
        </div>
        <div className="env-checks">
          <div className="env-checks-header">
            <label>Environment Status</label>
            <button
              className="env-recheck-btn"
              onClick={handleEnvCheck}
              disabled={p.hpcEnvLoading || !p.hpcConnected}
              title="Re-check"
            >
              {p.hpcEnvLoading ? "⏳" : "↻"}
            </button>
          </div>
          {p.hpcEnvChecks.length === 0 && !p.hpcEnvLoading && (
            <span className="env-check-empty">Click ↻ to check the remote environment</span>
          )}
          {p.hpcEnvChecks.map((c) => (
            <div key={c.name} className={`env-check-row ${c.ok ? "pass" : "fail"}`}>
              <span className="env-check-icon">{c.ok ? "✅" : "❌"}</span>
              <span className="env-check-label">{c.label}</span>
              <span className="env-check-detail">{c.detail}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Block 4: Slurm config ── */}
      <div style={{ ...hpcBlockStyle, opacity: p.hpcConnected ? 1 : 0.5 }}>
        <h3 style={hpcBlockTitleStyle}>⚙️ 4. Slurm Configuration</h3>
        <div className="run-field">
          <label>Slurm Account (Allocation)</label>
          <input type="text" value={p.slurmAccount}
            onChange={(e) => p.setSlurmAccount(e.target.value)}
            placeholder="e.g. reeds" disabled={!p.hpcConnected} />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div className="run-field" style={{ flex: 1 }}>
            <label>Walltime</label>
            <input type="text" value={p.slurmWalltime}
              onChange={(e) => p.setSlurmWalltime(e.target.value)}
              placeholder="2-00:00:00" disabled={!p.hpcConnected} />
          </div>
          <div className="run-field" style={{ flex: 1 }}>
            <label>Partition</label>
            <input type="text" value={p.slurmPartition}
              onChange={(e) => p.setSlurmPartition(e.target.value)}
              placeholder="(default)" disabled={!p.hpcConnected} />
          </div>
          <div className="run-field" style={{ flex: 1 }}>
            <label>Memory (MB)</label>
            <input type="text" value={p.slurmMemory}
              onChange={(e) => p.setSlurmMemory(e.target.value)}
              placeholder="246000" disabled={!p.hpcConnected} />
          </div>
        </div>
      </div>
    </>
  );
}

/* ─── Slurm queue widget ──────────────────────────────────────────────────── */

function SlurmQueueWidget({ jobs, onRefresh }: { jobs: SlurmJob[]; onRefresh: () => void }) {
  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: 8,
      padding: 12, marginBottom: 14, background: "var(--bg-secondary)",
    }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ flex: 1 }}>📡 Slurm Queue (squeue -u $USER)</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.78rem", marginRight: 8 }}>
          auto-refresh every 15s
        </span>
        <button className="run-refresh-btn" onClick={onRefresh} title="Refresh">↻</button>
      </div>
      {jobs.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          No active Slurm jobs.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "var(--text-muted)" }}>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Job ID</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Name</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>State</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Elapsed</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Limit</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Reason / Node</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "4px 8px", color: "var(--accent)" }}>{j.job_id}</td>
                  <td style={{ padding: "4px 8px" }}>{j.name}</td>
                  <td style={{ padding: "4px 8px", fontWeight: 600,
                    color: j.state === "RUNNING" ? "#4caf50"
                      : j.state === "PENDING" ? "#ff9800" : undefined }}>
                    {j.state}
                  </td>
                  <td style={{ padding: "4px 8px" }}>{j.elapsed}</td>
                  <td style={{ padding: "4px 8px" }}>{j.limit}</td>
                  <td style={{ padding: "4px 8px" }}>{j.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─── Mini HPC file explorer (used inside Block 2) ───────────────────────── */

function MiniHpcExplorer({
  host, user, password, home, onPick,
}: {
  host: string; user: string; password: string; home: string;
  onPick: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [cwd, setCwd] = useState<string>(home || "/");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasReeds, setHasReeds] = useState(false);

  // Reset cwd when home becomes available
  useEffect(() => {
    if (open && home && cwd === "/") setCwd(home);
  }, [open, home]);

  // Fetch directory whenever cwd changes (only while open)
  useEffect(() => {
    if (!open || !host || !user) return;
    setLoading(true);
    setError("");
    listHpcFilesAPI(host, user, cwd, password)
      .then((r) => {
        // Only show directories (folders) — this is a folder picker
        const dirs = r.entries.filter((e) => e.is_dir);
        setEntries(dirs);
        // Detect whether current dir IS a ReEDS repo
        const all = r.entries;
        const hasCases = all.some((e) => e.name === "cases.csv" && !e.is_dir);
        const hasRunbatch = all.some((e) => e.name === "runbatch.py" && !e.is_dir);
        setHasReeds(hasCases && hasRunbatch);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setEntries([]);
        setHasReeds(false);
      })
      .finally(() => setLoading(false));
  }, [open, cwd, host, user, password]);

  function goUp() {
    if (cwd === "/" || !cwd) return;
    const parent = cwd.replace(/\/+$/, "").split("/").slice(0, -1).join("/") || "/";
    setCwd(parent);
  }

  function enter(name: string) {
    const next = cwd.endsWith("/") ? `${cwd}${name}` : `${cwd}/${name}`;
    setCwd(next);
  }

  // Path breadcrumb (clickable)
  const segments = cwd === "/" ? [""] : cwd.split("/");
  const crumbs = segments.map((seg, i) => {
    const path = i === 0 ? "/" : segments.slice(0, i + 1).join("/");
    return { label: seg || "/", path };
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        style={{
          width: "100%", padding: "6px 10px", marginBottom: 8,
          background: "var(--bg)", border: "1px dashed var(--border)",
          borderRadius: 4, fontSize: "0.78rem", cursor: "pointer",
          color: "var(--accent)", textAlign: "left",
        }}
      >
        🗂️ Browse HPC filesystem to pick a folder…
      </button>
    );
  }

  return (
    <div style={{
      marginBottom: 10, border: "1px solid var(--border)", borderRadius: 6,
      background: "var(--bg)", overflow: "hidden",
    }}>
      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "6px 8px", background: "var(--bg-elevated)",
        borderBottom: "1px solid var(--border)", fontSize: "0.78rem",
      }}>
        <button
          type="button" onClick={goUp} disabled={cwd === "/" || loading}
          title="Up one level"
          style={{
            padding: "2px 8px", background: "transparent",
            border: "1px solid var(--border)", borderRadius: 3,
            color: "var(--text-muted)", cursor: cwd === "/" ? "default" : "pointer",
          }}
        >
          ⬆
        </button>
        {home && (
          <button
            type="button" onClick={() => setCwd(home)}
            title="Go to $HOME"
            style={{
              padding: "2px 8px", background: "transparent",
              border: "1px solid var(--border)", borderRadius: 3,
              color: "var(--text-muted)", cursor: "pointer",
            }}
          >
            🏠
          </button>
        )}
        <div style={{ flex: 1, overflowX: "auto", whiteSpace: "nowrap" }}>
          {crumbs.map((c, i) => (
            <span key={i}>
              {i > 0 && <span style={{ color: "var(--text-muted)" }}>/</span>}
              <button
                type="button"
                onClick={() => setCwd(c.path)}
                style={{
                  padding: "1px 4px", background: "transparent", border: "none",
                  color: i === crumbs.length - 1 ? "var(--accent)" : "var(--text-muted)",
                  cursor: "pointer", fontFamily: "monospace", fontSize: "0.78rem",
                }}
              >
                {c.label || "/"}
              </button>
            </span>
          ))}
        </div>
        <button
          type="button" onClick={() => setOpen(false)} title="Close explorer"
          style={{
            padding: "2px 8px", background: "transparent",
            border: "1px solid var(--border)", borderRadius: 3,
            color: "var(--text-muted)", cursor: "pointer",
          }}
        >
          ✕
        </button>
      </div>

      {/* Directory listing */}
      <div style={{
        maxHeight: 200, overflowY: "auto", padding: "4px 0",
        fontSize: "0.8rem",
      }}>
        {loading && (
          <div style={{ padding: "8px 12px", color: "var(--text-muted)" }}>
            Loading…
          </div>
        )}
        {!loading && error && (
          <div style={{ padding: "8px 12px", color: "var(--danger)" }}>
            {error}
          </div>
        )}
        {!loading && !error && entries.length === 0 && (
          <div style={{ padding: "8px 12px", color: "var(--text-muted)" }}>
            (no subfolders)
          </div>
        )}
        {!loading && !error && entries.map((e) => (
          <div
            key={e.rel_path}
            onDoubleClick={() => enter(e.name)}
            onClick={() => enter(e.name)}
            style={{
              padding: "3px 12px", cursor: "pointer", display: "flex",
              alignItems: "center", gap: 6, fontFamily: "monospace",
            }}
            onMouseEnter={(ev) => (ev.currentTarget.style.background = "var(--bg-elevated)")}
            onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
          >
            <span>📁</span>
            <span>{e.name}</span>
          </div>
        ))}
      </div>

      {/* Footer: pick this folder */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 8px", background: "var(--bg-elevated)",
        borderTop: "1px solid var(--border)",
      }}>
        {hasReeds && (
          <span style={{ color: "#4caf50", fontSize: "0.75rem" }}>
            ✅ ReEDS repo detected
          </span>
        )}
        {!hasReeds && !loading && (
          <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>
            cases.csv / runbatch.py not found here
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => { onPick(cwd); setOpen(false); }}
          disabled={!cwd}
          style={{
            padding: "4px 12px",
            background: hasReeds ? "var(--accent)" : "var(--bg)",
            border: "1px solid var(--accent)",
            borderRadius: 4, color: hasReeds ? "#fff" : "var(--accent)",
            fontSize: "0.78rem", fontWeight: 600, cursor: "pointer",
          }}
        >
          Use this folder
        </button>
      </div>
    </div>
  );
}
