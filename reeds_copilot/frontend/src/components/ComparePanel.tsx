import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import hljs from "highlight.js";
import "highlight.js/styles/vs2015.css";
import { guessLang } from "../lib/highlight";
import {
  listRunFoldersAPI,
  compareBrowseAPI,
  compareCaseFilesAPI,
  compareDataAPI,
  rawFileURL,
  type RunFolder,
  type CompareDataResponse,
  type CompareEntry,
  type CompareBrowseResponse,
  type CaseFilesResponse,
} from "../lib/api";

interface Props {
  onClose: () => void;
  /** When provided, only run folders with these names appear in the picker. */
  filterRunNames?: string[];
  /** Optional banner text shown at the top (e.g. "HPC runs synced to local"). */
  banner?: string;
  /** Custom run-folder lister (e.g. HPC). Defaults to local listRunFoldersAPI. */
  listRunsFn?: () => Promise<RunFolder[]>;
  /** Custom common-files lister. Defaults to local compareBrowseAPI. */
  browseFn?: (cases: string[], subdir: string) => Promise<CompareBrowseResponse>;
  /** Custom per-case file lister. Defaults to local compareCaseFilesAPI. */
  caseFilesFn?: (caseName: string, subdir: string) => Promise<CaseFilesResponse>;
  /** Custom data fetcher. Defaults to local compareDataAPI. */
  dataFn?: (
    cases: string[],
    filename: string,
    subdir: string,
    maxRowsPerCase: number,
    filenames?: Record<string, string>,
  ) => Promise<CompareDataResponse>;
  /** Custom URL builder for image_diff mode. Defaults to local rawFileURL. */
  imageURLFn?: (path: string) => string;
}

type FileSortKey = "name" | "size";
type FileSortDir = "asc" | "desc";

const CASE_COLORS = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c", "#2dd4bf", "#e879f9"];

export default function ComparePanel({
  onClose, filterRunNames, banner,
  listRunsFn, browseFn, caseFilesFn, dataFn, imageURLFn,
}: Props) {
  const _listRuns = listRunsFn ?? listRunFoldersAPI;
  const _browse = browseFn ?? compareBrowseAPI;
  const _caseFiles = caseFilesFn ?? compareCaseFilesAPI;
  const _data = dataFn ?? compareDataAPI;
  const _imageURL = imageURLFn ?? rawFileURL;
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

  // Custom pick mode (per-case file selection)
  const [customPick, setCustomPick] = useState(false);
  const [customSubdir, setCustomSubdir] = useState("");
  const [customEntries, setCustomEntries] = useState<Record<string, CompareEntry[]>>({});
  const [customSelected, setCustomSelected] = useState<Record<string, string>>({});
  const [customFilter, setCustomFilter] = useState<Record<string, string>>({});
  const [customLoading, setCustomLoading] = useState(false);

  const step = data ? 3 : confirmed ? 2 : 1;

  useEffect(() => {
    _listRuns()
      .then((all) => {
        if (filterRunNames && filterRunNames.length > 0) {
          const allow = new Set(filterRunNames);
          setFolders(all.filter((f) => allow.has(f.name)));
        } else {
          setFolders(all);
        }
      })
      .catch(() => {});
  }, [filterRunNames, _listRuns]);

  // Browse common entries when subdir changes (standard mode)
  useEffect(() => {
    if (!confirmed || customPick) return;
    setBrowseLoading(true);
    setError(null);
    _browse(Array.from(selected), browseSubdir)
      .then((res) => setBrowseEntries(res.entries))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBrowseLoading(false));
  }, [confirmed, browseSubdir, selected, customPick, _browse]);

  // Browse per-case entries when in custom pick mode
  useEffect(() => {
    if (!confirmed || !customPick) return;
    setCustomLoading(true);
    setError(null);
    Promise.all(
      Array.from(selected).map((c) =>
        _caseFiles(c, customSubdir).then((res) => ({ case: c, entries: res.entries }))
      )
    )
      .then((results) => {
        const map: Record<string, CompareEntry[]> = {};
        for (const r of results) map[r.case] = r.entries;
        setCustomEntries(map);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCustomLoading(false));
  }, [confirmed, customPick, customSubdir, selected, _caseFiles]);

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
    setCustomPick(false);
    setCustomSubdir("");
    setCustomSelected({});
    setCustomFilter({});
    setCustomEntries({});
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
      _data(Array.from(selected), entry.name, browseSubdir, 5000)
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

  function customNavigateUp() {
    if (!customSubdir) return;
    const parts = customSubdir.split("/");
    parts.pop();
    setCustomSubdir(parts.join("/"));
    setCustomFilter({});
  }

  function handleCustomDirClick(dirName: string) {
    const newPath = customSubdir ? `${customSubdir}/${dirName}` : dirName;
    setCustomSubdir(newPath);
    setCustomSelected({});
    setCustomFilter({});
  }

  function handleCustomFileSelect(caseName: string, fileName: string) {
    setCustomSelected((prev) => ({ ...prev, [caseName]: fileName }));
  }

  function customCompare() {
    const cases = Array.from(selected);
    const allSelected = cases.every((c) => customSelected[c]);
    if (!allSelected) return;
    setLoading(true);
    setError(null);
    setDiffOnly(false);
    _data(cases, "", customSubdir, 5000, customSelected)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  const allCustomSelected = Array.from(selected).every((c) => customSelected[c]);

  function goBack() {
    if (data) {
      setData(null);
      setDiffOnly(false);
    } else if (confirmed) {
      setConfirmed(false);
      setBrowseEntries([]);
      setBrowseSubdir("");
      setFileFilter("");
      setCustomPick(false);
      setCustomSubdir("");
      setCustomSelected({});
      setCustomFilter({});
      setCustomEntries({});
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
            <button
              onClick={goBack}
              title="Go back to the previous step"
              className="cmp-btn cmp-btn-back">
              <span style={{ fontSize: "0.95rem", lineHeight: 1 }}>←</span> Back
            </button>
          )}
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Compare Cases</h3>
        </div>
        <button
          onClick={onClose}
          title="Close the Compare Cases panel and return to the file browser"
          className="cmp-btn cmp-btn-close">
          <span style={{ fontSize: "0.95rem", lineHeight: 1 }}>✕</span> Close Compare
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

      {banner && (
        <div style={{
          background: "var(--bg-elev)", border: "1px solid var(--border)",
          borderRadius: "var(--radius)", padding: "8px 12px", margin: "8px 0",
          fontSize: "0.82rem", lineHeight: 1.4,
        }}>{banner}</div>
      )}

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
          {/* Case badges */}
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
            {selectedArr.map((c, i) => (
              <span key={c} className="compare-case-badge" style={{
                background: CASE_COLORS[i % CASE_COLORS.length] + "20",
                color: CASE_COLORS[i % CASE_COLORS.length],
              }}>{c}</span>
            ))}
            <label style={{
              marginLeft: "auto", fontSize: "0.75rem", display: "flex", alignItems: "center", gap: 4,
              cursor: "pointer", color: "var(--text-muted)",
            }}>
              <input type="checkbox" checked={customPick} onChange={() => {
                setCustomPick((v) => !v);
                setCustomSubdir(browseSubdir);
                setCustomSelected({});
                setCustomFilter({});
              }} style={{ accentColor: "var(--accent)" }} />
              Custom Pick
            </label>
          </div>

          {/* ── Standard mode (common files) ── */}
          {!customPick && (
            <>
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
            </>
          )}

          {/* ── Custom pick mode (per-case file selection) ── */}
          {customPick && (
            <>
              <div className="compare-breadcrumb">
                <span onClick={() => { setCustomSubdir(""); setCustomSelected({}); setCustomFilter({}); }}>📁 root</span>
                {(customSubdir ? customSubdir.split("/") : []).map((part, i, arr) => {
                  const path = arr.slice(0, i + 1).join("/");
                  return (
                    <span key={path}>
                      {" / "}
                      <span onClick={() => { setCustomSubdir(path); setCustomSelected({}); setCustomFilter({}); }}>{part}</span>
                    </span>
                  );
                })}
                {customSubdir && (
                  <span onClick={customNavigateUp} style={{ marginLeft: 10, cursor: "pointer", opacity: 0.7 }}>⬆ up</span>
                )}
              </div>

              <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", margin: "4px 0 8px" }}>
                Pick one file from each case (names can differ). Navigate folders first.
              </p>

              {customLoading && <div className="loading">Loading…</div>}

              {/* Shared folder navigation — dirs common across all cases */}
              {!customLoading && (() => {
                const dirSets = selectedArr.map((c) =>
                  new Set((customEntries[c] ?? []).filter((e) => e.is_dir).map((e) => e.name))
                );
                const commonDirs = [...(dirSets[0] ?? [])].filter((d) => dirSets.every((s) => s.has(d))).sort();
                if (commonDirs.length === 0) return null;
                return (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: 2 }}>📁 Common folders:</div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {commonDirs.map((d) => (
                        <button key={d} className="btn btn-outline"
                          style={{ fontSize: "0.75rem", padding: "2px 8px" }}
                          onClick={() => handleCustomDirClick(d)}>
                          {d}/
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Per-case file lists */}
              {!customLoading && (
                <div style={{ display: "flex", gap: 8, overflow: "auto" }}>
                  {selectedArr.map((c, idx) => {
                    const entries = (customEntries[c] ?? []).filter((e) => !e.is_dir);
                    const filter = customFilter[c] ?? "";
                    const filtered = filter
                      ? entries.filter((e) => e.name.toLowerCase().includes(filter.toLowerCase()))
                      : entries;
                    const color = CASE_COLORS[idx % CASE_COLORS.length];
                    const sel = customSelected[c];
                    return (
                      <div key={c} style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ color, fontWeight: 600, fontSize: "0.8rem", marginBottom: 4, fontFamily: "var(--font-mono)" }}>
                          {c}
                          {sel && <span style={{ fontWeight: 400, opacity: 0.7 }}> → {sel}</span>}
                        </div>
                        <input type="text" placeholder="Filter…"
                          value={filter}
                          onChange={(e) => setCustomFilter((prev) => ({ ...prev, [c]: e.target.value }))}
                          className="compare-filter-input" style={{ marginBottom: 4 }}
                        />
                        <div className="compare-file-list" style={{ maxHeight: "40vh" }}>
                          {filtered.map((e) => (
                            <div key={e.name}
                              className="compare-file-item"
                              onClick={() => handleCustomFileSelect(c, e.name)}
                              style={{
                                background: sel === e.name ? `${color}20` : undefined,
                                borderLeft: sel === e.name ? `3px solid ${color}` : "3px solid transparent",
                              }}>
                              <span className="compare-file-icon">📄</span>
                              <span className="compare-file-name">{e.name}</span>
                              <span className="compare-file-size">{formatSize(e.size)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Compare button */}
              {allCustomSelected && (
                <button className="btn" style={{ marginTop: 10, width: "100%", padding: "8px", fontSize: "0.88rem" }}
                  onClick={customCompare} disabled={loading}>
                  {loading ? "Comparing…" : "Compare Selected Files →"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Step 3: View comparison */}
      {step === 3 && loading && (
        <div className="loading-block">
          <div className="spinner-lg" />
          <div>Comparing files across cases…</div>
          <div className="hint">This may take a moment for large files or HPC downloads.</div>
        </div>
      )}
      {step === 3 && data && data.mode === "text_diff" && <TextDiffView data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />}
      {step === 3 && data && data.mode === "image_diff" && <ImageDiffView data={data} caseColors={CASE_COLORS} imageURL={_imageURL} />}
      {step === 3 && data && data.mode === "gdx_diff" && <GdxDiffView data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />}
      {step === 3 && data && data.mode === "side_by_side" && (
        <CompareTable data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />
      )}
      {step === 3 && data && data.mode === "csv_table" && <CsvTableView data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />}
      {step === 3 && data && data.mode === "unsupported" && <TextDiffView data={data} caseColors={CASE_COLORS} diffOnly={diffOnly} onToggleDiffOnly={() => setDiffOnly((v) => !v)} />}
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

function TextDiffView({ data, caseColors, diffOnly, onToggleDiffOnly }: {
  data: CompareDataResponse; caseColors: string[];
  diffOnly?: boolean; onToggleDiffOnly?: () => void;
}) {
  const { cases, texts, filename, subdir } = data;
  const setRef = useSyncScroll(cases.length);
  // Pre-compute which line indices differ across cases (raw text comparison).
  const diffLineSet = useMemo(() => {
    if (!texts) return new Set<number>();
    const splits = cases.map((c) => (texts[c] ?? "").split("\n"));
    const maxLen = Math.max(0, ...splits.map((s) => s.length));
    const diffs = new Set<number>();
    for (let i = 0; i < maxLen; i++) {
      const first = splits[0]?.[i];
      for (let j = 1; j < splits.length; j++) {
        if (splits[j]?.[i] !== first) { diffs.add(i); break; }
      }
    }
    return diffs;
  }, [texts, cases]);
  const diffCount = diffLineSet.size;
  if (!texts) return null;
  const lang = guessLang(filename ?? "");
  return (
    <div className="compare-data">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
          {diffCount.toLocaleString()} differing line{diffCount === 1 ? "" : "s"}
        </span>
        {onToggleDiffOnly && (
          <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
            <input type="checkbox" checked={!!diffOnly} onChange={onToggleDiffOnly} style={{ accentColor: "var(--accent)" }} />
            Show diffs only
          </label>
        )}
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
                {lines.map((lineHtml, idx) => {
                  const isDiff = diffLineSet.has(idx);
                  if (diffOnly && !isDiff) return null;
                  return (
                    <div key={idx} style={{
                      display: "flex", minHeight: "1.5em",
                      background: isDiff ? "rgba(251, 191, 36, 0.10)" : undefined,
                    }}>
                      <span style={{
                        display: "inline-block", width: 40, minWidth: 40, textAlign: "right",
                        paddingRight: 8, color: "var(--text-muted)", opacity: 0.5,
                        userSelect: "none", borderRight: "1px solid var(--border)",
                        marginRight: 8, flexShrink: 0,
                      }}>{idx + 1}</span>
                      <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                        dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
                    </div>
                  );
                })}
                {diffOnly && diffCount === 0 && (
                  <div style={{ padding: 12, color: "var(--text-muted)", fontSize: "0.8rem" }}>
                    No differing lines — files are identical.
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CsvTableView({ data, caseColors, diffOnly, onToggleDiffOnly }: {
  data: CompareDataResponse; caseColors: string[];
  diffOnly?: boolean; onToggleDiffOnly?: () => void;
}) {
  const { columns, cases, filename, subdir, case_tables, total_rows } = data;
  const setRef = useSyncScroll(cases.length);
  // Determine which row indices differ across cases. A row index is "diff" if
  // the row is missing in any case OR any column value disagrees across cases.
  const diffRowSet = useMemo(() => {
    const diffs = new Set<number>();
    if (!case_tables) return diffs;
    const lengths = cases.map((c) => (case_tables[c] ?? []).length);
    const maxLen = Math.max(0, ...lengths);
    for (let i = 0; i < maxLen; i++) {
      let isDiff = false;
      const baseRow = case_tables[cases[0]]?.[i];
      for (let j = 0; j < cases.length; j++) {
        const row = case_tables[cases[j]]?.[i];
        if (!row || !baseRow) { isDiff = true; break; }
        for (const col of columns) {
          const a = row[col]; const b = baseRow[col];
          if ((a == null ? "" : String(a)) !== (b == null ? "" : String(b))) { isDiff = true; break; }
        }
        if (isDiff) break;
      }
      if (isDiff) diffs.add(i);
    }
    return diffs;
  }, [case_tables, cases, columns]);
  const diffCount = diffRowSet.size;
  if (!case_tables) return null;
  return (
    <div className="compare-data">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
          {total_rows} rows · {diffCount.toLocaleString()} differing
        </span>
        {onToggleDiffOnly && (
          <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
            <input type="checkbox" checked={!!diffOnly} onChange={onToggleDiffOnly} style={{ accentColor: "var(--accent)" }} />
            Show diffs only
          </label>
        )}
      </div>
      <div style={{ display: "flex", gap: 10, overflow: "auto" }}>
        {cases.map((c, i) => {
          const rows = case_tables[c] ?? [];
          const color = caseColors[i % caseColors.length];
          const visibleRows = diffOnly
            ? rows.map((row, ri) => ({ row, ri })).filter((x) => diffRowSet.has(x.ri))
            : rows.map((row, ri) => ({ row, ri }));
          return (
            <div key={c} style={{ flex: 1, minWidth: 300 }}>
              <div style={{
                color, fontWeight: 600,
                fontSize: "0.82rem", marginBottom: 4, fontFamily: "var(--font-mono)",
              }}>{c} ({visibleRows.length} {diffOnly ? "differing" : "rows"})</div>
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
                    {visibleRows.map(({ row, ri }) => (
                      <tr key={ri} style={diffRowSet.has(ri) ? { background: "rgba(251, 191, 36, 0.10)" } : undefined}>
                        {columns.map((col) => (
                          <td key={col}>{row[col] != null ? String(row[col]) : ""}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {diffOnly && diffCount === 0 && (
                  <div style={{ padding: 12, color: "var(--text-muted)", fontSize: "0.8rem" }}>
                    No differing rows.
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ImageDiffView({ data, caseColors, imageURL }: { data: CompareDataResponse; caseColors: string[]; imageURL: (p: string) => string }) {
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
                src={imageURL(image_paths[c])}
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

function GdxDiffView({ data, caseColors, diffOnly, onToggleDiffOnly }: {
  data: CompareDataResponse; caseColors: string[];
  diffOnly?: boolean; onToggleDiffOnly?: () => void;
}) {
  const { columns, rows, cases, filename, subdir, gdx_total_symbols, gdx_common_count } = data;
  const [filter, setFilter] = useState("");

  const rowHasDiff = useCallback((row: Record<string, unknown>): boolean => {
    const vals = cases.map((c) => row[c]);
    return new Set(vals.map(String)).size > 1;
  }, [cases]);

  const filtered = useMemo(() => {
    let out = rows;
    if (filter) {
      const lower = filter.toLowerCase();
      out = out.filter((r) => String(r.name ?? "").toLowerCase().includes(lower));
    }
    if (diffOnly) out = out.filter(rowHasDiff);
    return out;
  }, [rows, filter, diffOnly, rowHasDiff]);

  const diffCount = useMemo(() => rows.filter(rowHasDiff).length, [rows, rowHasDiff]);

  return (
    <div className="compare-data">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <strong style={{ color: "var(--accent)" }}>{subdir ? `${subdir}/` : ""}{filename}</strong>
        <span style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>
          {gdx_common_count} common symbols · {diffCount} differing
          {gdx_total_symbols && ` (total: ${cases.map((c) => `${c}=${gdx_total_symbols[c]}`).join(", ")})`}
        </span>
        {onToggleDiffOnly && (
          <label style={{ fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
            <input type="checkbox" checked={!!diffOnly} onChange={onToggleDiffOnly} style={{ accentColor: "var(--accent)" }} />
            Show diffs only
          </label>
        )}
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
                <tr key={i} style={hasDiff ? { background: "rgba(251, 191, 36, 0.10)" } : undefined}>
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
      {diffOnly && filtered.length === 0 && (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: 10 }}>
          No differing symbols.
        </p>
      )}
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
