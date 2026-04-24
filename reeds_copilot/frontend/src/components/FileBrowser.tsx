import { useEffect, useState } from "react";
import {
  listFilesAPI,
  type FileEntry,
  type FileListResponse,
} from "../lib/api";

interface Props {
  rootPath: string;
  onSelectFile: (path: string) => void;
}

export default function FileBrowser({ rootPath, onSelectFile }: Props) {
  const [currentPath, setCurrentPath] = useState(rootPath);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentPath(rootPath);
  }, [rootPath]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listFilesAPI(currentPath)
      .then((res: FileListResponse) => {
        if (!cancelled) setEntries(res.entries);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [currentPath]);

  function navigateUp() {
    const parts = currentPath.split("/").filter(Boolean);
    if (parts.length > 0) {
      parts.pop();
      setCurrentPath(parts.join("/") || ".");
    }
  }

  function handleClick(entry: FileEntry) {
    if (entry.is_dir) {
      setCurrentPath(entry.rel_path);
    } else {
      onSelectFile(entry.rel_path);
    }
  }

  function formatSize(size: number | null): string {
    if (size === null) return "";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  // breadcrumb
  const pathParts = currentPath === "." ? [] : currentPath.split("/");

  return (
    <div className="file-browser">
      <div className="breadcrumb">
        <span onClick={() => setCurrentPath(".")}>repo</span>
        {pathParts.map((part, i) => {
          const sub = pathParts.slice(0, i + 1).join("/");
          return (
            <span key={sub}>
              {" / "}
              <span onClick={() => setCurrentPath(sub)}>{part}</span>
            </span>
          );
        })}
        {currentPath !== "." && (
          <span onClick={navigateUp} style={{ marginLeft: 12, cursor: "pointer" }}>
            ⬆ up
          </span>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading">Loading…</div>}

      {entries.map((e) => (
        <div
          key={e.rel_path}
          className="file-entry"
          onClick={() => handleClick(e)}
        >
          <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
          <span className="name">{e.name}</span>
          <span className="size">{formatSize(e.size)}</span>
        </div>
      ))}
    </div>
  );
}
