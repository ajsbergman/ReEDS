import { useEffect, useState, useMemo } from "react";
import {
  listFilesAPI,
  type FileEntry,
  type FileListResponse,
} from "../lib/api";

type SortKey = "name" | "type" | "size" | "modified";
type SortDir = "asc" | "desc";

interface Props {
  rootPath: string;
  onSelectFile: (path: string) => void;
}

function getExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
}

export default function FileBrowser({ rootPath, onSelectFile }: Props) {
  const [currentPath, setCurrentPath] = useState(rootPath);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

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

  const sortedEntries = useMemo(() => {
    const dirs = entries.filter((e) => e.is_dir);
    const files = entries.filter((e) => !e.is_dir);

    const cmp = (a: FileEntry, b: FileEntry): number => {
      let result = 0;
      switch (sortKey) {
        case "name":
          result = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
          break;
        case "type":
          result = getExtension(a.name).localeCompare(getExtension(b.name)) || a.name.localeCompare(b.name);
          break;
        case "size":
          result = (a.size ?? 0) - (b.size ?? 0);
          break;
        case "modified":
          result = (a.modified_at ?? 0) - (b.modified_at ?? 0);
          break;
      }
      return sortDir === "asc" ? result : -result;
    };

    // Directories always first, then sorted files
    return [...dirs.sort(cmp), ...files.sort(cmp)];
  }, [entries, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

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

  function formatDate(ts: number): string {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

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

      {/* Sort header */}
      <div className="file-sort-bar">
        <span className="sort-col sort-col--name" onClick={() => toggleSort("name")}>
          Name{sortIndicator("name")}
        </span>
        <span className="sort-col sort-col--type" onClick={() => toggleSort("type")}>
          Type{sortIndicator("type")}
        </span>
        <span className="sort-col sort-col--size" onClick={() => toggleSort("size")}>
          Size{sortIndicator("size")}
        </span>
        <span className="sort-col sort-col--date" onClick={() => toggleSort("modified")}>
          Modified{sortIndicator("modified")}
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading">Loading…</div>}

      {sortedEntries.map((e) => (
        <div
          key={e.rel_path}
          className="file-entry"
          onClick={() => handleClick(e)}
        >
          <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
          <span className="name">{e.name}</span>
          <span className="ext">{e.is_dir ? "" : getExtension(e.name)}</span>
          <span className="size">{formatSize(e.size)}</span>
          <span className="date">{formatDate(e.modified_at)}</span>
        </div>
      ))}
    </div>
  );
}
