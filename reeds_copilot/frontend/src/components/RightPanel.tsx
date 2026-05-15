import { useEffect, useState, useMemo } from "react";
import hljs from "highlight.js";
import "highlight.js/styles/vs2015.css";
import { guessLang } from "../lib/highlight";
import { previewFileAPI, downloadFileURL, rawFileURL, type FilePreviewResponse, type GdxSymbolInfo, type H5DatasetInfo } from "../lib/api";
import type { SourceSnippet } from "../lib/api";

interface Props {
  selectedFile: string | null;
  selectedLine?: number | null;
  sources: SourceSnippet[];
  onSelectFile: (path: string, line?: number) => void;
  width?: number;
}

export default function RightPanel({ selectedFile, selectedLine, sources, onSelectFile, width }: Props) {
  const [preview, setPreview] = useState<FilePreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fullMode, setFullMode] = useState(false);
  const [gdxSymbol, setGdxSymbol] = useState<string | null>(null);
  const [h5Dataset, setH5Dataset] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedFile) {
      setPreview(null);
      setLoadError(null);
      setFullMode(false);
      setGdxSymbol(null);
      setH5Dataset(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    previewFileAPI(selectedFile, fullMode, gdxSymbol, h5Dataset)
      .then((res) => { if (!cancelled) { setPreview(res); setLoadError(null); } })
      .catch((err) => {
        if (cancelled) return;
        setPreview(null);
        const msg = (err && (err.message || String(err))) || "Unknown error";
        setLoadError(msg);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedFile, fullMode, gdxSymbol, h5Dataset]);

  // If the caller asked for a specific line, force full-file mode so it can be located
  useEffect(() => {
    if (selectedLine && selectedLine > 0) setFullMode(true);
  }, [selectedFile, selectedLine]);

  // Reset full mode and gdx/h5 selection when switching files
  useEffect(() => {
    if (!selectedLine) setFullMode(false);
    setGdxSymbol(null);
    setH5Dataset(null);
  }, [selectedFile]);

  return (
    <div className="right-panel" style={width ? { width, minWidth: width } : undefined}>
      {/* Sources section */}
      {sources.length > 0 && (
        <>
          <h3>Sources</h3>
          {sources.map((s, i) => (
            <div key={i} className="source-item" onClick={() => onSelectFile(s.file_path, s.line)}>
              <div className="path">{s.file_path}{s.line ? `:${s.line}` : ""}</div>
              {s.snippet && s.snippet !== "(filename match)" && (
                <div className="snippet">{s.snippet}</div>
              )}
            </div>
          ))}
        </>
      )}

      {/* File preview */}
      {selectedFile && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: sources.length > 0 ? 18 : 0 }}>
            <h3 style={{ margin: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              Preview: {selectedFile}
            </h3>
            <a
              href={downloadFileURL(selectedFile)}
              download
              className="btn btn-outline"
              style={{ fontSize: "0.75rem", padding: "3px 10px", whiteSpace: "nowrap", color: "#fff", borderColor: "#fff" }}
              title="Download full file"
            >
              ⬇ Download
            </a>
          </div>
          {loading && <div className="loading">Loading{fullMode ? " full file" : " preview"}…</div>}
          {preview && preview.is_image && selectedFile ? (
            <div className="file-preview" style={{ textAlign: "center", padding: 12 }}>
              <img
                src={rawFileURL(selectedFile)}
                alt={selectedFile}
                style={{ maxWidth: "100%", maxHeight: "70vh", borderRadius: 6, background: "#fff" }}
              />
            </div>
          ) : preview && preview.gdx_symbols && !gdxSymbol ? (
            <GdxSymbolList symbols={preview.gdx_symbols} onSelect={setGdxSymbol} />
          ) : preview && preview.gdx_symbol && preview.columns && preview.rows ? (
            <GdxDataView preview={preview} onBack={() => setGdxSymbol(null)} />
          ) : preview && preview.h5_datasets && !h5Dataset ? (
            <H5DatasetList datasets={preview.h5_datasets} onSelect={setH5Dataset} />
          ) : preview && preview.h5_dataset && preview.columns && preview.rows ? (
            <H5DataView preview={preview} onBack={() => setH5Dataset(null)} />
          ) : preview && preview.columns && preview.rows ? (
            <CsvPreview preview={preview} fullMode={fullMode} onViewFull={() => setFullMode(true)} />
          ) : preview && preview.content ? (
            <HighlightedPreview content={preview.content} filename={selectedFile} truncated={preview.truncated} fullMode={fullMode} onViewFull={() => setFullMode(true)} highlightLine={selectedLine ?? null} />
          ) : !loading && loadError ? (
            <div className="file-preview" style={{ padding: 14, color: "var(--text-muted)" }}>
              <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 6 }}>
                Could not open this file
              </div>
              <div style={{ fontSize: "0.85rem", marginBottom: 8 }}>
                <code style={{ color: "#fbbf24" }}>{selectedFile}</code>
              </div>
              <div style={{ fontSize: "0.8rem", lineHeight: 1.5 }}>
                The path may not exist in this repo, may be outside the repo
                root, or the AI may have cited it without verifying. Try the
                <strong> Search</strong> tab to find a similar file.
              </div>
              <details style={{ marginTop: 10, fontSize: "0.75rem", opacity: 0.7 }}>
                <summary>Details</summary>
                <div style={{ marginTop: 4 }}>{loadError}</div>
              </details>
            </div>
          ) : null}
        </>
      )}

      {!selectedFile && sources.length === 0 && (
        <div style={{ color: "var(--text-muted)" }}>
          Sources and file previews will appear here.
        </div>
      )}
    </div>
  );
}

function HighlightedPreview({ content, filename, truncated, fullMode, onViewFull, highlightLine }: {
  content: string; filename: string; truncated?: boolean; fullMode: boolean; onViewFull: () => void;
  highlightLine?: number | null;
}) {
  const lang = guessLang(filename);
  const highlighted = useMemo(() => {
    try {
      if (lang && lang !== "csv" && lang !== "plaintext")
        return hljs.highlight(content, { language: lang }).value;
      return hljs.highlightAuto(content).value;
    } catch {
      return content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
  }, [content, lang]);

  const lines = highlighted.split("\n");
  const targetLine = highlightLine && highlightLine > 0 ? highlightLine : null;

  // Scroll to the target line whenever it (or the file) changes
  useEffect(() => {
    if (!targetLine) return;
    const id = `right-line-${targetLine}`;
    // Wait for the DOM to render the new content
    const t = setTimeout(() => {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    return () => clearTimeout(t);
  }, [targetLine, content]);

  return (
    <div className="file-preview">
      <div className="hljs" style={{
        background: "var(--bg)", padding: 0, borderRadius: "var(--radius)",
        fontFamily: "var(--font-mono)", fontSize: "0.78rem",
        overflow: "auto", maxHeight: "calc(100vh - 160px)", lineHeight: 1.5,
      }}>
        {lines.map((lineHtml, idx) => {
          const lineNo = idx + 1;
          const isTarget = targetLine === lineNo;
          return (
            <div
              key={idx}
              id={`right-line-${lineNo}`}
              style={{
                display: "flex", minHeight: "1.5em",
                background: isTarget ? "rgba(255, 200, 0, 0.18)" : undefined,
                borderLeft: isTarget ? "3px solid #f59e0b" : "3px solid transparent",
              }}
            >
              <span style={{
                display: "inline-block", width: 40, minWidth: 40, textAlign: "right",
                paddingRight: 8,
                color: isTarget ? "#f59e0b" : "var(--text-muted)",
                opacity: isTarget ? 1 : 0.5,
                fontWeight: isTarget ? 700 : 400,
                userSelect: "none", borderRight: "1px solid var(--border)",
                marginRight: 8, flexShrink: 0,
              }}>{lineNo}</span>
              <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                dangerouslySetInnerHTML={{ __html: lineHtml || "&nbsp;" }} />
            </div>
          );
        })}
      </div>
      {truncated && !fullMode && (
        <button
          className="btn btn-outline"
          style={{ marginTop: 8, fontSize: "0.8rem" }}
          onClick={onViewFull}
        >
          View Full File
        </button>
      )}
    </div>
  );
}

function CsvPreview({ preview, fullMode, onViewFull }: { preview: FilePreviewResponse; fullMode: boolean; onViewFull: () => void }) {
  if (!preview.columns || !preview.rows) return null;
  return (
    <div>
      <div style={{ color: "var(--text-muted)", marginBottom: 6, fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 8 }}>
        <span>
          {preview.rows.length}{preview.total_rows != null && preview.total_rows > preview.rows.length ? ` / ${preview.total_rows}` : ""} rows · {preview.columns.length} columns
          {preview.truncated && !fullMode && " (showing sample)"}
        </span>
        {preview.truncated && !fullMode && (
          <button
            className="btn btn-outline"
            style={{ fontSize: "0.7rem", padding: "2px 8px" }}
            onClick={onViewFull}
          >
            View All Rows
          </button>
        )}
      </div>
      <div className="csv-table-wrap">
        <table>
          <thead>
            <tr>
              {preview.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <tr key={i}>
                {preview.columns!.map((c) => (
                  <td key={c}>{String(row[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


/* ── GDX symbol list ─────────────────────────────────────────────────────── */

function GdxSymbolList({ symbols, onSelect }: { symbols: GdxSymbolInfo[]; onSelect: (name: string) => void }) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? symbols.filter((s) => s.name.toLowerCase().includes(filter.toLowerCase()))
    : symbols;

  return (
    <div>
      <div style={{ color: "var(--text-muted)", marginBottom: 6, fontSize: "0.8rem" }}>
        {symbols.length} symbols in GDX file
      </div>
      <input
        type="text"
        placeholder="Filter symbols…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{
          width: "100%", padding: "5px 8px", marginBottom: 8,
          background: "var(--bg-input, #23272e)", color: "var(--text-primary, #e0e0e0)",
          border: "1px solid var(--border, #333)", borderRadius: 4, fontSize: "0.82rem",
          boxSizing: "border-box",
        }}
      />
      <div className="csv-table-wrap" style={{ maxHeight: "70vh" }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Dims</th>
              <th>Records</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr
                key={s.name}
                onClick={() => onSelect(s.name)}
                style={{ cursor: "pointer" }}
                title={s.description || s.name}
              >
                <td style={{ color: "var(--accent, #2C86B8)" }}>{s.name}</td>
                <td>{s.type}</td>
                <td>{s.dims}</td>
                <td>{s.records.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginTop: 6 }}>
          No symbols match "{filter}"
        </div>
      )}
    </div>
  );
}


/* ── GDX single-symbol data view ─────────────────────────────────────────── */

function GdxDataView({ preview, onBack }: { preview: FilePreviewResponse; onBack: () => void }) {
  if (!preview.columns || !preview.rows) return null;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <button
          className="btn btn-outline"
          style={{ fontSize: "0.75rem", padding: "2px 8px" }}
          onClick={onBack}
        >
          ← Back
        </button>
        <span style={{ fontWeight: 600, color: "var(--accent, #2C86B8)" }}>
          {preview.gdx_symbol}
        </span>
        <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
          {preview.rows.length}{preview.total_rows != null && preview.total_rows > preview.rows.length ? ` / ${preview.total_rows.toLocaleString()}` : ""} rows
          {preview.truncated && " (showing first 500)"}
        </span>
      </div>
      <div className="csv-table-wrap">
        <table>
          <thead>
            <tr>
              {preview.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <tr key={i}>
                {preview.columns!.map((c) => (
                  <td key={c}>{String(row[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


/* ── HDF5 dataset list ───────────────────────────────────────────────────── */

function H5DatasetList({ datasets, onSelect }: { datasets: H5DatasetInfo[]; onSelect: (name: string) => void }) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? datasets.filter((d) => d.name.toLowerCase().includes(filter.toLowerCase()))
    : datasets;

  return (
    <div>
      <div style={{ color: "var(--text-muted)", marginBottom: 6, fontSize: "0.8rem" }}>
        {datasets.length} dataset{datasets.length === 1 ? "" : "s"} in HDF5 file
      </div>
      <input
        type="text"
        placeholder="Filter datasets…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{
          width: "100%", padding: "5px 8px", marginBottom: 8,
          background: "var(--bg-input, #23272e)", color: "var(--text-primary, #e0e0e0)",
          border: "1px solid var(--border, #333)", borderRadius: 4, fontSize: "0.82rem",
          boxSizing: "border-box",
        }}
      />
      <div className="csv-table-wrap" style={{ maxHeight: "70vh" }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Shape</th>
              <th>Dtype</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr
                key={d.name}
                onClick={() => onSelect(d.name)}
                style={{ cursor: "pointer" }}
                title={`${d.name} — ${d.shape} ${d.dtype}`}
              >
                <td style={{ color: "var(--accent, #2C86B8)" }}>{d.name}</td>
                <td>{d.shape}</td>
                <td>{d.dtype}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginTop: 6 }}>
          No datasets match "{filter}"
        </div>
      )}
    </div>
  );
}


/* ── HDF5 single-dataset data view ───────────────────────────────────────── */

function H5DataView({ preview, onBack }: { preview: FilePreviewResponse; onBack: () => void }) {
  if (!preview.columns || !preview.rows) return null;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <button
          className="btn btn-outline"
          style={{ fontSize: "0.75rem", padding: "2px 8px" }}
          onClick={onBack}
        >
          ← Back
        </button>
        <span style={{ fontWeight: 600, color: "var(--accent, #2C86B8)" }}>
          {preview.h5_dataset}
        </span>
        {preview.h5_shape && (
          <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
            shape {preview.h5_shape}
          </span>
        )}
        {preview.h5_dtype && (
          <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
            dtype {preview.h5_dtype}
          </span>
        )}
        <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
          {preview.rows.length}{preview.total_rows != null && preview.total_rows > preview.rows.length ? ` / ${preview.total_rows.toLocaleString()}` : ""} rows
          {preview.truncated && " (showing first 500)"}
        </span>
      </div>
      <div className="csv-table-wrap">
        <table>
          <thead>
            <tr>
              {preview.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <tr key={i}>
                {preview.columns!.map((c) => (
                  <td key={c}>{String(row[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
