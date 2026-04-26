/** Thin API client for the ReEDS-Copilot backend. */

const BASE = "/api"; // proxied by Vite to http://127.0.0.1:8001

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* ── Types ────────────────────────────────────────────────────────────────── */

export interface SourceSnippet {
  file_path: string;
  snippet: string;
  match_type: string;
  score: number;
}

export interface ChatResponse {
  answer: string;
  sources: SourceSnippet[];
}

export interface SearchResult {
  file_path: string;
  snippet: string;
  match_type: string;
  score: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

export interface FileEntry {
  name: string;
  rel_path: string;
  is_dir: boolean;
  size: number | null;
  modified_at: number;
  category: string;
}

export interface FileListResponse {
  path: string;
  entries: FileEntry[];
}

export interface GdxSymbolInfo {
  name: string;
  type: string;
  dims: number;
  records: number;
  description: string;
}

export interface FilePreviewResponse {
  rel_path: string;
  file_type: string;
  content?: string | null;
  columns?: string[] | null;
  rows?: Record<string, unknown>[] | null;
  total_rows?: number | null;
  truncated: boolean;
  is_image?: boolean;
  // GDX-specific
  gdx_symbols?: GdxSymbolInfo[] | null;
  gdx_symbol?: string | null;
}

export interface HealthResponse {
  status: string;
  repo_root: string;
  repo_exists: boolean;
  llm_provider: string;
  model_name: string;
  api_key_set: boolean;
}

/* ── Endpoints ────────────────────────────────────────────────────────────── */

export function chatAPI(
  message: string,
  mode: string,
  selectedPath?: string | null,
): Promise<ChatResponse> {
  return post<ChatResponse>("/chat", {
    message,
    mode,
    selected_path: selectedPath ?? null,
  });
}

export function searchAPI(
  query: string,
  category: string = "all",
  maxResults: number = 10,
): Promise<SearchResponse> {
  return post<SearchResponse>("/search", {
    query,
    category,
    max_results: maxResults,
  });
}

export function listFilesAPI(path: string = "."): Promise<FileListResponse> {
  return request<FileListResponse>(
    `/files/list?path=${encodeURIComponent(path)}`,
  );
}

export function previewFileAPI(
  path: string,
  full: boolean = false,
  gdxSymbol?: string | null,
): Promise<FilePreviewResponse> {
  const params = new URLSearchParams({ path });
  if (full) params.set("full", "true");
  if (gdxSymbol) params.set("gdx_symbol", gdxSymbol);
  return request<FilePreviewResponse>(`/files/preview?${params}`);
}

export function downloadFileURL(path: string): string {
  return `${BASE}/files/download?path=${encodeURIComponent(path)}`;
}

export function rawFileURL(path: string): string {
  return `${BASE}/files/raw?path=${encodeURIComponent(path)}`;
}

export function healthAPI(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export interface UpdateApiKeyResponse {
  success: boolean;
  message: string;
}

export function updateApiKeyAPI(
  apiKey: string,
  provider: string = "anthropic",
  model: string = "",
): Promise<UpdateApiKeyResponse> {
  return post<UpdateApiKeyResponse>("/config/api-key", {
    api_key: apiKey,
    provider,
    model,
  });
}

/* ── Chat Sessions ────────────────────────────────────────────────────────── */

export interface SessionSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

export interface SessionFull {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: { role: string; content: string }[];
}

export function createSessionAPI(title: string = "New Chat"): Promise<SessionFull> {
  return post<SessionFull>("/chat/sessions", { title });
}

export function listSessionsAPI(): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/chat/sessions");
}

export function getSessionAPI(id: string): Promise<SessionFull> {
  return request<SessionFull>(`/chat/sessions/${encodeURIComponent(id)}`);
}

export function updateSessionAPI(
  id: string,
  messages: { role: string; content: string }[],
  title?: string,
): Promise<SessionFull> {
  return request<SessionFull>(`/chat/sessions/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, title }),
  });
}

export function deleteSessionAPI(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/chat/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/* ── Runs ──────────────────────────────────────────────────────────────────── */

export interface CasesFile {
  filename: string;
  suffix: string;
  cases: string[];
}

export interface CasesDetail {
  filename: string;
  cases: string[];
  switches: { switch: string; values: Record<string, string> }[];
}

export interface RunRecord {
  id: string;
  batch_name: string;
  cases_suffix: string;
  cases: string[];
  simult_runs: number;
  target: string;
  status: string;
  created_at: number;
  pid: number | null;
  log_tail: string;
  finished_at: number | null;
  error: string | null;
}

export function listCasesFilesAPI(): Promise<CasesFile[]> {
  return request<CasesFile[]>("/runs/cases-files");
}

export function getCasesDetailAPI(suffix: string): Promise<CasesDetail> {
  return request<CasesDetail>(
    `/runs/cases-files/${encodeURIComponent(suffix || "_default")}`,
  );
}

export interface CondaEnv {
  name: string;
  path: string;
}

export function listCondaEnvsAPI(): Promise<CondaEnv[]> {
  return request<CondaEnv[]>("/runs/conda-envs");
}

export function startRunAPI(body: {
  batch_name: string;
  cases_suffix?: string;
  cases?: string[];
  simult_runs?: number;
  target?: "local" | "hpc";
  conda_env?: string;
  overwrite?: boolean;
}): Promise<RunRecord> {
  return post<RunRecord>("/runs", body);
}

export function listRunsAPI(): Promise<RunRecord[]> {
  return request<RunRecord[]>("/runs");
}

export function getRunAPI(id: string): Promise<RunRecord> {
  return request<RunRecord>(`/runs/${encodeURIComponent(id)}`);
}

export function cancelRunAPI(id: string): Promise<{ success: boolean }> {
  return post<{ success: boolean }>(`/runs/${encodeURIComponent(id)}/cancel`, {});
}

export function deleteRunAPI(id: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/runs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export interface RunFolder {
  name: string;
  path: string;
  has_report: boolean;
  has_outputs: boolean;
  has_gamslog: boolean;
  has_meta: boolean;
  modified_at: number;
}

export function listRunFoldersAPI(): Promise<RunFolder[]> {
  return request<RunFolder[]>("/runs/folders/list");
}

/* ── Compare Cases ────────────────────────────────────────────────────────── */

export interface CompareEntry {
  name: string;
  is_dir: boolean;
  size: number | null;
}

export interface CompareBrowseResponse {
  subdir: string;
  entries: CompareEntry[];
}

export function compareBrowseAPI(cases: string[], subdir: string = ""): Promise<CompareBrowseResponse> {
  const params = cases.map((c) => `cases=${encodeURIComponent(c)}`).join("&");
  const sd = subdir ? `&subdir=${encodeURIComponent(subdir)}` : "";
  return request<CompareBrowseResponse>(`/runs/compare/common-files?${params}${sd}`);
}

export interface CaseFilesResponse {
  case: string;
  subdir: string;
  entries: CompareEntry[];
}

export function compareCaseFilesAPI(caseName: string, subdir: string = ""): Promise<CaseFilesResponse> {
  const sd = subdir ? `&subdir=${encodeURIComponent(subdir)}` : "";
  return request<CaseFilesResponse>(`/runs/compare/case-files?case=${encodeURIComponent(caseName)}${sd}`);
}

export interface CompareDataResponse {
  mode: "side_by_side" | "text_diff" | "image_diff" | "gdx_diff" | "csv_table" | "unsupported";
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
  filename: string;
  subdir?: string;
  cases: string[];
  index_cols: string[];
  value_col: string | null;
  texts?: Record<string, string>;
  image_paths?: Record<string, string>;
  gdx_total_symbols?: Record<string, number>;
  gdx_common_count?: number;
  case_tables?: Record<string, Record<string, unknown>[]>;
}

export function compareDataAPI(
  cases: string[],
  filename: string,
  subdir: string = "",
  maxRowsPerCase: number = 5000,
  filenames?: Record<string, string>,
): Promise<CompareDataResponse> {
  return post<CompareDataResponse>("/runs/compare/data", {
    cases,
    filename,
    subdir,
    max_rows_per_case: maxRowsPerCase,
    ...(filenames ? { filenames } : {}),
  });
}

/* ── Environment Checks ───────────────────────────────────────────────────── */

export interface EnvCheckResult {
  name: string;
  label: string;
  ok: boolean;
  detail: string;
  fixable?: boolean;
}

export function envCheckAPI(condaEnv: string = "reeds2"): Promise<EnvCheckResult[]> {
  return request<EnvCheckResult[]>(
    `/runs/env-check?conda_env=${encodeURIComponent(condaEnv)}`,
  );
}

export function envFixAPI(checkName: string, condaEnv: string = "reeds2"): Promise<{ ok: boolean; detail: string }> {
  return post<{ ok: boolean; detail: string }>("/runs/env-fix", {
    check_name: checkName,
    conda_env: condaEnv,
  });
}

export function getGamsLicenseAPI(): Promise<{ exists: boolean; content: string }> {
  return request<{ exists: boolean; content: string }>("/runs/gams-license");
}

export function saveGamsLicenseAPI(content: string): Promise<{ ok: boolean; detail: string }> {
  return post<{ ok: boolean; detail: string }>("/runs/gams-license", { content });
}
