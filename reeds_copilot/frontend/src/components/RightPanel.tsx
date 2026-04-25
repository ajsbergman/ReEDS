import { useEffect, useState } from "react";
import { previewFileAPI, downloadFileURL, type FilePreviewResponse } from "../lib/api";
import type { SourceSnippet } from "../lib/api";

interface Props {
  selectedFile: string | null;
  sources: SourceSnippet[];
  onSelectFile: (path: string) => void;
}

export default function RightPanel({ selectedFile, sources, onSelectFile }: Props) {
  const [preview, setPreview] = useState<FilePreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fullMode, setFullMode] = useState(false);

  useEffect(() => {
    if (!selectedFile) {
      setPreview(null);
      setFullMode(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    previewFileAPI(selectedFile, fullMode)
      .then((res) => { if (!cancelled) setPreview(res); })
      .catch(() => { if (!cancelled) setPreview(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedFile, fullMode]);

  // Reset full mode when switching files
  useEffect(() => { setFullMode(false); }, [selectedFile]);

  return (
    <div className="right-panel">
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
          {preview && preview.columns && preview.rows ? (
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
