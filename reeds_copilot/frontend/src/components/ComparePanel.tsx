import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import hljs from "highlight.js";
import "highlight.js/styles/vs2015.css";
import {
  listRunFoldersAPI,
  compareBrowseAPI,
  compareDataAPI,
  rawFileURL,
  type RunFolder,
  type CompareDataResponse,
  type CompareEntry,
} from "../lib/api";

interface Props {
  onClose: () => void;
}

type FileSortKey = "name" | "size";
type FileSortDir = "asc" | "desc";

const CASE_COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c", "#2dd4bf", "#e879f9"];

export default function ComparePanel({ onClose }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);

  // Browsing state
  const [browseSubdir, setBrowseSubdir] = useState("");
  const [browseEntries, setBrowseEntries] = useState<CompareEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  // Data view state
  const [data, setData] = useState<CompareDataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diffOnly, setDiffOnly] = useState(false);

  // File sorting
  const [fileSortKey, setFileSortKey] = useState<FileSortKey>("name");
  const [fileSortDir, setFileSortDir] = useState<FileSortDir>("asc");
  const [fileFilter, setFileFilter] = useState("");

  const step = data ? 3 : confirmed ? 2 : 1;

  useEffect(() => {
    listRunFoldersAPI().then(setFolders).catch(() => {});
  }, []);

  // Browse common entries when subdir changes
  useEffect(() => {
    if (!confirmed) return;
    setBrowseLoading(true);
    setError(null);
    compareBrowseAPI(Array.from(selected), browseSubdir)
      .then((res) => setBrowseEntries(res.entries))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBrowseLoading(false));
  }, [confirmed, browseSubdir, selected]);

  function toggleCase(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function confirmCases() {
    if (selected.size < 2) return;
    setConfirmed(true);
    setBrowseSubdir("");
  }

  function handleBrowseClick(entry: CompareEntry) {
    if (entry.is_dir) {
      const newPath = browseSubdir ? `${browseSubdir}/${entry.name}` : entry.name;
      setBrowseSubdir(newPath);
      setFileFilter("");
    } else {
      setLoading(true);
      setError(null);
      setDiffOnly(false);
      compareDataAPI(Array.from(selected), entry.name, browseSubdir)
        .then(setData)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false));
    }
  }

  function navigateUp() {
    if (!browseSubdir) return;
    const parts = browseSubdir.split("/");
    parts.pop();
    setBrowseSubdir(parts.join("/"));
    setFileFilter("");
  }

  function goBack() {
    if (data) {
      setData(null);
      setDiffOnly(false);
    } else if (confirmed) {
      setConfirmed(false);
      setBrowseEntries([]);
      setBrowseSubdir("");
      setFileFilter("");
    }
  }

  function toggleFileSort(key: FileSortKey) {
    if (fileSortKey === key) setFileSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setFileSortKey(key); setFileSortDir("asc"); }
  }

  function sortIndicator(key: FileSortKey): string {
    return fileSortKey !== key ? "" : fileSortDir === "asc" ? " ▲" : " ▼";
  }

  const sortedEntries = useMemo(() => {
    let items = browseEntries;
    if (fileFilter) {
      const lower = fileFilter.toLowerCase();
      items = items.filter((e) => e.name.toLowerCase().includes(lower));
    }
    const dirs = items.filter((e) => e.is_dir);
    const files = items.filter((e) => !e.is_dir);
    const cmp = (a: CompareEntry, b: CompareEntry) => {
      let r = 0;
      if (fileSortKey === "name") r = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
      else r = (a.size ?? 0) - (b.size ?? 0);
      return fileSortDir === "asc" ? r : -r;
    };
    return [...dirs.sort(cmp), ...files.sort(cmp)];
  }, [browseEntries, fileFilter, fileSortKey, fileSortDir]);

  function formatSize(size: number | null): string {
    if (size === null) return "";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  const selectedArr = Array.from(selected);
  const breadcrumbParts = browseSubdir ? browseSubdir.split("/") : [];

  return (
    <div className="compare-panel">
      {/* Header */}
      <div className="compare-header">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {step > 1 && (
            <button className="btn btn-outline" onClick={goBack} style={{ fontSize: "0.78rem", padding: "3px 8px" }}>
              ← Back
            </button>
          )}
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Compare Cases</h3>
        </div>
        <button className="btn btn-outline" onClick={onClose} style={{ fontSize: "0.78rem", padding: "3px 8px" }}>
          ✕ Close
        </button>
      </div>

      {/* Step indicator */}
      <div className="compare-steps">
        <span className={step >= 1 ? "step-active" : ""}>① Select Cases</span>
        <span className="step-arrow">→</span>
        <span className={step >= 2 ? "step-active" : ""}>② Pick File</span>
        <span className="step-arrow">→</span>
        <span className={step >= 3 ? "step-active" : ""}>③ Compare</span>
      </div>

      {error && <div className="error-banner" style={{ margin: "8px 0" }}>{error}</div>}

      {/* Step 1: Select cases */}
      {step === 1 && (
        <div className="compare-case-select">
          <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", margin: "0 0 10px" }}>
            Select 2 or more cases to compare ({selected.size} selected)
          </p>
          <div className="compare-case-list">
            {folders.map((f) => (
              <label key={f.name} className="compare-case-item">
                <input type="checkbox" checked={selected.has(f.name)} onChange={() => toggleCase(f.name)} />
                <span className="compare-case-name">{f.name}</span>
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                  {new Date(f.modified_at * 1000).toLocaleDateString()}
                </span>
              </label>
            ))}
          </div>
          {folders.length === 0 && <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>No run cases found.</p>}
          {selected.size >= 2 && (
            <button className="btn" style={{ marginTop: 12, width: "100%", padding: "8px", fontSize: "0.88rem" }} onClick={confirmCases}>
              Compare {selected.size} Cases →
            </button>
          )}
        </div>
      )}

      {/* Step 2: Browse & pick file */}
      {step === 2 && (
        <div className="compare-file-select">
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            {selectedArr.map((c, i) => (
              <span key={c} className="compare-case-badge" style={{
                background: CASE_COLORS[i % CASE_COLORS.length] + "20",
                color: CASE_COLORS[i % CASE_COLORS.length],
              }}>{c}</span>
            ))}
          </div>

          <div className="compare-breadcrumb">
            <span onClick={() => setBrowseSubdir("")}>📁 root</span>
            {breadcrumbParts.map((part, i) => {
              const path = breadcrumbParts.slice(0, i + 1).join("/");
              return (
                <span key={path}>
                  {" / "}
                  <span onClick={() => setBrowseSubdir(path)}>{part}</span>
                </span>
              );
            })}
            {browseSubdir && (
              <span onClick={navigateUp} style={{ marginLeft: 10, cursor: "pointer", opacity: 0.7 }}>⬆ up</span>
            )}
          </div>

          {browseLoading && <div className="loading">Loading…</div>}

          {!browseLoading && sortedEntries.length > 0 && (
            <>
              <input
                type="text" placeholder="Filter…" value={fileFilter}
                onChange={(e) => setFileFilter(e.target.value)}
                className="compare-filter-input"
              />
              <div className="compare-file-sort-bar">
                <span className="compare-sort-col compare-sort-col--name" onClick={() => toggleFileSort("name")}>
                  Name{sortIndicator("name")}
                </span>
                <span className="compare-sort-col compare-sort-col--size" onClick={() => toggleFileSort("size")}>
                  Size{sortIndicator("size")}
                </span>
              </div>
            </>
          )}

          <div className="compare-file-list">
            {sortedEntries.map((e) => (
              <div key={e.name} className="compare-file-item" onClick={() => handleBrowseClick(e)}>
                <span className="compare-file-icon">{e.is_dir ? "📁" : "📄"}</span>
                <span className="compare-file-name">{e.name}</span>
                <span className="compare-file-size">{formatSize(e.size)}</span>
              </div>
            ))}
            {!browseLoading && sortedEntries.length === 0 && (
              <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", padding: "8px 0" }}>
                {fileFilter ? "No matches." : "No common entries at this level."}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Step 3: View comparison */}
      {step === 3 && loading && <div className="loading">Loading comparison…</div>}
      {step === 3 && data && data.mode === "text_diff" && <TextDiffView data={data} caseColors={CASE_COLORS} />}
      {step === 3 && data && data.mode === "image_diff" && <ImageDiffView data={data} caseColors={CASE_COLORS} />}
      {step === 3 && data && data.mode === "gdx_diff" && <GdxDiffView data={data} caseColors={CASE_COLORS} />}
      {step === 3 && data && data.mode === "side_by_side" && (
        <CompareTable data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />
      )}
      {step === 3 && data && data.mode === "csv_table" && <CsvTableView data={data} caseColors={CASE_COLORS} />}
      {step === 3 && data && data.mode === "unsupported" && <TextDiffView data={data} caseColors={CASE_COLORS} />}
    </div>
  );
}

function useSyncScroll(count: number) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const isSyncing = useRef(false);
  const setRef = useCallback((idx: number) => (el: HTMLDivElement | null) => {
    refs.current[idx] = el;
  }, []);
  useEffect(() => {
    const els = refs.current.filter(Boolean) as HTMLDivElement[];
    const handler = (source: HTMLDivElement) => () => {
      if (isSyncing.current) return;
      isSyncing.current = true;
      for (const el of els) {
        if (el !== source) {
          el.scrollTop = source.scrollTop;
          el.scrollLeft = source.scrollLeft;
        }
      }
      isSyncing.current = false;
    };
    const handlers = els.map((el) => { const h = handler(el); el.addEventListener("scroll", h); return { el, h }; });
    return () => { handlers.forEach(({ el, h }) => el.removeEventListener("scroll", h)); };
  }, [count]);
  return setRef;
}

function guessLang(filename: string): string | undefined {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python", gms: "gams", jl: "julia", r: "r", sh: "bash", bat: "dos",
    json: "json", yaml: "yaml", yml: "yaml", toml: "ini", cfg: "ini", ini: "ini",
    csv: "csv", tsv: "csv", md: "markdown", html: "xml", xml: "xml",
    sql: "sql", js: "javascript", ts: "typescript", opt: "ini",
    txt: "plaintext", log: "plaintext", lst: "plaintext",
  };
  return map[ext];
}

function TextDiffView({ data, caseColors }: { data: CompareDataResponse; caseColors: string[] }) {
  const { cases, texts, filename, subdir } = data;
  const setRef = useSyncScroll(cases.length);
  if (!texts) return null;
  const lang = guessLang(filename ?? "");
  return (
    <div className="compare-data">
      <div style={{ marginBottom: 8 }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
      </div>
      <div style={{ display: "flex", gap: 8, overflow: "auto" }}>
        {cases.map((c, i) => {
          const raw = texts[c] ?? "(empty)";
          let highlighted: string;
          try {
            highlighted = lang && lang !== "csv" && lang !== "plaintext"
              ? hljs.highlight(raw, { language: lang }).value
              : hljs.highlightAuto(raw).value;
          } catch { highlighted = raw.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
          const lines = highlighted.split("\n");
          return (
            <div key={c} style={{ flex: 1, minWidth: 300 }}>
              <div style={{
                color: caseColors[i % caseColors.length], fontWeight: 600,
                fontSize: "0.82rem", marginBottom: 4, fontFamily: "var(--font-mono)",
              }}>{c}</div>
              <div ref={setRef(i)} className="hljs" style={{
                background: "var(--bg)", borderRadius: 4,
                fontSize: "0.75rem", maxHeight: "calc(100vh - 320px)", overflow: "auto",
                border: `1px solid ${caseColors[i % caseColors.length]}30`,
                fontFamily: "var(--font-mono)", lineHeight: 1.5,
              }}>
                {lines.map((lineHtml, idx) => (
                  <div key={idx} style={{ display: "flex", minHeight: "1.5em" }}>
                    <span style={{
                      display: "inline-block", width: 40, minWidth: 40, textAlign: "right",
                      paddingRight: 8, color: "var(--text-muted)", opacity: 0.5,
                      userSelect: "none", borderRight: "1px solid var(--border)",
                      marginRight: 8, flexShrink: 0,
                    }}>{idx + 1}</span>
                    <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                      dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CsvTableView({ data, caseColors }: { data: CompareDataResponse; caseColors: string[] }) {
  const { columns, cases, filename, subdir, case_tables, total_rows } = data;
  const setRef = useSyncScroll(cases.length);
  if (!case_tables) return null;
  return (
    <div className="compare-data">
      <div style={{ marginBottom: 8 }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginLeft: 8 }}>
          {total_rows} rows
        </span>
      </div>
      <div style={{ display: "flex", gap: 10, overflow: "auto" }}>
        {cases.map((c, i) => {
          const rows = case_tables[c] ?? [];
          const color = caseColors[i % caseColors.length];
          return (
            <div key={c} style={{ flex: 1, minWidth: 300 }}>
              <div style={{
                color, fontWeight: 600,
                fontSize: "0.82rem", marginBottom: 4, fontFamily: "var(--font-mono)",
              }}>{c} ({rows.length} rows)</div>
              <div ref={setRef(i)} className="csv-table-wrap" style={{
                maxHeight: "calc(100vh - 320px)",
                border: `1px solid ${color}30`, borderRadius: 4,
              }}>
                <table>
                  <thead>
                    <tr>
                      {columns.map((col) => <th key={col}>{col}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, ri) => (
                      <tr key={ri}>
                        {columns.map((col) => (
                          <td key={col}>{row[col] != null ? String(row[col]) : ""}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ImageDiffView({ data, caseColors }: { data: CompareDataResponse; caseColors: string[] }) {
  const { cases, image_paths, filename, subdir } = data;
  if (!image_paths) return null;
  return (
    <div className="compare-data">
      <div style={{ marginBottom: 8 }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
      </div>
      <div style={{ display: "flex", gap: 10, overflow: "auto", flexWrap: "wrap" }}>
        {cases.map((c, i) => (
          <div key={c} style={{ flex: 1, minWidth: 250 }}>
            <div style={{
              color: caseColors[i % caseColors.length], fontWeight: 600,
              fontSize: "0.82rem", marginBottom: 4, fontFamily: "var(--font-mono)",
            }}>{c}</div>
            <div style={{
              background: "#fff", borderRadius: 4, padding: 4,
              border: `1px solid ${caseColors[i % caseColors.length]}30`,
              textAlign: "center",
            }}>
              <img
                src={rawFileURL(image_paths[c])}
                alt={`${c} / ${filename}`}
                style={{ maxWidth: "100%", maxHeight: "60vh" }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GdxDiffView({ data, caseColors }: { data: CompareDataResponse; caseColors: string[] }) {
  const { columns, rows, cases, filename, subdir, gdx_total_symbols, gdx_common_count } = data;
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    if (!filter) return rows;
    const lower = filter.toLowerCase();
    return rows.filter((r) => String(r.name ?? "").toLowerCase().includes(lower));
  }, [rows, filter]);

  const rowHasDiff = useCallback((row: Record<string, unknown>): boolean => {
    const vals = cases.map((c) => row[c]);
    return new Set(vals.map(String)).size > 1;
  }, [cases]);

  return (
    <div className="compare-data">
      <div style={{ marginBottom: 8 }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginLeft: 8 }}>
          {gdx_common_count} common symbols
          {gdx_total_symbols && ` (total: ${cases.map((c) => `${c}=${gdx_total_symbols[c]}`).join(", ")})`}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
        {cases.map((c, i) => (
          <span key={c} className="compare-case-badge" style={{
            background: caseColors[i % caseColors.length] + "20",
            color: caseColors[i % caseColors.length],
          }}>{c}</span>
        ))}
      </div>
      <input type="text" placeholder="Filter symbols…" value={filter}
        onChange={(e) => setFilter(e.target.value)} className="compare-filter-input" />
      <div className="csv-table-wrap" style={{ maxHeight: "calc(100vh - 340px)" }}>
        <table>
          <thead>
            <tr>
              {columns.map((c) => {
                const caseIdx = cases.indexOf(c);
                return (
                  <th key={c} style={caseIdx >= 0 ? { color: caseColors[caseIdx % caseColors.length] } : undefined}>
                    {caseIdx >= 0 ? "records" : c}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row, i) => {
              const hasDiff = rowHasDiff(row);
              return (
                <tr key={i} style={hasDiff ? { background: "rgba(251, 191, 36, 0.06)" } : undefined}>
                  {columns.map((c) => {
                    const caseIdx = cases.indexOf(c);
                    return (
                      <td key={c} style={caseIdx >= 0 ? { color: caseColors[caseIdx % caseColors.length] } : undefined}>
                        {String(row[c] ?? "")}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompareTable({
  data,
  caseColors,
  diffOnly,
  onToggleDiffOnly,
}: {
  data: CompareDataResponse;
  caseColors: string[];
  diffOnly: boolean;
  onToggleDiffOnly: () => void;
}) {
  const { columns, rows, cases, index_cols, filename, subdir, total_rows } = data;
  const diffCol = columns.includes("diff") ? "diff" : null;

  const displayRows = useMemo(() => {
    if (!diffOnly || !diffCol) return rows;
    return rows.filter((r) => {
      const d = r[diffCol];
      return d !== null && d !== undefined && d !== 0;
    });
  }, [rows, diffOnly, diffCol]);

  const diffCount = useMemo(() => {
    if (!diffCol) return 0;
    return rows.filter((r) => r[diffCol] !== null && r[diffCol] !== undefined && r[diffCol] !== 0).length;
  }, [rows, diffCol]);

  const formatVal = useCallback((v: unknown): string => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") {
      if (Number.isNaN(v)) return "—";
      if (Math.abs(v) >= 1e6 || (Math.abs(v) < 0.01 && v !== 0)) return v.toExponential(3);
      return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
    }
    return String(v);
  }, []);

  const diffCellStyle = useCallback((val: unknown): React.CSSProperties => {
    if (val === null || val === undefined || val === 0) return {};
    const n = Number(val);
    if (Number.isNaN(n)) return {};
    return n > 0 ? { color: "#4ade80", fontWeight: 600 } : { color: "#f87171", fontWeight: 600 };
  }, []);

  const colHeaderStyle = useCallback((col: string): React.CSSProperties => {
    const caseIdx = cases.indexOf(col);
    if (caseIdx >= 0) return { color: caseColors[caseIdx % caseColors.length], fontWeight: 700 };
    if (col === "diff" || col === "pct_diff") return { color: "#fbbf24" };
    if (index_cols.includes(col)) return { background: "var(--bg-elevated)" };
    return {};
  }, [cases, caseColors, index_cols]);

  const rowHasDiff = useCallback((row: Record<string, unknown>): boolean => {
    if (!diffCol) return false;
    const d = row[diffCol];
    return d !== null && d !== undefined && d !== 0;
  }, [diffCol]);

  return (
    <div className="compare-data">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
          {displayRows.length.toLocaleString()}{diffOnly ? ` / ${total_rows.toLocaleString()}` : ""} rows
          {` · ${diffCount.toLocaleString()} differences`}
        </span>
        {diffCol && (
          <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
            <input type="checkbox" checked={diffOnly} onChange={onToggleDiffOnly} style={{ accentColor: "var(--accent)" }} />
            Show diffs only
          </label>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        {cases.map((c, i) => (
          <span key={c} className="compare-case-badge" style={{
            background: caseColors[i % caseColors.length] + "20",
            color: caseColors[i % caseColors.length],
          }}>{c}</span>
        ))}
      </div>
      <div className="csv-table-wrap" style={{ maxHeight: "calc(100vh - 300px)" }}>
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} style={{
                  ...colHeaderStyle(c),
                  ...(index_cols.includes(c) ? { position: "sticky", left: 0, zIndex: 1 } : {}),
                }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, i) => {
              const hasDiff = rowHasDiff(row);
              return (
                <tr key={i} style={hasDiff ? { background: "rgba(251, 191, 36, 0.06)" } : undefined}>
                  {columns.map((c) => {
                    const val = row[c];
                    const isIndex = index_cols.includes(c);
                    const isDiff = c === "diff" || c === "pct_diff";
                    const caseIdx = cases.indexOf(c);

                    let style: React.CSSProperties = {};
                    if (isIndex) style = { position: "sticky", left: 0, background: "var(--bg-elevated)", zIndex: 1 };
                    else if (isDiff) style = diffCellStyle(val);
                    else if (caseIdx >= 0) style = { color: caseColors[caseIdx % caseColors.length] };

                    return (
                      <td key={c} style={style}>
                        {isDiff && c === "pct_diff" ? (val != null ? `${formatVal(val)}%` : "—") : formatVal(val)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {displayRows.length === 0 && (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: 10 }}>
          {diffOnly ? "No differences found — identical across cases." : "No data."}
        </p>
      )}
    </div>
  );
}
