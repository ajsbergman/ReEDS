import { useEffect, useState } from "react";
import { previewFileAPI, type FilePreviewResponse } from "../lib/api";
import type { SourceSnippet } from "../lib/api";

interface Props {
  selectedFile: string | null;
  sources: SourceSnippet[];
  onSelectFile: (path: string) => void;
}

export default function RightPanel({ selectedFile, sources, onSelectFile }: Props) {
  const [preview, setPreview] = useState<FilePreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedFile) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    previewFileAPI(selectedFile)
      .then((res) => { if (!cancelled) setPreview(res); })
      .catch(() => { if (!cancelled) setPreview(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedFile]);

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
          <h3 style={{ marginTop: sources.length > 0 ? 18 : 0 }}>
            Preview: {selectedFile}
          </h3>
          {loading && <div className="loading">Loading preview…</div>}
          {preview && preview.columns && preview.rows ? (
            <CsvPreview preview={preview} />
          ) : preview && preview.content ? (
            <div className="file-preview">
              <pre>{preview.content}</pre>
              {preview.truncated && (
                <div style={{ color: "var(--text-muted)", marginTop: 6 }}>
                  (truncated)
                </div>
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

function CsvPreview({ preview }: { preview: FilePreviewResponse }) {
  if (!preview.columns || !preview.rows) return null;
  return (
    <div>
      <div style={{ color: "var(--text-muted)", marginBottom: 6, fontSize: "0.8rem" }}>
        {preview.total_rows ?? "?"} rows · {preview.columns.length} columns
        {preview.truncated && " (showing sample)"}
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
