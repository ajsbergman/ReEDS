import { useEffect, useState, useMemo } from "react";
import {
  listRunFoldersAPI,
  compareCommonFilesAPI,
  compareDataAPI,
  type RunFolder,
  type CompareDataResponse,
} from "../lib/api";

interface Props {
  onClose: () => void;
}

export default function ComparePanel({ onClose }: Props) {
  const [folders, setFolders] = useState<RunFolder[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [commonFiles, setCommonFiles] = useState<string[] | null>(null);
  const [chosenFile, setChosenFile] = useState<string | null>(null);
  const [data, setData] = useState<CompareDataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fileFilter, setFileFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Step tracking
  const step = data ? 3 : commonFiles ? 2 : 1;

  useEffect(() => {
    listRunFoldersAPI().then(setFolders).catch(() => {});
  }, []);

  // Fetch common files when selection changes (>= 2 cases)
  useEffect(() => {
    setCommonFiles(null);
    setChosenFile(null);
    setData(null);
    setError(null);
    if (selected.size < 2) return;
    const cases = Array.from(selected);
    compareCommonFilesAPI(cases)
      .then((res) => setCommonFiles(res.files))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [selected]);

  function toggleCase(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function loadComparison(filename: string) {
    setChosenFile(filename);
    setLoading(true);
    setError(null);
    compareDataAPI(Array.from(selected), filename)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  function goBack() {
    if (data) {
      setData(null);
      setChosenFile(null);
    } else if (commonFiles) {
      setCommonFiles(null);
      setSelected(new Set());
    }
  }

  const filteredFiles = useMemo(() => {
    if (!commonFiles) return [];
    if (!fileFilter) return commonFiles;
    const lower = fileFilter.toLowerCase();
    return commonFiles.filter((f) => f.toLowerCase().includes(lower));
  }, [commonFiles, fileFilter]);

  // Case colors for visual differentiation
  const caseColors = ["#60a5fa", "#4ade80", "#fbbf24", "#f87171", "#c084fc", "#fb923c", "#2dd4bf", "#e879f9"];

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
        <span className={step >= 3 ? "step-active" : ""}>③ View Data</span>
      </div>

      {error && <div className="error-banner" style={{ margin: "8px 0" }}>{error}</div>}

      {/* Step 1: Select cases */}
      {step === 1 && (
        <div className="compare-case-select">
          <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", margin: "0 0 10px" }}>
            Select 2 or more cases to compare (currently: {selected.size} selected)
          </p>
          <div className="compare-case-list">
            {folders.map((f) => (
              <label key={f.name} className="compare-case-item">
                <input
                  type="checkbox"
                  checked={selected.has(f.name)}
                  onChange={() => toggleCase(f.name)}
                />
                <span className="compare-case-name">{f.name}</span>
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                  {new Date(f.modified_at * 1000).toLocaleDateString()}
                </span>
              </label>
            ))}
          </div>
          {folders.length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>No run cases found.</p>
          )}
        </div>
      )}

      {/* Step 2: Pick a common CSV */}
      {step === 2 && commonFiles && (
        <div className="compare-file-select">
          <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", margin: "0 0 8px" }}>
            {commonFiles.length} common CSV files across {selected.size} cases
          </p>
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            {Array.from(selected).map((c, i) => (
              <span
                key={c}
                style={{
                  fontSize: "0.72rem", padding: "2px 8px", borderRadius: 4,
                  background: caseColors[i % caseColors.length] + "25",
                  color: caseColors[i % caseColors.length],
                  fontFamily: "var(--font-mono)",
                }}
              >
                {c}
              </span>
            ))}
          </div>
          <input
            type="text"
            placeholder="Filter files…"
            value={fileFilter}
            onChange={(e) => setFileFilter(e.target.value)}
            style={{
              width: "100%", padding: "5px 8px", marginBottom: 8,
              background: "var(--bg-input, #23272e)", color: "var(--text-primary, #e0e0e0)",
              border: "1px solid var(--border, #333)", borderRadius: 4, fontSize: "0.82rem",
              boxSizing: "border-box",
            }}
          />
          <div className="compare-file-list">
            {filteredFiles.map((f) => (
              <div
                key={f}
                className="compare-file-item"
                onClick={() => loadComparison(f)}
              >
                📄 {f}
              </div>
            ))}
            {filteredFiles.length === 0 && (
              <p style={{ color: "var(--text-muted)", fontSize: "0.82rem" }}>No files match.</p>
            )}
          </div>
        </div>
      )}

      {/* Step 3: Data table */}
      {step === 3 && loading && <div className="loading">Loading comparison…</div>}
      {step === 3 && data && (
        <div className="compare-data">
          <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginBottom: 8 }}>
            <strong style={{ color: "var(--accent)" }}>{data.filename}</strong>
            {" · "}{data.total_rows.toLocaleString()} rows across {data.cases.length} cases
          </div>
          <div className="csv-table-wrap" style={{ maxHeight: "calc(100vh - 280px)" }}>
            <table>
              <thead>
                <tr>
                  {data.columns.map((c) => (
                    <th key={c} style={c === "case" ? { position: "sticky", left: 0, background: "var(--bg-elevated)", zIndex: 1 } : undefined}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => {
                  const caseIdx = data.cases.indexOf(String(row.case));
                  const caseColor = caseColors[caseIdx % caseColors.length];
                  return (
                    <tr key={i}>
                      {data.columns.map((c) => (
                        <td
                          key={c}
                          style={
                            c === "case"
                              ? { position: "sticky", left: 0, background: "var(--bg-elevated)", color: caseColor, fontWeight: 600, zIndex: 1 }
                              : undefined
                          }
                        >
                          {String(row[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
