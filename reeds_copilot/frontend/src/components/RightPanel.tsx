import { useEffect, useState } from "react";
import { previewFileAPI, downloadFileURL, rawFileURL, type FilePreviewResponse, type GdxSymbolInfo } from "../lib/api";
import type { SourceSnippet } from "../lib/api";

interface Props {
  selectedFile: string | null;
  sources: SourceSnippet[];
  onSelectFile: (path: string) => void;
  width?: number;
}

export default function RightPanel({ selectedFile, sources, onSelectFile, width }: Props) {
  const [preview, setPreview] = useState<FilePreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fullMode, setFullMode] = useState(false);
  const [gdxSymbol, setGdxSymbol] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedFile) {
      setPreview(null);
      setFullMode(false);
      setGdxSymbol(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    previewFileAPI(selectedFile, fullMode, gdxSymbol)
      .then((res) => { if (!cancelled) setPreview(res); })
      .catch(() => { if (!cancelled) setPreview(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedFile, fullMode, gdxSymbol]);

  // Reset full mode and gdx symbol when switching files
  useEffect(() => { setFullMode(false); setGdxSymbol(null); }, [selectedFile]);

  return (
    <div className="right-panel" style={width ? { width, minWidth: width } : undefined}>
      {/* Sources section */}
      {sources.length > 0 && (
        <>
          <h3>Sources</h3>
          {sources.map((s, i) => (
            <div key={i} className="source-item" onClick={() => onSelectFile(s.file_path)}>
              <div className="path">{s.file_path}</div>
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
          ) : preview && preview.columns && preview.rows ? (
            <CsvPreview preview={preview} fullMode={fullMode} onViewFull={() => setFullMode(true)} />
          ) : preview && preview.content ? (
            <div className="file-preview">
              <pre>{preview.content}</pre>
              {preview.truncated && !fullMode && (
                <button
                  className="btn btn-outline"
                  style={{ marginTop: 8, fontSize: "0.8rem" }}
                  onClick={() => setFullMode(true)}
                >
                  View Full File
                </button>
              )}
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
