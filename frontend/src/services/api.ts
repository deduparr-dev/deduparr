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

export interface ScanRequest {
  library_names: string[];
  // media_types removed - auto-detected from library type
}

export interface ScanResponse {
  success: boolean;
  message: string;
  duplicates_found: number;
  sets_created: number;
  sets_already_exist: number;
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
  plex_item_id: string;
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
    scan_interval_hours: number;
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

export interface PlexConfig {
  plex_auth_token?: string;
  plex_server_name?: string;
  plex_libraries?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  qbittorrent_url?: string;
  qbittorrent_username?: string;
  qbittorrent_password?: string;
}

export interface SetupStatus {
  plex_configured: boolean;
  radarr_configured: boolean;
  sonarr_configured: boolean;
  qbittorrent_configured: boolean;
  is_complete: boolean;
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
  message: string;
}

export interface ServiceConfig {
  url: string;
  api_key: string;
}

export interface QBittorrentConfig {
  url: string;
  username: string;
  password: string;
}

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`);

  if (!response.ok) {
    throw new Error(`API request failed: ${response.statusText}`);
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
    const error = await response.text();
    throw new Error(`API request failed: ${error || response.statusText}`);
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
    const error = await response.text();
    throw new Error(`API request failed: ${error || response.statusText}`);
  }

  return response.json() as Promise<T>;
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
};

export const configAPI = {
  getAll: () => fetchAPI<PlexConfig>("/api/config/"),
  // Use GET endpoint that reads credentials from DB
  getPlexLibraries: () => fetchAPI<PlexLibrary[]>("/api/setup/plex/libraries"),
};

export const setupAPI = {
  getStatus: () => fetchAPI<SetupStatus>("/api/setup/status"),

  // Plex OAuth
  initiatePlexAuth: () => fetchAPI<PlexAuthResponse>("/api/setup/plex/auth/initiate"),
  checkPlexAuth: (pinId: string) =>
    fetchAPI<PlexAuthCheckResponse>(`/api/setup/plex/auth/check/${pinId}`),

  // Service testing
  testPlex: () => fetchAPI<ServiceTestResponse>("/api/setup/test/plex"),
  testRadarr: (config: ServiceConfig) =>
    postAPI<ServiceTestResponse, ServiceConfig>("/api/setup/test/radarr", config),
  testSonarr: (config: ServiceConfig) =>
    postAPI<ServiceTestResponse, ServiceConfig>("/api/setup/test/sonarr", config),
  testQBittorrent: (config: QBittorrentConfig) =>
    postAPI<ServiceTestResponse, QBittorrentConfig>("/api/setup/test/qbittorrent", config),

  // Service configuration
  configureRadarr: (config: ServiceConfig) =>
    putAPI<ServiceTestResponse, ServiceConfig>("/api/setup/configure/radarr", config),
  configureSonarr: (config: ServiceConfig) =>
    putAPI<ServiceTestResponse, ServiceConfig>("/api/setup/configure/sonarr", config),
  configureQBittorrent: (config: QBittorrentConfig) =>
    putAPI<ServiceTestResponse, QBittorrentConfig>("/api/setup/configure/qbittorrent", config),

  // Plex libraries
  getPlexLibraries: () => fetchAPI<PlexLibrary[]>("/api/setup/plex/libraries"),
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

