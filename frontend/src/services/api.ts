/**
 * API client for Deduparr backend
 */

// In production (no Vite dev server), use relative paths for nginx proxy
// In development, use localhost:3001 for backend
const API_BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ||
  (import.meta.env.DEV ? "http://localhost:3001" : "");

export interface DashboardStats {
  total_duplicates: number; // Number of unique items (movies/episodes) with duplicates
  total_duplicate_files: number; // Total number of duplicate files
  pending_duplicates: number;
  approved_duplicates: number;
  processed_duplicates: number;
  space_to_reclaim: number;
  total_deletions: number;
  successful_deletions: number;
  failed_deletions: number;
}

export interface RecentActivity {
  id: number;
  title: string;
  media_type: "movie" | "episode";
  status: "pending" | "approved" | "rejected" | "processed";
  found_at: string;
  space_to_reclaim: number;
}

export interface DeletionActivity {
  id: number;
  file_path: string;
  deleted_at: string;
  is_complete: boolean;
  error: string | null;
}

/** Library titles to scan, per media server ("plex", "jellyfin") */
export type LibrarySelection = Record<string, string[]>;

export interface ScanRequest {
  /** Becomes each server's stored selection; left out, the stored one is scanned */
  libraries?: LibrarySelection;
}

export interface ScanResponse {
  success: boolean;
  message: string;
  duplicates_found: number;
  sets_created: number;
  sets_updated: number;
  sets_removed: number;
  total_sets: number;
}

export interface DuplicateFile {
  id: number;
  file_path: string;
  file_size: number;
  score: number;
  keep: boolean;
  file_metadata: Record<string, string | number | null> | null;
}

export interface DuplicateSet {
  id: number;
  /** Which media server reported this set: "plex", "jellyfin" or "disk" */
  media_server: string;
  item_id: string;
  title: string;
  media_type: string;
  found_at: string;
  status: string;
  space_to_reclaim: number;
  files: DuplicateFile[];
}

export interface ScanStatus {
  total_duplicate_sets: number;
  pending_sets: number;
  total_space_reclaimable: number;
}

export interface DeleteRequest {
  dry_run: boolean;
}

export interface DeleteResponse {
  success: boolean;
  message: string;
  dry_run: boolean;
  files_deleted: number;
  space_reclaimed: number;
  errors: string[];
}

export interface DeleteAllResponse {
  success: boolean;
  message: string;
  dry_run: boolean;
  sets_processed: number;
  files_deleted: number;
  errors: string[];
}

export interface MediaLibrary {
  key: string;
  title: string;
  type: string;
  count: number;
  /** Which media server reported this library: "plex" or "jellyfin" */
  server: string;
}

/** How each media server is named on screen */
export const MEDIA_SERVER_NAMES: Record<string, string> = {
  plex: "Plex",
  jellyfin: "Jellyfin",
};

export interface JellyfinConfig {
  url: string;
  api_key: string;
}

export interface PlexLibrary {
  key: string;
  title: string;
  type: string;
  agent: string;
}

export interface SystemVersionInfo {
  deduparr: string;
  python: string;
  fastapi: string;
  sqlalchemy: string;
  platform: string;
  architecture: string;
}

export interface SystemInfo {
  hostname: string;
  platform: {
    system: string;
    release: string;
    version: string;
    machine: string;
    processor: string;
  };
  python: {
    version: string;
    implementation: string;
    executable: string;
  };
  process: {
    pid: number;
    memory_rss: number;
    memory_vms: number;
    cpu_percent: number;
    threads: number;
  };
  uptime_seconds: number | null;
  timezone: string;
}

export interface AppInfo {
  name: string;
  description: string;
  version: string;
  database: {
    url: string;
    status: string;
    size_bytes: number | null;
  };
  config: {
    log_level: string;
    enable_scheduled_scans: boolean;
    scheduler_description: string;
    data_dir: string;
  };
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
}

export interface LogsResponse {
  logs: LogEntry[];
  total: number;
  limit: number;
}

export interface AppConfig {
  plex_auth_token?: string;
  plex_server_name?: string;
  plex_libraries?: string;
  jellyfin_libraries?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  qbittorrent_url?: string;
  qbittorrent_username?: string;
  qbittorrent_password?: string;
  enable_deep_scan?: string; // "true" or "false" string from backend
  prefer_arr_quality_profile?: string; // "true" or "false" string from backend
  jellyfin_url?: string;
  jellyfin_api_key?: string;
  radarr_path_mappings?: string; // one "<Radarr path>=<media server path>" per line
  sonarr_path_mappings?: string; // one "<Sonarr path>=<media server path>" per line
  email_notifications_enabled?: string; // "true" or "false" string from backend
  notification_email?: string;
  smtp_host?: string;
  smtp_port?: string;
  smtp_user?: string;
  smtp_password?: string;
  smtp_from_email?: string;
}

export interface PlexAuthResponse {
  pin_id: string;
  auth_url: string;
}

export interface PlexAuthCheckResponse {
  success: boolean;
  encrypted_token: string | null;
}

export interface ServiceTestResponse {
  success: boolean;
  /** Present on failure; the backend also fills `message` for some tests */
  error?: string;
  message?: string;
  server_name?: string;
  version?: string;
  platform?: string;
  available_servers?: string[];
}

/** A connection test's outcome, as the UI shows it */
export interface ConnectionTestResult {
  success: boolean;
  error?: string;
  server_name?: string;
  version?: string;
}

/** Run a connection test, keeping whatever reason the API gave for a failure. */
export async function runConnectionTest(
  test: () => Promise<ServiceTestResponse>
): Promise<ConnectionTestResult> {
  try {
    const response = await test();
    return response.success
      ? { success: true, server_name: response.server_name, version: response.version }
      : { success: false, error: response.error ?? response.message ?? "Connection failed" };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : "Connection failed" };
  }
}

export interface ServiceConfig {
  url: string;
  api_key: string;
}

export interface EmailTestConfig {
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  notification_email: string;
}

export interface PlexServer {
  name: string;
  client_identifier: string;
  product: string;
  platform: string;
  owned: boolean;
}

interface SaveResponse {
  status: string;
  message: string;
}

export interface QBittorrentConfig {
  url: string;
  username: string;
  password: string;
}

/** Why a request failed: the API's own explanation when it sent one. */
async function requestError(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const { detail } = JSON.parse(text) as { detail?: unknown };
    if (typeof detail === "string") return new Error(detail);
  } catch {
    // Not JSON, so the text itself is the explanation
  }
  return new Error(text || response.statusText || `Request failed (${response.status})`);
}

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`);

  if (!response.ok) {
    throw await requestError(response);
  }

  return response.json() as Promise<T>;
}

async function postAPI<T, U>(endpoint: string, data: U): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw await requestError(response);
  }

  return response.json() as Promise<T>;
}

async function putAPI<T, U>(endpoint: string, data: U): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw await requestError(response);
  }

  return response.json() as Promise<T>;
}

async function patchAPI<T, U>(endpoint: string, data: U): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    throw await requestError(response);
  }

  return response.json() as Promise<T>;
}

export interface UpdateFileKeepResponse {
  success: boolean;
  message: string;
  file_id: number;
  keep: boolean;
  space_to_reclaim: number;
}

export const statsAPI = {
  getDashboardStats: (): Promise<DashboardStats> =>
    fetchAPI<DashboardStats>("/api/stats/dashboard"),

  getRecentActivity: (limit: number = 10): Promise<RecentActivity[]> =>
    fetchAPI<RecentActivity[]>(`/api/stats/recent-activity?limit=${limit}`),

  getRecentDeletions: (limit: number = 10): Promise<DeletionActivity[]> =>
    fetchAPI<DeletionActivity[]>(`/api/stats/recent-deletions?limit=${limit}`),
};

export const scanAPI = {
  startScan: (request: ScanRequest) =>
    postAPI<ScanResponse, ScanRequest>("/api/scan/start", request),
  // Dev-only: Direct disk scan that creates real DB records (only works when LOG_LEVEL=DEBUG)
  devDiskScan: (paths: string[] = ["/media/movies", "/media/tv"], mediaType = "movie") =>
    postAPI<ScanResponse, { paths: string[]; media_type: string }>("/api/scan/dev/disk-scan", {
      paths,
      media_type: mediaType,
    }),
  getDuplicates: (status?: string, mediaType?: string) => {
    const params = new URLSearchParams();
    if (status) params.append("status", status);
    if (mediaType) params.append("media_type", mediaType);
    const query = params.toString() ? `?${params.toString()}` : "";
    return fetchAPI<DuplicateSet[]>(`/api/scan/duplicates${query}`);
  },
  getScanStatus: () => fetchAPI<ScanStatus>("/api/scan/status"),
  deleteDuplicateSet: (setId: number, dryRun: boolean) =>
    postAPI<DeleteResponse, DeleteRequest>(`/api/scan/duplicates/${setId}/delete`, {
      dry_run: dryRun,
    }),
  deleteAllDuplicateSets: (dryRun: boolean) =>
    postAPI<DeleteAllResponse, DeleteRequest>("/api/scan/duplicates/delete-all", {
      dry_run: dryRun,
    }),
  updateFileKeep: (setId: number, fileId: number, keep: boolean) =>
    patchAPI<UpdateFileKeepResponse, { keep: boolean }>(
      `/api/scan/duplicates/${setId}/files/${fileId}`,
      { keep }
    ),
};

export interface DeepScanSetting {
  enabled: boolean;
}

export interface ArrQualityProfileSetting {
  enabled: boolean;
}

export interface SchedulerConfig {
  enable_scheduled_scans: boolean;
  scan_schedule_mode: "daily" | "interval";
  scheduled_scan_time: string;
  scan_interval_hours: number;
  enable_scheduled_deletion: boolean;
}

export const configAPI = {
  getAll: () => fetchAPI<AppConfig>("/api/config/"),

  // Deep scan configuration
  getDeepScanSetting: () => fetchAPI<DeepScanSetting>("/api/config/deep-scan"),
  updateDeepScanSetting: (enabled: boolean) =>
    putAPI<DeepScanSetting, { enabled: boolean }>("/api/config/deep-scan", { enabled }),

  // Keep the file ranked highest by the Radarr/Sonarr quality profile
  getArrQualityProfileSetting: () =>
    fetchAPI<ArrQualityProfileSetting>("/api/config/arr-quality-profile"),
  updateArrQualityProfileSetting: (enabled: boolean) =>
    putAPI<ArrQualityProfileSetting, { enabled: boolean }>("/api/config/arr-quality-profile", {
      enabled,
    }),

  // Single config value (an empty string clears it)
  setValue: (key: string, value: string) =>
    putAPI<{ key: string; value: string | null }, { value: string }>(`/api/config/${key}`, {
      value,
    }),

  // Scheduler configuration
  getSchedulerConfig: () => fetchAPI<SchedulerConfig>("/api/config/scheduler"),
  updateSchedulerConfig: (config: Partial<SchedulerConfig>) =>
    postAPI<{ status: string; message: string }, Partial<SchedulerConfig>>(
      "/api/config/scheduler",
      config
    ),
};

export const setupAPI = {
  // Plex OAuth
  initiatePlexAuth: () => fetchAPI<PlexAuthResponse>("/api/setup/plex/auth/initiate"),
  checkPlexAuth: (pinId: string) =>
    fetchAPI<PlexAuthCheckResponse>(`/api/setup/plex/auth/check/${pinId}`),

  getPlexServers: (authToken: string) =>
    postAPI<{ servers: PlexServer[] }, { auth_token: string }>("/api/setup/plex/servers", {
      auth_token: authToken,
    }),

  // Service testing
  testPlex: (authToken: string, serverName: string) =>
    postAPI<ServiceTestResponse, { auth_token: string; server_name: string }>(
      "/api/setup/test/plex",
      { auth_token: authToken, server_name: serverName }
    ),
  testJellyfin: (config: JellyfinConfig) =>
    postAPI<ServiceTestResponse, JellyfinConfig>("/api/setup/test/jellyfin", config),
  // Libraries from every configured media server, each tagged with its origin
  getMediaLibraries: () => fetchAPI<MediaLibrary[]>("/api/setup/libraries"),
  // During setup the credentials are not stored yet, so they are passed in
  getJellyfinLibraries: (config: JellyfinConfig) =>
    postAPI<MediaLibrary[], JellyfinConfig>("/api/setup/jellyfin/libraries", config),
  testRadarr: (config: ServiceConfig) =>
    postAPI<ServiceTestResponse, ServiceConfig>("/api/setup/test/radarr", config),
  testSonarr: (config: ServiceConfig) =>
    postAPI<ServiceTestResponse, ServiceConfig>("/api/setup/test/sonarr", config),
  testQBittorrent: (config: QBittorrentConfig) =>
    postAPI<ServiceTestResponse, QBittorrentConfig>("/api/setup/test/qbittorrent", config),
  testEmail: (config: EmailTestConfig) =>
    postAPI<ServiceTestResponse, EmailTestConfig>("/api/setup/test/email", config),

  // Keys left out keep their stored values; secrets are encrypted on save
  saveConfig: (config: Record<string, string>) =>
    postAPI<SaveResponse, { config: Record<string, string> }>("/api/setup/save", { config }),
  completeSetup: () => postAPI<SaveResponse, Record<string, never>>("/api/setup/complete", {}),

  // Plex libraries
  getPlexLibrariesWithAuth: (authToken: string, serverName: string) =>
    postAPI<PlexLibrary[], { auth_token: string; server_name: string }>(
      "/api/setup/plex/libraries",
      { auth_token: authToken, server_name: serverName }
    ),
};

export const systemAPI = {
  getVersionInfo: () => fetchAPI<SystemVersionInfo>("/api/system/version"),
  getSystemInfo: () => fetchAPI<SystemInfo>("/api/system/info"),
  getAppInfo: () => fetchAPI<AppInfo>("/api/system/app"),
  getLogs: (limit = 100) => fetchAPI<LogsResponse>(`/api/system/logs?limit=${limit}`),
};
