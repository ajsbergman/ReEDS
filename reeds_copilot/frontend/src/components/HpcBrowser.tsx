import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import {
  hpcConnectAPI,
  listHpcFilesAPI,
  previewHpcFileAPI,
  disconnectHpcAPI,
  listHpcCasesFilesAPI,
  startRunAPI,
  listRunsAPI,
  getRunAPI,
  cancelRunAPI,
  deleteRunAPI,
  rawHpcURL,
  downloadHpcURL,
  pptxHpcViewURL,
  listHpcRunFoldersAPI,
  hpcCompareBrowseAPI,
  hpcCompareCaseFilesAPI,
  hpcCompareDataAPI,
  type FileEntry,
  type FileListResponse,
  type FilePreviewResponse,
  type CasesFile,
  type RunRecord,
} from "../lib/api";
import {
  GdxSymbolList, GdxDataView, H5DatasetList, H5DataView,
  HighlightedPreview,
} from "./RightPanel";
import HpcPostProcessPanel from "./HpcPostProcessPanel";
import ComparePanel from "./ComparePanel";

type SortKey = "name" | "type" | "size" | "modified";
type SortDir = "asc" | "desc";

const HPC_CLUSTERS: { label: string; host: string }[] = [
  { label: "Kestrel", host: "kestrel.hpc.nlr.gov" },
  { label: "Eagle", host: "eagle.hpc.nlr.gov" },
  { label: "Custom", host: "" },
];

function getExtension(name: string): string {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
}

function formatSize(size: number | null | undefined): string {
  if (size == null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function statusBadge(s: string) {
  const map: Record<string, { bg: string; label: string }> = {
    queued: { bg: "#555", label: "Queued" },
    running: { bg: "#2196f3", label: "Running" },
    completed: { bg: "#4caf50", label: "Completed" },
    failed: { bg: "#e05252", label: "Failed" },
    cancelled: { bg: "#ff9800", label: "Cancelled" },
  };
  const { bg, label } = map[s] ?? { bg: "#888", label: s };
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: "0.75rem", fontWeight: 600, color: "#fff", background: bg,
    }}>
      {label}
    </span>
  );
}

/* --- Main component ------------------------------------------------------ */

// Module-level cache so connection state and form values persist across
// tab switches (HpcBrowser is unmounted whenever the user navigates away
// from the HPC Explorer tab). Mirrors the `hpcCache` in RunPanel.
// NOTE: the password is intentionally NEVER cached -- only the opaque,
// server-issued session token is kept (and that token expires server-side
// after the idle timeout configured in backend SESSION_IDLE_TIMEOUT_SECS).
type HpcExplorerCache = {
  cluster: string;
  host: string;
  user: string;
  sessionToken: string;
  connected: boolean;
  view: "browse" | "runs";
  currentPath: string;
  entries: FileEntry[];
  preview: FilePreviewResponse | null;
  selectedFile: string | null;
  gdxSymbol: string | null;
  h5Dataset: string | null;
  reedsPath: string;
  selectedSuffix: string;
  selectedCases: string[];
  batchName: string;
  simultRuns: number;
  overwrite: boolean;
  slurmAccount: string;
  slurmWalltime: string;
  slurmPartition: string;
  slurmMemory: string;
  slurmMailUser: string;
  slurmMailBegin: boolean;
  slurmMailEnd: boolean;
  slurmMailFail: boolean;
  // Active overlay panels (Compare / Post-Process) so leaving and re-entering
  // the HPC Explorer tab keeps the user where they were.
  compareMode: boolean;
  ppMode: boolean;
  compareTool: "compare_cases" | "bokeh_report";
};

let hpcExplorerCache: HpcExplorerCache | null = null;

/**
 * Best-effort: derive the ReEDS root from a browse path.
 * - "/scratch/me/ReEDS-main/runs/foo/outputs" -> "/scratch/me/ReEDS-main"
 * - "/scratch/me/ReEDS-main/runs"             -> "/scratch/me/ReEDS-main"
 * - "/scratch/me/ReEDS-main"                  -> "/scratch/me/ReEDS-main"
 * Returns null only when given an empty/invalid path.
 */
function inferReedsRoot(currentPath: string): string | null {
  if (!currentPath) return null;
  const p = currentPath.replace(/\/+$/, "");
  const m = p.match(/^(.*?)\/runs(\/|$)/);
  if (m) return m[1] || "/";
  return p;
}

export default function HpcBrowser() {
  /* -- Connection state -- */
  const [cluster, setCluster] = useState(() => hpcExplorerCache?.cluster ?? "kestrel");
  const [hpcHost, setHpcHost] = useState(() => hpcExplorerCache?.host ?? "kestrel.hpc.nlr.gov");
  const [hpcUser, setHpcUser] = useState(() => hpcExplorerCache?.user ?? "");
  const [hpcPassword, setHpcPassword] = useState("");
  // Opaque server-issued token returned by /hpc/connect. After login we
  // wipe the password and use this token for every subsequent HPC API call,
  // matching the mechanism in RunPanel.
  const [hpcSessionToken, setHpcSessionToken] = useState(() => hpcExplorerCache?.sessionToken ?? "");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(() => hpcExplorerCache?.connected ?? false);

  /* -- View toggle (only "browse" remains; runs view was removed) -- */
  const [view] = useState<"browse" | "runs">("browse");

  /* -- HPC-native compare/bokeh panel state -- */
  const [compareMode, setCompareMode] = useState(() => hpcExplorerCache?.compareMode ?? false);
  const [ppMode, setPpMode] = useState(() => hpcExplorerCache?.ppMode ?? false);
  const [compareTool, setCompareTool] = useState<"compare_cases" | "bokeh_report">(() => hpcExplorerCache?.compareTool ?? "compare_cases");

  /* -- File browser state -- */
  const [currentPath, setCurrentPath] = useState(() => hpcExplorerCache?.currentPath ?? "");
  const [entries, setEntries] = useState<FileEntry[]>(() => hpcExplorerCache?.entries ?? []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  /* -- Splitter (resizable preview pane) -- */
  // Width of the preview pane in pixels. Persisted in localStorage so it
  // survives reloads (the rest of cache state is module-scoped only).
  const [previewWidth, setPreviewWidth] = useState<number>(() => {
    const v = parseInt(localStorage.getItem("hpc_preview_width") || "0", 10);
    return Number.isFinite(v) && v >= 200 ? v : 480;
  });
  const splitRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);
  // Mirror of draggingRef in React state so we can re-render and disable
  // pointer-events on the iframe (otherwise the iframe swallows mousemove
  // events and the splitter gets stuck).
  const [isDragging, setIsDragging] = useState(false);
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!draggingRef.current || !splitRef.current) return;
      const rect = splitRef.current.getBoundingClientRect();
      const next = Math.min(
        Math.max(rect.right - e.clientX, 240),
        rect.width - 240,
      );
      setPreviewWidth(next);
    }
    function onUp() {
      if (draggingRef.current) {
        draggingRef.current = false;
        setIsDragging(false);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        localStorage.setItem("hpc_preview_width", String(Math.round(previewWidth)));
      }
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [previewWidth]);

  /* -- Preview state -- */
  const [preview, setPreview] = useState<FilePreviewResponse | null>(() => hpcExplorerCache?.preview ?? null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(() => hpcExplorerCache?.selectedFile ?? null);
  // For GDX/HDF5 drill-down: when the user clicks a symbol/dataset we
  // re-request the preview with the chosen name. Cleared when the file
  // selection changes.
  const [gdxSymbol, setGdxSymbol] = useState<string | null>(() => hpcExplorerCache?.gdxSymbol ?? null);
  const [h5Dataset, setH5Dataset] = useState<string | null>(() => hpcExplorerCache?.h5Dataset ?? null);
  // Track previous symbol/dataset to detect Back (non-null → null) vs new file (null → null)
  const prevGdxSymbolRef = useRef<string | null>(gdxSymbol);
  const prevH5DatasetRef = useRef<string | null>(h5Dataset);

  /* -- Run form state (mirrors RunPanel) -- */
  const [reedsPath, setReedsPath] = useState(() => hpcExplorerCache?.reedsPath ?? "");
  const [casesFiles, setCasesFiles] = useState<CasesFile[]>([]);
  const [selectedSuffix, setSelectedSuffix] = useState(() => hpcExplorerCache?.selectedSuffix ?? "");
  const [availableCases, setAvailableCases] = useState<string[]>([]);
  const [selectedCases, setSelectedCases] = useState<string[]>(() => hpcExplorerCache?.selectedCases ?? []);
  const [batchName, setBatchName] = useState(
    () => hpcExplorerCache?.batchName ?? `v${new Date().toISOString().slice(0, 10).replace(/-/g, "")}_hpc`,
  );
  const [simultRuns, setSimultRuns] = useState(() => hpcExplorerCache?.simultRuns ?? 1);
  const [overwrite, setOverwrite] = useState(() => hpcExplorerCache?.overwrite ?? false);
  const [slurmAccount, setSlurmAccount] = useState(() => hpcExplorerCache?.slurmAccount ?? "");
  const [slurmWalltime, setSlurmWalltime] = useState(() => hpcExplorerCache?.slurmWalltime ?? "2-00:00:00");
  const [slurmPartition, setSlurmPartition] = useState(() => hpcExplorerCache?.slurmPartition ?? "");
  const [slurmMemory, setSlurmMemory] = useState(() => hpcExplorerCache?.slurmMemory ?? "246000");
  const [slurmMailUser, setSlurmMailUser] = useState(() => hpcExplorerCache?.slurmMailUser ?? "");
  const [slurmMailBegin, setSlurmMailBegin] = useState(() => hpcExplorerCache?.slurmMailBegin ?? false);
  const [slurmMailEnd, setSlurmMailEnd] = useState(() => hpcExplorerCache?.slurmMailEnd ?? false);
  const [slurmMailFail, setSlurmMailFail] = useState(() => hpcExplorerCache?.slurmMailFail ?? false);
  const [launching, setLaunching] = useState(false);
  const [runError, setRunError] = useState("");

  /* â”€â”€ Run history state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<RunRecord | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── File browser logic ──────────────────────────────────────────  */
  const loadDirectory = useCallback(
    (path: string) => {
      if (!hpcHost || !hpcUser) return;
      setLoading(true);
      setError(null);
      listHpcFilesAPI(hpcHost, hpcUser, path, "", hpcSessionToken)
        .then((res: FileListResponse) => {
          setEntries(res.entries);
          setCurrentPath(path);
          setConnected(true);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : String(err));
          setEntries([]);
        })
        .finally(() => setLoading(false));
    },
    [hpcHost, hpcUser, hpcSessionToken],
  );

  function handleClusterChange(value: string) {
    setCluster(value);
    const match = HPC_CLUSTERS.find((c) => c.label.toLowerCase() === value);
    if (match && match.host) setHpcHost(match.host);
  }

  async function handleConnect() {
    if (!hpcHost || !hpcUser) { setError("Please enter both hostname and username"); return; }
    setConnecting(true);
    setError(null);
    try {
      const info = await hpcConnectAPI(hpcHost, hpcUser, hpcPassword);
      // Server-issued token replaces the password for all later calls.
      setHpcSessionToken(info.session_token);
      setHpcPassword("");
      setConnected(true);
      // Open the user's home dir if the server gave us one
      const startPath = info.home || "/";
      // loadDirectory uses the new token via state by the next render; call
      // the API directly here so we don't have to wait for re-render.
      try {
        const res = await listHpcFilesAPI(hpcHost, hpcUser, startPath, "", info.session_token);
        setEntries(res.entries);
        setCurrentPath(startPath);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setConnected(false);
    } finally {
      setConnecting(false);
    }
  }

  function handleDisconnect() {
    disconnectHpcAPI(hpcHost, hpcUser, hpcSessionToken).catch(() => {});
    setConnected(false);
    setEntries([]);
    setPreview(null);
    setSelectedFile(null);
    setHpcPassword("");
    setHpcSessionToken("");
    setError(null);
    setCasesFiles([]);
    setCompareMode(false);
    setPpMode(false);
    // Drop cached session so a future tab visit shows the login form,
    // not a "session expired" message.
    hpcExplorerCache = null;
  }

  function handleClick(entry: FileEntry) {
    if (entry.is_dir) {
      loadDirectory(entry.rel_path);
      setPreview(null);
      setSelectedFile(null);
    } else {
      const ext = getExtension(entry.name);
      if (!ext) {
        listHpcFilesAPI(hpcHost, hpcUser, entry.rel_path, "", hpcSessionToken)
          .then((res) => {
            setEntries(res.entries);
            setCurrentPath(entry.rel_path);
            setPreview(null);
            setSelectedFile(null);
          })
          .catch(() => showPreview(entry));
      } else {
        showPreview(entry);
      }
    }
  }

  function showPreview(entry: FileEntry) {
    const ext = getExtension(entry.name).toLowerCase();
    // HTML reports (e.g. bokehpivot output) and PPTX decks are useless as
    // raw source/binary — render them in an iframe inside the preview pane.
    // We skip the text fetch and synthesize a minimal preview object; the
    // render branch keys off file_type to mount the iframe.
    //   .html/.htm → /files/hpc/raw            (served as text/html)
    //   .pptx      → /files/hpc/pptx-view      (converted to PDF via soffice)
    if (ext === "html" || ext === "htm" || ext === "pptx") {
      setSelectedFile(entry.rel_path);
      setGdxSymbol(null);
      setH5Dataset(null);
      setPreviewLoading(false);
      setPreview({
        rel_path: entry.rel_path,
        file_type: "." + ext,
        content: "",
        truncated: false,
      });
      return;
    }
    setSelectedFile(entry.rel_path);
    setGdxSymbol(null);
    setH5Dataset(null);
    setPreviewLoading(true);
    previewHpcFileAPI(hpcHost, hpcUser, entry.rel_path, "", 200, hpcSessionToken)
      .then(setPreview)
      .catch((err) => {
        setPreview({
          rel_path: entry.rel_path,
          file_type: getExtension(entry.name),
          content: `Error loading preview: ${err instanceof Error ? err.message : String(err)}`,
          truncated: false,
        });
      })
      .finally(() => setPreviewLoading(false));
  }

  /* Re-fetch the preview when the user drills into a GDX symbol or HDF5
     dataset. When clearing gdxSymbol/h5Dataset (Back button), re-fetch the
     file without a symbol to get back to the symbol/dataset list. */
  useEffect(() => {
    if (!selectedFile) return;
    if (!gdxSymbol && !h5Dataset) {
      // Only re-fetch if user pressed Back (was non-null → now null),
      // not when a new file is initially selected (null → null).
      const wasGdx = prevGdxSymbolRef.current !== null;
      const wasH5 = prevH5DatasetRef.current !== null;
      prevGdxSymbolRef.current = gdxSymbol;
      prevH5DatasetRef.current = h5Dataset;
      if (!wasGdx && !wasH5) return;
      // Back was pressed — reload the file to show the symbol/dataset list
      setPreviewLoading(true);
      previewHpcFileAPI(hpcHost, hpcUser, selectedFile, "", 200, hpcSessionToken)
        .then(setPreview)
        .catch((err) => {
          setPreview({
            rel_path: selectedFile,
            file_type: getExtension(selectedFile),
            content: `Error reloading file: ${err instanceof Error ? err.message : String(err)}`,
            truncated: false,
          });
        })
        .finally(() => setPreviewLoading(false));
      return;
    }
    prevGdxSymbolRef.current = gdxSymbol;
    prevH5DatasetRef.current = h5Dataset;
    setPreviewLoading(true);
    previewHpcFileAPI(hpcHost, hpcUser, selectedFile, "", 200,
                      hpcSessionToken, gdxSymbol, h5Dataset)
      .then(setPreview)
      .catch((err) => {
        setPreview({
          rel_path: selectedFile,
          file_type: getExtension(selectedFile),
          content: `Error loading dataset/symbol: ${
            err instanceof Error ? err.message : String(err)
          }`,
          truncated: false,
        });
      })
      .finally(() => setPreviewLoading(false));
  }, [gdxSymbol, h5Dataset, selectedFile, hpcHost, hpcUser, hpcSessionToken]);

  function navigateUp() {
    const parts = currentPath.split("/").filter(Boolean);
    if (parts.length >= 1) {
      parts.pop();
      loadDirectory("/" + parts.join("/") || "/");
    }
  }

  function navigateTo(path: string) {
    loadDirectory(path);
    setPreview(null);
    setSelectedFile(null);
  }

  /* â”€â”€ Sorting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  */
  const sortedEntries = useMemo(() => {
    const dirs = entries.filter((e) => e.is_dir);
    const files = entries.filter((e) => !e.is_dir);
    const cmp = (a: FileEntry, b: FileEntry): number => {
      let result = 0;
      switch (sortKey) {
        case "name": result = a.name.localeCompare(b.name, undefined, { sensitivity: "base" }); break;
        case "type": result = getExtension(a.name).localeCompare(getExtension(b.name)) || a.name.localeCompare(b.name); break;
        case "size": result = (a.size ?? 0) - (b.size ?? 0); break;
        case "modified": result = (a.modified_at ?? 0) - (b.modified_at ?? 0); break;
      }
      return sortDir === "asc" ? result : -result;
    };
    return [...dirs.sort(cmp), ...files.sort(cmp)];
  }, [entries, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  }
  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  const pathParts = currentPath.split("/").filter(Boolean);

  /* â”€â”€ Run form logic (mirrors RunPanel) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  */
  function loadCasesFiles(path: string) {
    if (!hpcHost || !hpcUser || !path) return;
    listHpcCasesFilesAPI(hpcHost, hpcUser, path, "", hpcSessionToken)
      .then((files) => {
        setCasesFiles(files);
        const small = files.find((f) => f.suffix === "small");
        const first = small || files[0];
        if (first) {
          setSelectedSuffix(first.suffix);
          setAvailableCases(first.cases);
          setSelectedCases(first.cases);
        }
      })
      .catch(() => setCasesFiles([]));
  }

  function handleSuffixChange(suffix: string) {
    setSelectedSuffix(suffix);
    const file = casesFiles.find((f) => f.suffix === suffix);
    const cases = file?.cases ?? [];
    setAvailableCases(cases);
    setSelectedCases(cases);
  }

  function toggleCase(c: string) {
    setSelectedCases((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c],
    );
  }

  function setReedsPathFromBrowser() {
    setReedsPath(currentPath);
    loadCasesFiles(currentPath);
  }

  // Load cases when reedsPath changes via typing + Enter
  function handleReedsPathKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && reedsPath) loadCasesFiles(reedsPath);
  }

  async function handleLaunch() {
    if (!reedsPath.trim()) { setRunError("Set the ReEDS path first"); return; }
    if (!slurmAccount.trim()) { setRunError("Slurm account (allocation) is required"); return; }
    setRunError("");
    setLaunching(true);
    try {
      await startRunAPI({
        batch_name: batchName.trim(),
        cases_suffix: selectedSuffix || "_default",
        cases: selectedCases.length > 0 ? selectedCases : undefined,
        simult_runs: simultRuns,
        target: "hpc",
        overwrite,
        hpc_host: hpcHost,
        hpc_user: hpcUser,
        hpc_password: hpcSessionToken ? "" : hpcPassword,
        hpc_session_token: hpcSessionToken || undefined,
        hpc_reeds_path: reedsPath.trim(),
        slurm_account: slurmAccount.trim(),
        slurm_walltime: slurmWalltime.trim(),
        slurm_partition: slurmPartition.trim() || undefined,
        slurm_memory: slurmMemory.trim(),
        slurm_mail_user: slurmMailUser.trim() || undefined,
        slurm_mail_type: (() => {
          const types: string[] = [];
          if (slurmMailBegin) types.push("BEGIN");
          if (slurmMailEnd) types.push("END");
          if (slurmMailFail) types.push("FAIL");
          return types.length > 0 && slurmMailUser.trim() ? types.join(",") : undefined;
        })(),
      });
      refreshRuns();
    } catch (e: any) {
      setRunError(e.message ?? "Failed to start run");
    } finally {
      setLaunching(false);
    }
  }

  /* â”€â”€ Run history logic â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  */
  function refreshRuns() {
    listRunsAPI().then((all) => {
      // Only show HPC runs
      setRuns(all.filter((r) => r.target === "hpc"));
    }).catch(() => {});
    if (expandedRun) {
      getRunAPI(expandedRun).then(setExpandedDetail).catch(() => {});
    }
  }

  useEffect(() => {
    if (connected) refreshRuns();
  }, [connected]);

  /* Persist connection + form state to module-level cache so that switching
     tabs (which unmounts this component) does not lose the session. */
  useEffect(() => {
    hpcExplorerCache = {
      cluster, host: hpcHost, user: hpcUser,
      sessionToken: hpcSessionToken, connected, view,
      currentPath, entries,
      preview, selectedFile, gdxSymbol, h5Dataset,
      reedsPath, selectedSuffix, selectedCases,
      batchName, simultRuns, overwrite,
      slurmAccount, slurmWalltime, slurmPartition, slurmMemory,
      slurmMailUser, slurmMailBegin, slurmMailEnd, slurmMailFail,
      compareMode, ppMode, compareTool,
    };
  }, [
    cluster, hpcHost, hpcUser, hpcSessionToken, connected, view,
    currentPath, entries,
    preview, selectedFile, gdxSymbol, h5Dataset,
    reedsPath, selectedSuffix, selectedCases,
    batchName, simultRuns, overwrite,
    slurmAccount, slurmWalltime, slurmPartition, slurmMemory,
    slurmMailUser, slurmMailBegin, slurmMailEnd, slurmMailFail,
    compareMode, ppMode, compareTool,
  ]);

  /* On (re)mount: if we have a cached session token, refresh the directory
     listing so any server-side staleness is detected immediately. If the
     token has expired the API call will 401, and we drop back to the
     login form. */
  useEffect(() => {
    if (!hpcSessionToken || !hpcHost || !hpcUser) return;
    listHpcFilesAPI(hpcHost, hpcUser, currentPath || "/", "", hpcSessionToken)
      .then((res) => {
        setEntries(res.entries);
        setConnected(true);
      })
      .catch((err) => {
        // Session expired or invalid -- clear cached creds and force re-login
        const msg = err instanceof Error ? err.message : String(err);
        setHpcSessionToken("");
        setConnected(false);
        setEntries([]);
        setError(`Session expired -- please reconnect (${msg})`);
      });
    // Run only on mount (deps intentionally empty so cached state restoration
    // happens once when returning to the tab).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* Clear SSH session & password when user closes/refreshes the page */
  useEffect(() => {
    const cleanup = () => {
      if (hpcSessionToken) {
        // Use sendBeacon for reliability during page unload
        const payload = JSON.stringify({
          host: hpcHost, user: hpcUser, session_token: hpcSessionToken,
        });
        navigator.sendBeacon(
          `${import.meta.env.VITE_API_URL ?? "http://localhost:8001/api"}/files/hpc/disconnect`,
          new Blob([payload], { type: "application/json" }),
        );
      }
    };
    window.addEventListener("beforeunload", cleanup);
    return () => window.removeEventListener("beforeunload", cleanup);
  }, [hpcHost, hpcUser, hpcSessionToken]);

  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === "running" || r.status === "queued");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(refreshRuns, 5000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runs]);

  async function handleCancel(id: string) {
    await cancelRunAPI(id).catch(() => {});
    refreshRuns();
  }
  async function handleDelete(id: string) {
    await deleteRunAPI(id).catch(() => {});
    refreshRuns();
  }
  async function toggleExpand(id: string) {
    if (expandedRun === id) { setExpandedRun(null); setExpandedDetail(null); return; }
    setExpandedRun(id);
    try { setExpandedDetail(await getRunAPI(id)); } catch { setExpandedDetail(null); }
  }

  /* â”€â”€ Render â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€  */
  return (
    <div className="hpc-browser">
      {/* â”€â”€ Connection bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="hpc-connection-bar">
        <div className="hpc-connection-row">
          <label>Cluster</label>
          <select value={cluster} onChange={(e) => handleClusterChange(e.target.value)}>
            {HPC_CLUSTERS.map((c) => (
              <option key={c.label} value={c.label.toLowerCase()}>{c.label}</option>
            ))}
          </select>
          <label>Host</label>
          <input type="text" value={hpcHost} onChange={(e) => setHpcHost(e.target.value)}
            placeholder="login.hpc.example.com" disabled={cluster !== "custom"} />
          <label>User</label>
          <input type="text" value={hpcUser} onChange={(e) => setHpcUser(e.target.value)}
            placeholder="username" />
          <label>Password</label>
          <input type="password" value={hpcPassword}
            onChange={(e) => setHpcPassword(e.target.value)}
            disabled={!!hpcSessionToken}
            placeholder={hpcSessionToken ? "— session active —" : "password"} />
          <button className="btn-connect" onClick={handleConnect}
            disabled={connecting || !!hpcSessionToken}>
            {connecting ? "Connecting…" : connected ? "🟢 Connected" : "Connect"}
          </button>
          {connected && (
            <button className="btn-disconnect" onClick={handleDisconnect}>
              🔒 Disconnect
            </button>
          )}
        </div>
        {hpcSessionToken && (
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", padding: "4px 12px" }}>
            🔐 session active (password not stored)
          </div>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!connected && !loading && (
        <div className="hpc-empty-state">
          <p>🖥️ Connect to an HPC cluster to browse remote files and launch runs</p>
          <p style={{ fontSize: "0.85rem", opacity: 0.7 }}>
            Enter your credentials and click Connect. Password-based or SSH key auth supported.
          </p>
        </div>
      )}

      {/* -- File Browser View -- */}
      {connected && !compareMode && !ppMode && (
        <>
          <div className="hpc-connection-bar" style={{ borderTop: "none" }}>
            <div style={{ display: "flex", gap: 6, padding: "6px 12px", alignItems: "center", flexWrap: "wrap" }}>
              <button
                className="btn-primary"
                style={{ padding: "5px 14px", fontWeight: 600 }}>
                📁 Browse files
              </button>
              <div style={{ width: 1, height: 22, background: "var(--border)", margin: "0 6px" }} />
              <button
                onClick={() => {
                  // Always re-derive reedsPath from the current browse path so
                  // navigating the file browser to a different ReEDS root
                  // updates which runs Compare picks up.
                  const inferred = inferReedsRoot(currentPath);
                  if (inferred) setReedsPath(inferred);
                  setCompareMode(true);
                }}
                title="Compare files across HPC runs (CSV side-by-side, text diff, image diff, GDX symbol diff)"
                style={{ padding: "5px 14px" }}>
                ⚖ Compare
              </button>
              <button
                onClick={() => {
                  const inferred = inferReedsRoot(currentPath);
                  if (inferred) setReedsPath(inferred);
                  setCompareTool("compare_cases");
                  setPpMode(true);
                }}
                title="Run post-processing tools directly on the HPC (compare_cases.py, bokehpivot)"
                style={{ padding: "5px 14px" }}>
                📊 Post-Process
              </button>
            </div>
            <div className="hpc-path-input-row">
                <label>Path</label>
                <input type="text" value={currentPath} onChange={(e) => setCurrentPath(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") loadDirectory(currentPath); }}
                  placeholder="/home/user/ReEDS" />
                <button onClick={() => loadDirectory(currentPath)}>Go</button>
              </div>
          </div>

          <div ref={splitRef} className="hpc-content-split" style={{ display: (compareMode || ppMode) ? "none" : "flex" }}>
            {/* Left: file listing */}
            <div className="hpc-file-list" style={{ flex: "1 1 0", minWidth: 0 }}>
              <div className="breadcrumb">
                <span onClick={() => navigateTo("/")}>/</span>
                {pathParts.map((part, i) => {
                  const sub = "/" + pathParts.slice(0, i + 1).join("/");
                  return (
                    <span key={sub}>
                      {" / "}
                      <span onClick={() => navigateTo(sub)}>{part}</span>
                    </span>
                  );
                })}
                {pathParts.length > 0 && (
                  <span onClick={navigateUp} style={{ marginLeft: 12, cursor: "pointer" }}>⬆ up</span>
                )}
              </div>

              <div className="file-sort-bar">
                <span className="sort-col sort-col--name" onClick={() => toggleSort("name")}>Name{sortIndicator("name")}</span>
                <span className="sort-col sort-col--type" onClick={() => toggleSort("type")}>Type{sortIndicator("type")}</span>
                <span className="sort-col sort-col--size" onClick={() => toggleSort("size")}>Size{sortIndicator("size")}</span>
                <span className="sort-col sort-col--date" onClick={() => toggleSort("modified")}>Modified{sortIndicator("modified")}</span>
              </div>

              {loading && <div className="loading">Loading…</div>}
              {!loading && sortedEntries.length === 0 && (
                <div className="loading" style={{ opacity: 0.6 }}>Empty directory</div>
              )}
              {sortedEntries.map((e) => (
                <div key={e.rel_path}
                  className={`file-entry${selectedFile === e.rel_path ? " selected" : ""}`}
                  onClick={() => handleClick(e)}>
                  <span className="icon">{e.is_dir ? "📁" : "📄"}</span>
                  <span className="name">{e.name}</span>
                  <span className="ext">{e.is_dir ? "" : getExtension(e.name)}</span>
                  <span className="size">{formatSize(e.size)}</span>
                  <span className="date">{formatDate(e.modified_at)}</span>
                </div>
              ))}
            </div>

            {/* Right: inline preview */}
            {/* Draggable splitter */}
            <div
              className="hpc-splitter"
              onMouseDown={(e) => {
                e.preventDefault();
                draggingRef.current = true;
                setIsDragging(true);
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
              }}
              title="Drag to resize"
            />
            <div className="hpc-preview-pane" style={{ flex: `0 0 ${previewWidth}px`, minWidth: 0 }}>
              {!preview && !previewLoading && (
                <div className="hpc-empty-state" style={{ padding: "2rem" }}><p>Select a file to preview</p></div>
              )}
              {previewLoading && <div className="loading">Loading preview…</div>}
              {preview && !previewLoading && (
                <div className="hpc-preview-content">
                  <div className="hpc-preview-header">
                    <strong>{preview.rel_path.split("/").pop()}</strong>
                    <span style={{ marginLeft: 8, opacity: 0.6 }}>{preview.file_type}</span>
                    {preview.truncated && (
                      <span style={{ marginLeft: 8, color: "var(--accent)", fontSize: "0.8rem" }}>(truncated)</span>
                    )}
                    <a
                      href={downloadHpcURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                      className="btn btn-outline"
                      style={{ marginLeft: "auto", fontSize: "0.75rem", padding: "3px 10px", color: "#fff" }}
                      title="Download the original file from HPC to your computer"
                      download
                    >
                      ⬇ Download
                    </a>
                    {preview.file_type === ".pptx" && (
                      <a
                        href={pptxHpcViewURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                        target="_blank" rel="noreferrer"
                        className="btn btn-outline"
                        style={{ marginLeft: 6, fontSize: "0.75rem", padding: "3px 10px", color: "#fff" }}
                        title="Convert to PDF and open in browser"
                      >
                        Open in browser ↗
                      </a>
                    )}
                    {(preview.file_type === ".html" || preview.file_type === ".htm") && (
                      <a
                        href={rawHpcURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                        target="_blank" rel="noreferrer"
                        className="btn btn-outline"
                        style={{ marginLeft: 6, fontSize: "0.75rem", padding: "3px 10px", color: "#fff" }}
                        title="Open the rendered report in a new browser tab"
                      >
                        Open in new tab ↗
                      </a>
                    )}
                  </div>

                  {/* ── HTML report (rendered in iframe) ── */}
                  {preview.file_type === ".html" || preview.file_type === ".htm" ? (
                    <iframe
                      src={rawHpcURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                      title={preview.rel_path}
                      style={{
                        width: "100%",
                        height: "calc(100vh - 200px)",
                        border: "none",
                        background: "#fff",
                        // Disable iframe mouse capture while dragging the
                        // splitter so window-level mousemove events fire.
                        pointerEvents: isDragging ? "none" : "auto",
                      }}
                      sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
                    />
                  /* ── PPTX preview (converted to PDF on the backend) ── */
                  ) : preview.file_type === ".pptx" ? (
                    <iframe
                      src={pptxHpcViewURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                      title={preview.rel_path}
                      style={{
                        width: "100%",
                        height: "calc(100vh - 200px)",
                        border: "none",
                        background: "#fff",
                        pointerEvents: isDragging ? "none" : "auto",
                      }}
                    />
                  /* ── Image preview ── */
                  ) : preview.is_image ? (
                    <div style={{ textAlign: "center", padding: 12, overflow: "auto" }}>
                      <img
                        src={rawHpcURL(hpcHost, hpcUser, hpcSessionToken, preview.rel_path)}
                        alt={preview.rel_path}
                        style={{ maxWidth: "100%", maxHeight: "70vh", borderRadius: 6, background: "#fff" }}
                      />
                    </div>
                  /* ── GDX: symbol list → drill-down ── */
                  ) : preview.gdx_symbols && !preview.gdx_symbol ? (
                    <div style={{ padding: 12 }}>
                      <GdxSymbolList symbols={preview.gdx_symbols} onSelect={setGdxSymbol} />
                    </div>
                  ) : preview.gdx_symbol && preview.columns && preview.rows ? (
                    <div style={{ padding: 12 }}>
                      <GdxDataView preview={preview} onBack={() => setGdxSymbol(null)} />
                    </div>
                  /* ── HDF5: dataset list → drill-down ── */
                  ) : preview.h5_datasets && !preview.h5_dataset ? (
                    <div style={{ padding: 12 }}>
                      <H5DatasetList datasets={preview.h5_datasets} onSelect={setH5Dataset} />
                    </div>
                  ) : preview.h5_dataset && preview.columns && preview.rows ? (
                    <div style={{ padding: 12 }}>
                      <H5DataView preview={preview} onBack={() => setH5Dataset(null)} />
                    </div>
                  /* ── CSV / table preview ── */
                  ) : preview.columns && preview.rows ? (
                    <div className="csv-preview-wrapper" style={{ overflow: "auto", maxHeight: "calc(100vh - 200px)" }}>
                      <table className="csv-preview">
                        <thead><tr>{preview.columns.map((col) => <th key={col}>{col}</th>)}</tr></thead>
                        <tbody>
                          {preview.rows.map((row, i) => (
                            <tr key={i}>{preview.columns!.map((col) => <td key={col}>{String(row[col] ?? "")}</td>)}</tr>
                          ))}
                        </tbody>
                      </table>
                      {preview.total_rows != null && (
                        <div style={{ padding: "4px 8px", fontSize: "0.8rem", opacity: 0.6 }}>
                          Showing {preview.rows.length} of {preview.total_rows} rows
                        </div>
                      )}
                    </div>
                  ) : (
                    <HighlightedPreview
                      content={preview.content || ""}
                      filename={selectedFile || ""}
                      truncated={preview.truncated}
                      fullMode={false}
                      onViewFull={() => { /* not supported in HPC preview */ }}
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </>

      )}

      {/* -- HPC Compare (direct, mirrors Outputs Explorer) -- */}
      {connected && compareMode && (
        <div style={{ flex: 1, overflow: "auto" }}>
          {!reedsPath && (
            <div className="hpc-empty-state" style={{ padding: 14 }}>
              <p>👉 Set a <strong>ReEDS path</strong> first — navigate to your
                ReEDS root in 📁 Browse files (the path containing <code>runs/</code>),
                or type it here:</p>
              <input type="text" value={reedsPath}
                onChange={(e) => setReedsPath(e.target.value)}
                placeholder={`/scratch/${hpcUser || "user"}/ReEDS-main`}
                style={{ width: "100%", padding: "6px 10px", marginTop: 6 }} />
              <div style={{ marginTop: 10 }}>
                <button onClick={() => setCompareMode(false)}>Cancel</button>
              </div>
            </div>
          )}
          {reedsPath && (
            <ComparePanel
              onClose={() => setCompareMode(false)}
              banner={`⚖ Comparing HPC runs at ${hpcHost}:${reedsPath}/runs (files fetched on-demand via SFTP).`}
              listRunsFn={() => listHpcRunFoldersAPI(hpcHost, hpcUser, reedsPath, hpcSessionToken)}
              browseFn={(cases, subdir) =>
                hpcCompareBrowseAPI(
                  { host: hpcHost, user: hpcUser, session_token: hpcSessionToken, reeds_path: reedsPath },
                  cases, subdir,
                )
              }
              caseFilesFn={(caseName, subdir) =>
                hpcCompareCaseFilesAPI(
                  { host: hpcHost, user: hpcUser, session_token: hpcSessionToken, reeds_path: reedsPath },
                  caseName, subdir,
                )
              }
              dataFn={(cases, filename, subdir, max, filenames) =>
                hpcCompareDataAPI(
                  { host: hpcHost, user: hpcUser, session_token: hpcSessionToken, reeds_path: reedsPath },
                  cases, filename, subdir, max, filenames,
                )
              }
              imageURLFn={(remotePath) => rawHpcURL(hpcHost, hpcUser, hpcSessionToken, remotePath)}
            />
          )}
        </div>
      )}

      {/* -- HPC Post-Process (compare_cases.py, bokeh report) -- */}
      {connected && ppMode && (
        <div style={{ flex: 1, overflow: "auto", padding: "8px 12px" }}>
          {!reedsPath && (
            <div className="hpc-empty-state" style={{ padding: 14 }}>
              <p>👉 Set a <strong>ReEDS path</strong> first — navigate to your
                ReEDS root in 📁 Browse files (the path containing <code>runs/</code>),
                or type it here:</p>
              <input type="text" value={reedsPath}
                onChange={(e) => setReedsPath(e.target.value)}
                placeholder={`/scratch/${hpcUser || "user"}/ReEDS-main`}
                style={{ width: "100%", padding: "6px 10px", marginTop: 6 }} />
              <div style={{ marginTop: 10 }}>
                <button onClick={() => setPpMode(false)}>Cancel</button>
              </div>
            </div>
          )}
          {reedsPath && (
            <HpcPostProcessPanel
              onClose={() => setPpMode(false)}
              host={hpcHost}
              user={hpcUser}
              sessionToken={hpcSessionToken}
              reedsPath={reedsPath}
              initialTool={compareTool}
              onOpenRemotePath={(p) => { setPpMode(false); loadDirectory(p); }}
            />
          )}
        </div>
      )}
    </div>
  );
}
