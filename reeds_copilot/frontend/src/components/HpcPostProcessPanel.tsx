import { useEffect, useMemo, useState } from "react";
import {
  listHpcRunFoldersAPI,
  runHpcPostProcessAPI,
  type RunFolder,
  type HpcPostProcessResult,
  type HpcScenarioRow,
} from "../lib/api";

interface Props {
  onClose: () => void;
  host: string;
  user: string;
  sessionToken: string;
  reedsPath: string;
  /** Initial tool to focus on. */
  initialTool?: "compare_cases" | "bokeh_report";
  /** Called with a remote path the user wants to open in the file browser. */
  onOpenRemotePath?: (path: string) => void;
}

const BOKEH_REPORTS = [
  "standard_report_reduced",
  "standard_report",
  "standard_report_expanded",
  "standard_report_combined",
  "standard_report_CCS",
  "standard_report_RE100",
  "gen_only_report",
  "opres_report",
  "state_report",
  "value_factor_report",
];

export default function HpcPostProcessPanel({
  onClose, host, user, sessionToken, reedsPath,
  initialTool = "compare_cases", onOpenRemotePath,
}: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [tool, setTool] = useState<"compare_cases" | "bokeh_report">(initialTool);
  const [report, setReport] = useState<string>(BOKEH_REPORTS[0]);
  const [bashPrefix, setBashPrefix] = useState<string>("module load conda && conda activate reeds2");
  const [extraArgs, setExtraArgs] = useState<string>("");
  const [basecase, setBasecase] = useState<string>("");
  const [skipBokeh, setSkipBokeh] = useState(true);
  const [includeDiff, setIncludeDiff] = useState(true);
  const [gdxDiff, setGdxDiff] = useState(false);

  // Editable per-case scenarios (label + color) — used by both tools for rename.
  // Keyed by case name; auto-synced with `selected`.
  const [scenarios, setScenarios] = useState<Record<string, { label: string; color: string }>>({});

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<HpcPostProcessResult | null>(null);

  // Load HPC run folders on mount / when path changes
  useEffect(() => {
    if (!reedsPath || !sessionToken) return;
    setLoading(true);
    setError(null);
    listHpcRunFoldersAPI(host, user, reedsPath, sessionToken)
      .then(setFolders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [host, user, reedsPath, sessionToken]);

  // Default colour palette for scenarios (matches backend default).
  const DEFAULT_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
  ];

  // Keep `scenarios` in sync with `selected` — auto-add new cases with
  // defaults, remove deselected ones, preserve user edits for kept cases.
  useEffect(() => {
    setScenarios((prev) => {
      const cases = Array.from(selected);
      const next: Record<string, { label: string; color: string }> = {};
      cases.forEach((c, i) => {
        next[c] = prev[c] ?? { label: c, color: DEFAULT_COLORS[i % DEFAULT_COLORS.length] };
      });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const filtered = useMemo(() => {
    if (!filter) return folders;
    const lo = filter.toLowerCase();
    return folders.filter((f) => f.name.toLowerCase().includes(lo));
  }, [folders, filter]);

  function toggle(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function selectAllVisible() {
    setSelected(new Set(filtered.map((f) => f.name)));
  }
  function clearAll() { setSelected(new Set()); }

  async function handleRun() {
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const cases = Array.from(selected);
      const scenariosArr: HpcScenarioRow[] | undefined =
        tool === "bokeh_report"
          ? cases.map((name) => ({
              name,
              label: scenarios[name]?.label ?? name,
              color: scenarios[name]?.color ?? "#1f77b4",
            }))
          : undefined;

      // Build extra args for compare_cases: --skipbp, --basecase, --casenames, --gdxdiff
      let finalExtraArgs = extraArgs;
      if (tool === "compare_cases") {
        if (skipBokeh) {
          finalExtraArgs = "--skipbp" + (finalExtraArgs ? " " + finalExtraArgs : "");
        }
        if (gdxDiff) {
          finalExtraArgs += " --gdxdiff";
        }
        const effectiveBase = basecase || cases[0];
        if (effectiveBase) {
          finalExtraArgs += ` --basecase ${effectiveBase}`;
        }
        // Casenames: comma-separated display names (from scenarios labels)
        const hasRenames = cases.some((c) => scenarios[c]?.label && scenarios[c].label !== c);
        if (hasRenames) {
          const names = cases.map((c) => (scenarios[c]?.label || c).replace(/,/g, " "));
          finalExtraArgs += ` --casenames ${names.join(",")}`;
        }
      }
      // For bokeh_report, pass --basecase via the base scenario label
      if (tool === "bokeh_report") {
        const effectiveBase = basecase || cases[0];
        // The backend uses the first scenario as the base in the bokeh command
        // Reorder scenarios so the base case comes first if it's not already
        if (effectiveBase && scenariosArr && scenariosArr[0]?.name !== effectiveBase) {
          const baseIdx = scenariosArr.findIndex((s) => s.name === effectiveBase);
          if (baseIdx > 0) {
            const [baseScen] = scenariosArr.splice(baseIdx, 1);
            scenariosArr.unshift(baseScen);
          }
        }
      }

      const res = await runHpcPostProcessAPI({
        host, user, session_token: sessionToken,
        reeds_path: reedsPath,
        tool,
        cases: tool === "bokeh_report" && scenariosArr
          ? scenariosArr.map((s) => s.name)
          : cases,
        report: tool === "bokeh_report" ? report : undefined,
        bash_prefix: bashPrefix,
        extra_args: finalExtraArgs.trim(),
        scenarios: scenariosArr,
        include_diff: tool === "bokeh_report" ? includeDiff : undefined,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const canRun = !running && selected.size >= 2 && !!reedsPath;

  return (
    <div className="compare-panel">
      <div className="compare-header">
        <h3 style={{ margin: 0, fontSize: "1rem" }}>
          {tool === "compare_cases" ? "⚖️ Compare Cases (HPC)" : "📊 Bokeh Report (HPC)"}
        </h3>
        <button
          className="cmp-btn cmp-btn-close"
          onClick={onClose}
          title="Close the post-processing panel and return to the file browser">
          <span style={{ fontSize: "0.95rem", lineHeight: 1 }}>✕</span> Close Post-Process
        </button>
      </div>

      <div style={{
        background: "var(--bg-elev)", border: "1px solid var(--border)",
        borderRadius: "var(--radius)", padding: "8px 12px", margin: "8px 0",
        fontSize: "0.82rem", lineHeight: 1.4,
      }}>
        Runs <code>{tool === "compare_cases" ? "compare_cases.py" : `bokeh interface_report_model.py → ${report}`}</code>{" "}
        directly on <strong>{host}</strong> via SSH. Output is written to{" "}
        <code>{reedsPath}/runs/&lt;first-case&gt;/outputs/comparisons/</code> on the cluster
        — open it in 📁 Browse files when done.
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Last-run result (shown at top so it's always visible without scrolling). */}
      {result && (
        <div style={{
          border: `1px solid ${result.exit_code === 0 ? "rgba(74, 222, 128, 0.45)" : "rgba(248, 113, 113, 0.45)"}`,
          borderRadius: "var(--radius)",
          padding: 10, margin: "8px 0",
          background: result.exit_code === 0 ? "rgba(74, 222, 128, 0.06)" : "rgba(248, 113, 113, 0.06)",
        }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
            <strong style={{ color: result.exit_code === 0 ? "#4ade80" : "#f87171" }}>
              {result.exit_code === 0 ? "✅ Success" : `❌ Exit ${result.exit_code}`}
            </strong>
            {onOpenRemotePath && (
              <button onClick={() => onOpenRemotePath(result.output_dir)}
                className="cmp-btn"
                title="Open this output directory in the HPC file browser">
                📁 Open output dir
              </button>
            )}
            <code style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
              {result.output_dir}
            </code>
          </div>
          {result.stderr && (
            <details open={result.exit_code !== 0} style={{ marginBottom: 4 }}>
              <summary style={{ cursor: "pointer", fontSize: "0.82rem", color: "#f87171" }}>
                stderr ({result.stderr.length} chars)
              </summary>
              <pre style={{
                background: "var(--bg)", padding: 8, borderRadius: 4,
                maxHeight: 200, overflow: "auto", fontSize: "0.78rem",
              }}>{result.stderr}</pre>
            </details>
          )}
          <details>
            <summary style={{ cursor: "pointer", fontSize: "0.82rem" }}>
              stdout ({result.stdout.length} chars)
            </summary>
            <pre style={{
              background: "var(--bg)", padding: 8, borderRadius: 4,
              maxHeight: 360, overflow: "auto", fontSize: "0.78rem",
            }}>{result.stdout}</pre>
          </details>
          <details>
            <summary style={{ cursor: "pointer", fontSize: "0.78rem", color: "var(--text-muted)" }}>
              command
            </summary>
            <pre style={{
              background: "var(--bg)", padding: 8, borderRadius: 4,
              maxHeight: 120, overflow: "auto", fontSize: "0.75rem",
            }}>{result.command}</pre>
          </details>
        </div>
      )}

      {/* Tool + options */}
      <div style={{ display: "flex", gap: 12, padding: "6px 0", flexWrap: "wrap", alignItems: "center" }}>
        <div className="cmp-toggle-group" role="tablist" aria-label="Post-processing tool">
          <button
            type="button"
            role="tab"
            aria-selected={tool === "compare_cases"}
            className={`cmp-toggle ${tool === "compare_cases" ? "is-active" : ""}`}
            onClick={() => setTool("compare_cases")}
            title="Run compare_cases.py to generate side-by-side comparison plots">
            <span className="cmp-toggle-icon">⚖️</span>
            <span className="cmp-toggle-label">compare_cases</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tool === "bokeh_report"}
            className={`cmp-toggle ${tool === "bokeh_report" ? "is-active" : ""}`}
            onClick={() => setTool("bokeh_report")}
            title="Run bokehpivot interface_report_model.py to generate an interactive HTML report">
            <span className="cmp-toggle-icon">📊</span>
            <span className="cmp-toggle-label">bokeh_report</span>
          </button>
        </div>
        {tool === "bokeh_report" && (
          <select value={report} onChange={(e) => setReport(e.target.value)}
            className="cmp-select"
            title="Select which bokehpivot report template to render">
            {BOKEH_REPORTS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        )}
      </div>

      {/* Base case + compare_cases options */}
      {selected.size >= 1 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "4px 0 8px", fontSize: "0.82rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-muted)" }}>
            Reference (base) case:
            <select value={basecase || Array.from(selected)[0] || ""}
              onChange={(e) => setBasecase(e.target.value)}
              style={{ padding: "2px 6px", fontSize: "0.78rem" }}>
              {Array.from(selected).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          {tool === "compare_cases" && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-muted)" }}>
              <input type="checkbox" checked={skipBokeh} onChange={() => setSkipBokeh((v) => !v)} />
              Skip bokehpivot report (faster, PPTX only)
            </label>
          )}
          {tool === "compare_cases" && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-muted)" }}>
              <input type="checkbox" checked={gdxDiff} onChange={() => setGdxDiff((v) => !v)} />
              GDX diff (compare inputs.gdx between cases, 2 cases only)
            </label>
          )}
          {tool === "bokeh_report" && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", color: "var(--text-muted)" }}>
              <input type="checkbox" checked={includeDiff} onChange={() => setIncludeDiff((v) => !v)} />
              Include diff (difference vs. base case)
            </label>
          )}
        </div>
      )}

      <details style={{ margin: "4px 0 8px" }}>
        <summary style={{ cursor: "pointer", fontSize: "0.82rem", color: "var(--text-muted)" }}>
          Advanced (shell prefix / extra CLI args)
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 4px" }}>
          <label style={{ fontSize: "0.78rem" }}>
            Bash prefix (env setup):
            <input type="text" value={bashPrefix}
              onChange={(e) => setBashPrefix(e.target.value)}
              placeholder="module load conda && conda activate reeds2"
              style={{ width: "100%", padding: "4px 6px" }} />
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              Activates the ReEDS conda env so pandas/numpy match. Without this, Kestrel’s system Python causes a binary mismatch error.
            </span>
          </label>
          <label style={{ fontSize: "0.78rem" }}>
            Extra CLI args:
            <input type="text" value={extraArgs}
              onChange={(e) => setExtraArgs(e.target.value)}
              placeholder="--startyear 2024"
              style={{ width: "100%", padding: "4px 6px" }} />
          </label>
        </div>
      </details>

      {/* Run picker */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 0" }}>
        <input type="text" value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${folders.length} runs…`}
          style={{ flex: 1, padding: "4px 8px" }} />
        <button onClick={selectAllVisible} className="cmp-btn" title="Select every visible run">Select all</button>
        <button onClick={clearAll} className="cmp-btn" title="Clear current selection">Clear</button>
        <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          {selected.size} selected
        </span>
      </div>

      {loading ? (
        <div className="loading">Loading runs from HPC…</div>
      ) : (
        <div style={{
          display: "flex", gap: 12, alignItems: "stretch",
          maxHeight: "calc(100vh - 380px)", minHeight: 200,
        }}>
          {/* Run picker (left) */}
          <div style={{
            flex: selected.size > 0 ? 1.4 : 1,
            minWidth: 0, overflow: "auto",
            border: "1px solid var(--border)", borderRadius: "var(--radius)",
          }}>
            {filtered.map((f) => {
              const checked = selected.has(f.name);
              const status = f.has_report ? "✅ Completed"
                : f.has_gamslog ? "🟡 In progress"
                  : f.has_meta ? "🔵 Setting up" : "⚠️ Failed";
              return (
                <label key={f.name} style={{
                  display: "flex", gap: 8, alignItems: "center",
                  padding: "5px 10px", borderBottom: "1px solid var(--border)",
                  cursor: "pointer", background: checked ? "rgba(96,165,250,0.10)" : undefined,
                }}>
                  <input type="checkbox" checked={checked} onChange={() => toggle(f.name)} />
                  <span style={{ flex: 1, fontFamily: "var(--font-mono)", fontSize: "0.82rem" }}>
                    {f.name}
                  </span>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{status}</span>
                </label>
              );
            })}
            {filtered.length === 0 && (
              <div className="loading" style={{ opacity: 0.6 }}>No runs match.</div>
            )}
          </div>

          {/* Scenarios editor (right, both tools for rename) */}
          {selected.size > 0 && (
            <div style={{
              flex: 1, minWidth: 320, display: "flex", flexDirection: "column",
              border: "1px solid var(--border)", borderRadius: "var(--radius)",
              overflow: "hidden",
            }}>
              <div style={{
                padding: "6px 10px", fontSize: "0.82rem", fontWeight: 600,
                background: "var(--bg-elev)", borderBottom: "1px solid var(--border)",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <span>Display Names ({selected.size})</span>
                <span style={{ fontSize: "0.7rem", fontWeight: 400, color: "var(--text-muted)" }}>
                  {tool === "bokeh_report" ? "shown in plots" : "used as --casenames"}
                </span>
              </div>
              <div style={{ overflow: "auto", flex: 1 }}>
                <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
                  <thead style={{ background: "var(--bg-elev)", position: "sticky", top: 0, zIndex: 1 }}>
                    <tr>
                      <th style={{ textAlign: "left", padding: "4px 8px" }}>Case</th>
                      <th style={{ textAlign: "left", padding: "4px 8px" }}>Label</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from(selected).map((c) => {
                      const s = scenarios[c] ?? { label: c, color: "#1f77b4" };
                      return (
                        <tr key={c} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ padding: "3px 8px", fontFamily: "var(--font-mono)" }}>{c}</td>
                          <td style={{ padding: "3px 8px" }}>
                            <input type="text" value={s.label}
                              onChange={(e) => setScenarios((prev) => ({
                                ...prev, [c]: { ...s, label: e.target.value },
                              }))}
                              style={{ width: "100%", padding: "2px 6px" }} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div style={{
                padding: "4px 10px", fontSize: "0.7rem", color: "var(--text-muted)",
                borderTop: "1px solid var(--border)", background: "var(--bg-elev)",
              }}>
                Defaults to case name. Commas replaced with spaces. Colors auto-assigned.
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, padding: "10px 0", alignItems: "center" }}>
        <button onClick={handleRun} disabled={!canRun}
          className={canRun ? "cmp-btn cmp-btn-primary" : "cmp-btn"}
          title={canRun ? "Run the selected post-processing tool on the HPC cluster" : "Select at least 2 runs to enable"}
          style={{ fontWeight: 600 }}>
          {running ? "⏳ Running on HPC…" : "▶ Run on HPC"}
        </button>
        {selected.size < 2 && (
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Select at least 2 runs.
          </span>
        )}
      </div>
    </div>
  );
}
