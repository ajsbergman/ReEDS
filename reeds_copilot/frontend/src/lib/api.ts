/** Thin API client for the ReEDS-Copilot backend. */

const BASE = "/api"; // proxied by Vite to http://127.0.0.1:8001

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  // Guard: if we got HTML back, the Vite proxy isn't forwarding to the backend
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("text/html")) {
    throw new Error(
      "Proxy error: received HTML instead of JSON. Restart the Vite dev server (Ctrl+C then npm run dev).",
    );
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
  line?: number;
}

export interface ChatAttachment {
  type: "image" | "csv_table" | "file_list" | "run_card";
  // image
  path?: string;
  caption?: string;
  // csv_table
  headers?: string[];
  rows?: unknown[][];
  title?: string;
  // file_list
  files?: { name: string; path: string; size: number; suffix: string }[];
  // run_card
  run_name?: string;
  status?: string;
  detail?: string;
}

export interface ChatResponse {
  answer: string;
  sources: SourceSnippet[];
  attachments: ChatAttachment[];
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

export interface H5DatasetInfo {
  name: string;
  shape: string;
  dtype: string;
  size: number;
  ndim: number;
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
  // HDF5-specific
  h5_datasets?: H5DatasetInfo[] | null;
  h5_dataset?: string | null;
  h5_shape?: string | null;
  h5_dtype?: string | null;
}

export interface HealthResponse {
  status: string;
  repo_root: string;
  repo_exists: boolean;
  llm_provider: string;
  model_name: string;
  api_key_set: boolean;
  stored_keys: string[];  // providers that have a saved key on disk
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
  h5Dataset?: string | null,
): Promise<FilePreviewResponse> {
  const params = new URLSearchParams({ path });
  if (full) params.set("full", "true");
  if (gdxSymbol) params.set("gdx_symbol", gdxSymbol);
  if (h5Dataset) params.set("h5_dataset", h5Dataset);
  return request<FilePreviewResponse>(`/files/preview?${params}`);
}

export function downloadFileURL(path: string): string {
  return `${BASE}/files/download?path=${encodeURIComponent(path)}`;
}

export function rawFileURL(path: string): string {
  return `${BASE}/files/raw?path=${encodeURIComponent(path)}`;
}

/** URL that converts a .pptx to PDF on the backend and serves it inline so
 *  the browser renders it natively. Returns 503 if LibreOffice isn't installed. */
export function pptxViewURL(path: string): string {
  return `${BASE}/files/pptx-view?path=${encodeURIComponent(path)}`;
}

/* ── HPC remote file browsing ──────────────────────────────────────────────── */

export function listHpcFilesAPI(
  host: string,
  user: string,
  path: string,
  password: string = "",
  session_token: string = "",
): Promise<FileListResponse> {
  return post<FileListResponse>("/files/hpc/list",
    { host, user, path, password, session_token });
}

export function previewHpcFileAPI(
  host: string,
  user: string,
  path: string,
  password: string = "",
  lines: number = 200,
  session_token: string = "",
): Promise<FilePreviewResponse> {
  return post<FilePreviewResponse>("/files/hpc/preview",
    { host, user, path, password, lines, session_token });
}

export function disconnectHpcAPI(
  host: string,
  user: string,
  session_token: string = "",
): Promise<{ disconnected: boolean }> {
  return post<{ disconnected: boolean }>("/files/hpc/disconnect",
    { host, user, session_token });
}

export function listHpcCasesFilesAPI(
  host: string,
  user: string,
  reeds_path: string,
  password: string = "",
  session_token: string = "",
): Promise<CasesFile[]> {
  return post<CasesFile[]>("/files/hpc/cases-files",
    { host, user, reeds_path, password, session_token });
}

export interface HpcConnectInfo {
  ok: boolean;
  home: string;
  hostname: string;
  suggested_paths: string[];
  session_token: string;
}

export function hpcConnectAPI(
  host: string,
  user: string,
  password: string = "",
): Promise<HpcConnectInfo> {
  return post<HpcConnectInfo>("/files/hpc/connect", { host, user, password });
}

export interface HpcCondaEnv {
  name: string;
  prefix: string;
}

export function listHpcCondaEnvsAPI(
  host: string,
  user: string,
  password: string = "",
  session_token: string = "",
): Promise<HpcCondaEnv[]> {
  return post<HpcCondaEnv[]>("/files/hpc/conda-envs",
    { host, user, password, session_token });
}

export interface HpcEnvCheck {
  name: string;
  label: string;
  ok: boolean;
  detail: string;
  fixable: boolean;
}

export function hpcEnvCheckAPI(
  host: string,
  user: string,
  reeds_path: string,
  conda_env: string,
  password: string = "",
  session_token: string = "",
): Promise<{ checks: HpcEnvCheck[] }> {
  return post<{ checks: HpcEnvCheck[] }>("/files/hpc/env-check", {
    host, user, password, reeds_path, conda_env, session_token,
  });
}

export interface SlurmJob {
  job_id: string;
  name: string;
  state: string;
  elapsed: string;
  limit: string;
  reason: string;
}

export function hpcSqueueAPI(
  host: string,
  user: string,
  password: string = "",
  session_token: string = "",
): Promise<{ jobs: SlurmJob[] }> {
  return post<{ jobs: SlurmJob[] }>("/files/hpc/squeue",
    { host, user, password, session_token });
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

export function switchProviderAPI(
  provider: string,
  model: string = "",
): Promise<UpdateApiKeyResponse> {
  return post<UpdateApiKeyResponse>("/config/switch-provider", {
    provider,
    model,
  });
}

export function deleteApiKeyAPI(provider: string): Promise<{ deleted: boolean; provider: string }> {
  return request<{ deleted: boolean; provider: string }>(`/config/api-key/${encodeURIComponent(provider)}`, {
    method: "DELETE",
  });
}

/* ── Shutdown ─────────────────────────────────────────────────────────────── */

export interface ShutdownPreview {
  active_local_runs: { id: string; batch_name: string; status: string }[];
  active_hpc_runs: { id: string; batch_name: string; status: string }[];
  safe_to_shutdown: boolean;
}

export function shutdownPreviewAPI(): Promise<ShutdownPreview> {
  return request<ShutdownPreview>("/shutdown/preview");
}

export interface ShutdownResponse {
  shutdown: boolean;
  reason?: string;
  count?: number;
  cancelled_local_runs?: number;
  message: string;
}

export function shutdownBackendAPI(force = false): Promise<ShutdownResponse> {
  return post<ShutdownResponse>("/shutdown", { force });
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

export function generateSessionTitleAPI(
  id: string,
  messages: { role: string; content: string }[],
): Promise<{ title: string }> {
  return request<{ title: string }>(
    `/chat/sessions/${encodeURIComponent(id)}/generate-title`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    },
  );
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
  slurm_job_ids: string[];
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
  hpc_host?: string;
  hpc_user?: string;
  hpc_password?: string;
  hpc_session_token?: string;
  hpc_reeds_path?: string;
  slurm_account?: string;
  slurm_walltime?: string;
  slurm_partition?: string;
  slurm_memory?: string;
  slurm_mail_user?: string;
  slurm_mail_type?: string;
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

/* ── Post-Processing Tools ────────────────────────────────────────────────── */

export interface PPJob {
  id: string;
  type: string;
  status: "queued" | "running" | "completed" | "failed";
  cases: string[];
  report?: string;
  log: string;
  output_dir: string;
  started_at?: number;
  finished_at?: number;
}

export interface PPOutputFile {
  name: string;
  rel_path: string;
  size: number;
  suffix: string;
}

export function ppListReportsAPI(): Promise<{ reports: string[] }> {
  return request<{ reports: string[] }>("/runs/postprocess/reports");
}

export function ppRunCompareCasesAPI(body: {
  cases: string[];
  casenames?: string;
  basecase?: string;
  startyear?: number;
  skip_bokehpivot?: boolean;
  bpreport?: string;
  detailed?: boolean;
  conda_env?: string;
}): Promise<{ job_id: string; status: string }> {
  return post<{ job_id: string; status: string }>("/runs/postprocess/compare-cases", body);
}

export function ppRunBokehReportAPI(body: {
  cases: string[];
  casenames?: string;
  report?: string;
  diff?: boolean;
  basecase?: string;
  conda_env?: string;
}): Promise<{ job_id: string; status: string }> {
  return post<{ job_id: string; status: string }>("/runs/postprocess/bokeh-report", body);
}

export function ppListJobsAPI(): Promise<{ jobs: PPJob[] }> {
  return request<{ jobs: PPJob[] }>("/runs/postprocess/jobs");
}

export function ppGetJobAPI(jobId: string): Promise<PPJob> {
  return request<PPJob>(`/runs/postprocess/jobs/${jobId}`);
}

export function ppDeleteJobAPI(jobId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/runs/postprocess/jobs/${jobId}`, { method: "DELETE" });
}

export function ppListOutputsAPI(jobId: string): Promise<{ files: PPOutputFile[] }> {
  return request<{ files: PPOutputFile[] }>(`/runs/postprocess/jobs/${jobId}/outputs`);
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

/* ── Setup Wizard ─────────────────────────────────────────────────────────── */

export interface SetupStep {
  id: string;
  order: number;
  title: string;
  description: string;
  status: "pass" | "fail" | "running" | "skip";
  detail: string;
  auto_fixable: boolean;
  guide_url?: string;
  guide_steps?: string[];
}

export function setupCheckAllAPI(condaEnv: string = "reeds2"): Promise<SetupStep[]> {
  return request<SetupStep[]>(`/setup/check-all?conda_env=${encodeURIComponent(condaEnv)}`);
}

export function setupFixAPI(
  step: string,
  condaEnv: string = "reeds2",
  gamsLicense: string = "",
): Promise<{ ok: boolean; detail: string }> {
  return post<{ ok: boolean; detail: string }>("/setup/fix", {
    step,
    conda_env: condaEnv,
    gams_license: gamsLicense,
  });
}
