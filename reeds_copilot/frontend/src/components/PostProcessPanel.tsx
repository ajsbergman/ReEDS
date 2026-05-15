import { useEffect, useState, useCallback } from "react";
import {
  listRunFoldersAPI,
  ppListReportsAPI,
  ppRunCompareCasesAPI,
  ppRunBokehReportAPI,
  ppListJobsAPI,
  ppGetJobAPI,
  ppDeleteJobAPI,
  ppListOutputsAPI,
  rawFileURL,
  downloadFileURL,
  pptxViewURL,
  type RunFolder,
  type PPJob,
  type PPOutputFile,
} from "../lib/api";

interface Props {
  onClose: () => void;
  onSelectFile: (path: string) => void;
  /** When provided, only run folders with these names appear in the picker. */
  filterRunNames?: string[];
  /** Optional banner shown above the picker. */
  banner?: string;
}

const CASE_COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c"];

type Tool = "bokeh_report" | "compare_cases";

export default function PostProcessPanel({ onClose, onSelectFile, filterRunNames, banner }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [reports, setReports] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Tool config
  const [tool, setTool] = useState<Tool>("bokeh_report");
  const [bpreport, setBpreport] = useState("standard_report_reduced");
  const [startyear, setStartyear] = useState(2010);
  const [diff, setDiff] = useState(true);
  const [detailed, setDetailed] = useState(false);
  const [basecase, setBasecase] = useState("");
  const [aliases, setAliases] = useState<Record<string, string>>({});

  // Jobs
  const [jobs, setJobs] = useState<PPJob[]>([]);
  const [activeJob, setActiveJob] = useState<PPJob | null>(null);
  const [jobOutputs, setJobOutputs] = useState<PPOutputFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRunFoldersAPI()
      .then((all) => {
        if (filterRunNames && filterRunNames.length > 0) {
          const allow = new Set(filterRunNames);
          setFolders(all.filter((f) => allow.has(f.name)));
        } else {
          setFolders(all);
        }
      })
      .catch(() => {});
    ppListReportsAPI().then((r) => setReports(r.reports)).catch(() => {});
    ppListJobsAPI().then((r) => setJobs(r.jobs)).catch(() => {});
  }, [filterRunNames]);

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
      // Build casenames string: comma-separated display names (only if any alias is set)
      const names = cases.map((c) => aliases[c]?.trim() || c);
      const hasAliases = cases.some((c) => aliases[c]?.trim() && aliases[c].trim() !== c);
      const casenames = hasAliases ? names.join(",") : "";
      let res: { job_id: string };
      if (tool === "compare_cases") {
        res = await ppRunCompareCasesAPI({
          cases,
          casenames,
          basecase: basecase || cases[0],
          startyear,
          skip_bokehpivot: true,
          detailed,
        });
      } else {
        res = await ppRunBokehReportAPI({
          cases,
          casenames,
          report: bpreport,
          diff,
          basecase: basecase || cases[0],
        });
      }
      const job = await ppGetJobAPI(res.job_id);
      setActiveJob(job);
      setJobs((prev) => [job, ...prev]);
      setJobOutputs([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [selected, tool, basecase, bpreport, diff, startyear, detailed, aliases]);

  function viewJob(job: PPJob) {
    setActiveJob(job);
    if (job.status === "completed" || job.status === "failed") {
      ppListOutputsAPI(job.id).then((r) => setJobOutputs(r.files)).catch(() => {});
    } else {
      setJobOutputs([]);
    }
  }

  function deleteJob(e: React.MouseEvent, job: PPJob) {
    e.stopPropagation();
    ppDeleteJobAPI(job.id)
      .then(() => {
        setJobs((prev) => prev.filter((j) => j.id !== job.id));
        if (activeJob?.id === job.id) {
          setActiveJob(null);
          setJobOutputs([]);
        }
      })
      .catch(() => {});
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

      {banner && (
        <div style={{
          background: "var(--bg-elev)", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", padding: "8px 12px", margin: "8px 0",
          fontSize: "0.82rem", lineHeight: 1.4,
        }}>{banner}</div>
      )}

      {error && <div className="error-banner" style={{ margin: "8px 0" }}>{error}</div>}

      {/* ── Config + Submit ── */}
      {showConfig && (
        <>
          {/* Tool selector */}
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <button className="btn"
              style={{
                flex: 1, fontSize: "0.8rem", padding: "6px",
                background: tool === "bokeh_report" ? "var(--accent)" : "transparent",
                color: tool === "bokeh_report" ? "#fff" : "var(--text-muted)",
                border: tool === "bokeh_report" ? "1px solid var(--accent)" : "1px solid var(--border)",
              }}
              onClick={() => setTool("bokeh_report")}>
              📈 Bokeh Report
            </button>
            <button className="btn"
              style={{
                flex: 1, fontSize: "0.8rem", padding: "6px",
                background: tool === "compare_cases" ? "var(--accent)" : "transparent",
                color: tool === "compare_cases" ? "#fff" : "var(--text-muted)",
                border: tool === "compare_cases" ? "1px solid var(--accent)" : "1px solid var(--border)",
              }}
              onClick={() => setTool("compare_cases")}>
              📊 Compare Cases
            </button>
          </div>

          <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", margin: "0 0 8px" }}>
            {tool === "bokeh_report"
              ? "Runs a bokehpivot report template — generates interactive HTML + Excel."
              : "Runs compare_cases.py — generates PPTX comparison slides + optional bokehpivot report."}
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

          {/* Base case + display names */}
          {selected.size >= 1 && (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
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

              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: 2 }}>Display names (optional):</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {selectedArr.map((c) => (
                  <div key={c} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.75rem" }}>
                    <span style={{ minWidth: 60, color: "var(--text-muted)", fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }} title={c}>{c}</span>
                    <span style={{ color: "var(--text-muted)" }}>→</span>
                    <input
                      type="text"
                      placeholder={c}
                      value={aliases[c] || ""}
                      onChange={(e) => setAliases((prev) => ({ ...prev, [c]: e.target.value }))}
                      style={{
                        flex: 1, fontSize: "0.75rem", padding: "2px 6px",
                        background: "var(--bg-input, #23272e)", color: "var(--text-primary)",
                        border: "1px solid var(--border)", borderRadius: 4,
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tool-specific options */}
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontSize: "0.78rem" }}>
            {tool === "bokeh_report" && (
              <>
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
              </>
            )}

            {tool === "compare_cases" && (
              <>
                <label style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--text-muted)" }}>
                  Start year:
                  <input type="number" value={startyear} onChange={(e) => setStartyear(Number(e.target.value))}
                    style={{
                      width: 60, marginLeft: 4, fontSize: "0.78rem", padding: "2px 4px",
                      background: "var(--bg-input, #23272e)", color: "var(--text-primary)",
                      border: "1px solid var(--border)", borderRadius: 4,
                    }} />
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", color: "var(--text-muted)" }}>
                  <input type="checkbox" checked={detailed} onChange={() => setDetailed((v) => !v)}
                    style={{ accentColor: "var(--accent)" }} />
                  Detailed plots
                </label>
              </>
            )}
          </div>

          {/* Submit */}
          {selected.size >= 1 && (
            <button className="btn" disabled={submitting}
              style={{ marginTop: 12, width: "100%", padding: "8px", fontSize: "0.88rem" }}
              onClick={submit}>
              {submitting ? "Submitting…" : tool === "compare_cases" ? "Run Compare Cases →" : "Run Bokeh Report →"}
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
                    <span style={{ flex: 1, fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {j.type === "compare_cases" ? "Compare" : "Bokeh"} · {j.cases.join(", ")}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontSize: "0.72rem", flexShrink: 0 }}>
                      {j.status}
                    </span>
                    {j.status !== "queued" && j.status !== "running" && (
                      <button
                        title="Delete job"
                        onClick={(e) => deleteJob(e, j)}
                        style={{
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--text-muted)", fontSize: "0.82rem", padding: "0 2px",
                          lineHeight: 1, flexShrink: 0,
                        }}>
                        ✕
                      </button>
                    )}
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
          {jobOutputs.filter((f) => [".html", ".pptx"].includes(f.suffix)).length > 0 ? (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                Outputs
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {jobOutputs.filter((f) => [".html", ".pptx"].includes(f.suffix)).map((f) => {
                  const isHtml = f.suffix === ".html";
                  const isPptx = f.suffix === ".pptx";
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
                      {isPptx && (
                        <a href={pptxViewURL(f.rel_path)} target="_blank" rel="noopener noreferrer"
                          className="btn btn-outline"
                          title="Render slides as PDF in a new tab (requires LibreOffice on the backend)"
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
          ) : activeJob.status === "failed" ? (
            <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", margin: "8px 0" }}>
              No output files generated — the script crashed before saving. Check the log for details.
            </p>
          ) : null}

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
