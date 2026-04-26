import { useEffect, useState, useCallback } from "react";
import {
  listRunFoldersAPI,
  ppListReportsAPI,
  ppRunBokehReportAPI,
  ppListJobsAPI,
  ppGetJobAPI,
  ppListOutputsAPI,
  rawFileURL,
  downloadFileURL,
  type RunFolder,
  type PPJob,
  type PPOutputFile,
} from "../lib/api";

interface Props {
  onClose: () => void;
  onSelectFile: (path: string) => void;
}

const CASE_COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c"];

export default function PostProcessPanel({ onClose, onSelectFile }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [reports, setReports] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Tool config
  const [bpreport, setBpreport] = useState("standard_report_reduced");
  const [diff, setDiff] = useState(true);
  const [basecase, setBasecase] = useState("");

  // Jobs
  const [jobs, setJobs] = useState<PPJob[]>([]);
  const [activeJob, setActiveJob] = useState<PPJob | null>(null);
  const [jobOutputs, setJobOutputs] = useState<PPOutputFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRunFoldersAPI().then(setFolders).catch(() => {});
    ppListReportsAPI().then((r) => setReports(r.reports)).catch(() => {});
    ppListJobsAPI().then((r) => setJobs(r.jobs)).catch(() => {});
  }, []);

  // Poll active job
  useEffect(() => {
    if (!activeJob || activeJob.status === "completed" || activeJob.status === "failed") return;
    const interval = setInterval(() => {
      ppGetJobAPI(activeJob.id).then((j) => {
        setActiveJob(j);
        setJobs((prev) => prev.map((p) => (p.id === j.id ? j : p)));
        if (j.status === "completed" || j.status === "failed") {
          ppListOutputsAPI(j.id).then((r) => setJobOutputs(r.files)).catch(() => {});
        }
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(interval);
  }, [activeJob]);

  function toggleCase(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const submit = useCallback(async () => {
    if (selected.size < 1) return;
    setSubmitting(true);
    setError(null);
    try {
      const cases = Array.from(selected);
      let res: { job_id: string };
      res = await ppRunBokehReportAPI({
        cases,
        report: bpreport,
        diff,
        basecase: basecase || cases[0],
      });
      const job = await ppGetJobAPI(res.job_id);
      setActiveJob(job);
      setJobs((prev) => [job, ...prev]);
      setJobOutputs([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [selected, basecase, bpreport, diff]);

  function viewJob(job: PPJob) {
    setActiveJob(job);
    if (job.status === "completed" || job.status === "failed") {
      ppListOutputsAPI(job.id).then((r) => setJobOutputs(r.files)).catch(() => {});
    } else {
      setJobOutputs([]);
    }
  }

  const selectedArr = Array.from(selected);
  const showConfig = !activeJob;

  return (
    <div className="compare-panel">
      {/* Header */}
      <div className="compare-header">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {activeJob && (
            <button className="btn btn-outline" onClick={() => { setActiveJob(null); setJobOutputs([]); }}
              style={{ fontSize: "0.78rem", padding: "3px 8px" }}>← Back</button>
          )}
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Post-Processing Tools</h3>
        </div>
        <button className="btn btn-outline" onClick={onClose} style={{ fontSize: "0.78rem", padding: "3px 8px" }}>
          ✕ Close
        </button>
      </div>

      {error && <div className="error-banner" style={{ margin: "8px 0" }}>{error}</div>}

      {/* ── Config + Submit ── */}
      {showConfig && (
        <>
          {/* Tool description */}
          <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", margin: "0 0 8px" }}>
            Runs a bokehpivot report template — generates interactive HTML + Excel.
          </p>

          {/* Case selection */}
          <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: 4 }}>
            Select Cases ({selected.size} selected)
          </div>
          <div className="compare-case-list" style={{ maxHeight: "25vh" }}>
            {folders.map((f) => (
              <label key={f.name} className="compare-case-item">
                <input type="checkbox" checked={selected.has(f.name)} onChange={() => toggleCase(f.name)} />
                <span className="compare-case-name">{f.name}</span>
              </label>
            ))}
          </div>

          {/* Base case */}
          {selected.size >= 1 && (
            <div style={{ marginTop: 8 }}>
              <label style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                Base case:
                <select value={basecase || selectedArr[0]}
                  onChange={(e) => setBasecase(e.target.value)}
                  style={{
                    marginLeft: 6, fontSize: "0.78rem", padding: "2px 6px",
                    background: "var(--bg-input, #23272e)", color: "var(--text-primary)",
                    border: "1px solid var(--border)", borderRadius: 4,
                  }}>
                  {selectedArr.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            </div>
          )}

          {/* Tool-specific options */}
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontSize: "0.78rem" }}>
            <label style={{ color: "var(--text-muted)" }}>
              Report template:
              <select value={bpreport} onChange={(e) => setBpreport(e.target.value)}
                style={{
                  marginLeft: 6, fontSize: "0.78rem", padding: "2px 6px",
                  background: "var(--bg-input, #23272e)", color: "var(--text-primary)",
                  border: "1px solid var(--border)", borderRadius: 4,
                }}>
                {reports.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", color: "var(--text-muted)" }}>
              <input type="checkbox" checked={diff} onChange={() => setDiff((v) => !v)}
                style={{ accentColor: "var(--accent)" }} />
              Include diff plots
            </label>
          </div>

          {/* Submit */}
          {selected.size >= 1 && (
            <button className="btn" disabled={submitting}
              style={{ marginTop: 12, width: "100%", padding: "8px", fontSize: "0.88rem" }}
              onClick={submit}>
              {submitting ? "Submitting…" : "Run Bokeh Report →"}
            </button>
          )}

          {/* Job history */}
          {jobs.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: 6 }}>Recent Jobs</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {jobs.map((j) => (
                  <div key={j.id} onClick={() => viewJob(j)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "5px 8px",
                      background: "var(--bg-elevated)", borderRadius: "var(--radius)",
                      cursor: "pointer", fontSize: "0.78rem",
                    }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                      background: j.status === "completed" ? "#4ade80"
                        : j.status === "failed" ? "#f87171"
                        : j.status === "running" ? "#fbbf24"
                        : "var(--text-muted)",
                    }} />
                    <span style={{ flex: 1, fontFamily: "var(--font-mono)" }}>
                      {j.type === "compare_cases" ? "Compare" : "Bokeh"} · {j.cases.join(", ")}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontSize: "0.72rem" }}>
                      {j.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Active Job View ── */}
      {activeJob && (
        <div>
          {/* Job header */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <span style={{
              width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
              background: activeJob.status === "completed" ? "#4ade80"
                : activeJob.status === "failed" ? "#f87171"
                : activeJob.status === "running" ? "#fbbf24"
                : "var(--text-muted)",
            }} />
            <strong style={{ fontSize: "0.88rem" }}>
              {activeJob.type === "compare_cases" ? "Compare Cases" : "Bokeh Report"}
            </strong>
            <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
              {activeJob.status}
              {activeJob.report && ` · ${activeJob.report}`}
            </span>
          </div>
          <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
            {activeJob.cases.map((c, i) => (
              <span key={c} className="compare-case-badge" style={{
                background: CASE_COLORS[i % CASE_COLORS.length] + "20",
                color: CASE_COLORS[i % CASE_COLORS.length],
              }}>{c}</span>
            ))}
          </div>

          {/* Outputs */}
          {jobOutputs.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                Outputs
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {jobOutputs.filter((f) => f.suffix === ".html").map((f) => {
                  const isHtml = f.suffix === ".html";
                  const isViewable = [".html", ".png", ".jpg", ".csv", ".xlsx"].includes(f.suffix);
                  return (
                    <div key={f.rel_path} style={{
                      display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                      borderRadius: "var(--radius)", fontSize: "0.78rem",
                      fontFamily: "var(--font-mono)",
                    }}>
                      <span style={{ flex: 1, wordBreak: "break-all" }}>
                        {isHtml ? "📊" : f.suffix === ".pptx" ? "📑" : f.suffix === ".xlsx" ? "📗" : "📄"}{" "}
                        {f.name}
                      </span>
                      {isHtml && (
                        <a href={rawFileURL(f.rel_path)} target="_blank" rel="noopener noreferrer"
                          className="btn btn-outline"
                          style={{ fontSize: "0.7rem", padding: "2px 6px", whiteSpace: "nowrap", color: "#fff" }}>
                          Open ↗
                        </a>
                      )}
                      {isViewable && !isHtml && (
                        <button className="btn btn-outline"
                          style={{ fontSize: "0.7rem", padding: "2px 6px" }}
                          onClick={() => onSelectFile(f.rel_path)}>
                          View
                        </button>
                      )}
                      <a href={downloadFileURL(f.rel_path)} download
                        className="btn btn-outline"
                        style={{ fontSize: "0.7rem", padding: "2px 6px", color: "#fff", borderColor: "#fff" }}>
                        ⬇
                      </a>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Log (collapsible) */}
          <details style={{ marginTop: 4 }}>
            <summary style={{ fontSize: "0.82rem", fontWeight: 600, cursor: "pointer", userSelect: "none" }}>
              Log
            </summary>
            <pre style={{
              background: "var(--bg)", padding: 8, borderRadius: "var(--radius)",
              fontSize: "0.72rem", fontFamily: "var(--font-mono)",
              maxHeight: "calc(100vh - 400px)", overflow: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-all",
              border: "1px solid var(--border)", marginTop: 4,
            }}>
              {activeJob.log || (activeJob.status === "running" ? "Running… (auto-refreshing)" : "(no output yet)")}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
