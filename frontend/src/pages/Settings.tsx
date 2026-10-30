import { useState, useTransition } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PlexServerSelect } from "@/components/PlexServerSelect";
import {
  AlertCircle,
  Check,
  Download,
  Film,
  Loader2,
  Mail,
  Server,
  Settings as SettingsIcon,
  Tv,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  configAPI,
  runConnectionTest,
  setupAPI,
  type ConnectionTestResult,
  type PlexServer,
  type ServiceConfig,
  type ServiceTestResponse,
} from "@/services/api";
import { toast } from "@/components/ui/use-toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const tabs = [
  { id: "general", name: "General", icon: SettingsIcon },
  { id: "plex", name: "Plex", icon: Film },
  { id: "jellyfin", name: "Jellyfin", icon: Server },
  { id: "radarr", name: "Radarr", icon: Film },
  { id: "sonarr", name: "Sonarr", icon: Tv },
  { id: "qbittorrent", name: "qBittorrent", icon: Download },
];

type RecordTest = (service: string, result: ConnectionTestResult) => void;

/** A Test button's pending state, and how to run its test. */
function useConnectionTest(service: string, recordTest: RecordTest) {
  const [isTesting, startTest] = useTransition();
  function run(test: () => Promise<ServiceTestResponse>) {
    startTest(async () => recordTest(service, await runConnectionTest(test)));
  }
  return [isTesting, run] as const;
}

function TestResultBadge({ result, testing }: { result?: ConnectionTestResult; testing: boolean }) {
  if (testing) {
    return (
      <div className="mt-4 p-4 rounded-lg bg-card border border-border">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="w-4 h-4 animate-spin text-primary" />
          <span className="font-medium">Testing connection...</span>
        </div>
        <p className="text-xs text-muted-foreground mt-1">This may take up to 30 seconds</p>
      </div>
    );
  }
  if (!result) return null;

  return (
    <div
      className={cn(
        "mt-4 p-4 rounded-lg border",
        result.success ? "bg-card border-border" : "bg-destructive-light border-destructive-border"
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium">
        {result.success ? (
          <>
            <Check className="w-4 h-4 text-primary" />
            <span className="text-foreground">Connection successful</span>
          </>
        ) : (
          <>
            <X className="w-4 h-4 text-destructive" />
            <span className="text-destructive-foreground">Connection failed</span>
          </>
        )}
      </div>
      {result.error && <p className="text-sm text-destructive-foreground mt-2">{result.error}</p>}
      {result.server_name && (
        <p className="text-sm text-muted-foreground mt-2">Server: {result.server_name}</p>
      )}
      {result.version && (
        <p className="text-sm text-muted-foreground mt-1">Version: {result.version}</p>
      )}
    </div>
  );
}

function GeneralSettings({
  deepScanEnabled,
  setDeepScanEnabled,
  preferArrQualityProfile,
  setPreferArrQualityProfile,
  emailNotificationsEnabled,
  setEmailNotificationsEnabled,
  smtpHost,
  setSmtpHost,
  smtpPort,
  setSmtpPort,
  smtpUser,
  setSmtpUser,
  smtpPassword,
  setSmtpPassword,
  smtpPasswordSaved,
  notificationEmail,
  setNotificationEmail,
  scheduledScansEnabled,
  setScheduledScansEnabled,
  scanMode,
  setScanMode,
  scanTime,
  setScanTime,
  scanIntervalHours,
  setScanIntervalHours,
  scheduledDeletionEnabled,
  setScheduledDeletionEnabled,
  emailResult,
  recordTest,
}: {
  deepScanEnabled: boolean;
  setDeepScanEnabled: (value: boolean) => void;
  preferArrQualityProfile: boolean;
  setPreferArrQualityProfile: (value: boolean) => void;
  emailNotificationsEnabled: boolean;
  setEmailNotificationsEnabled: (value: boolean) => void;
  smtpHost: string;
  setSmtpHost: (value: string) => void;
  smtpPort: string;
  setSmtpPort: (value: string) => void;
  smtpUser: string;
  setSmtpUser: (value: string) => void;
  smtpPassword: string;
  setSmtpPassword: (value: string) => void;
  /** A password is saved; the field is left blank, which keeps and tests it */
  smtpPasswordSaved: boolean;
  notificationEmail: string;
  setNotificationEmail: (value: string) => void;
  scheduledScansEnabled: boolean;
  setScheduledScansEnabled: (value: boolean) => void;
  scanMode: "daily" | "interval";
  setScanMode: (value: "daily" | "interval") => void;
  scanTime: string;
  setScanTime: (value: string) => void;
  scanIntervalHours: number;
  setScanIntervalHours: (value: number) => void;
  scheduledDeletionEnabled: boolean;
  setScheduledDeletionEnabled: (value: boolean) => void;
  emailResult?: ConnectionTestResult;
  recordTest: RecordTest;
}) {
  const [isTesting, runTest] = useConnectionTest("email", recordTest);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">General Settings</h2>
        <p className="text-sm text-muted-foreground mt-1">Configure application-wide preferences</p>
      </div>

      {/* Scan Settings Section */}
      <div className="space-y-4">
        <h3 className="text-base font-semibold text-foreground">Scan Settings</h3>

        <div className="flex items-start space-x-3 p-4 rounded-lg border border-border bg-card">
          <input
            type="checkbox"
            id="enable-deep-scan"
            checked={deepScanEnabled}
            onChange={(e) => setDeepScanEnabled(e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
          />
          <div className="flex-1">
            <label
              htmlFor="enable-deep-scan"
              className="font-medium text-foreground cursor-pointer"
            >
              Enable Deep Scan
            </label>
            <p className="text-sm text-muted-foreground mt-1">
              Also walks the library folders on disk and logs any duplicate files the media server
              does not list. These are only logged, not added as duplicate sets.
            </p>
            <div className="flex items-start gap-2 mt-3">
              <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
              <p className="text-sm text-muted-foreground">
                Please note that this might significantly slow down scans for large libraries.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-start space-x-3 p-4 rounded-lg border border-border bg-card">
          <input
            type="checkbox"
            id="prefer-arr-quality-profile"
            checked={preferArrQualityProfile}
            onChange={(e) => setPreferArrQualityProfile(e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
          />
          <div className="flex-1">
            <label
              htmlFor="prefer-arr-quality-profile"
              className="font-medium text-foreground cursor-pointer"
            >
              Prefer *arr Quality Profile
            </label>
            <p className="text-sm text-muted-foreground mt-1">
              Keep the file Radarr/Sonarr ranks highest: quality order in the item&apos;s quality
              profile, then proper/repack, then custom format score. Deduparr&apos;s score only
              breaks ties.
            </p>
            <div className="flex items-start gap-2 mt-3">
              <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
              <p className="text-sm text-muted-foreground">
                If any file in a duplicate set cannot be evaluated by Radarr/Sonarr, the whole set
                uses Deduparr&apos;s score. Applies to duplicate sets created or updated by the next
                scans.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Email Notifications Section */}
      <div className="space-y-4">
        <h3 className="text-base font-semibold text-foreground">Email Notifications</h3>

        <div className="flex items-start space-x-3 p-4 rounded-lg border border-border bg-card">
          <input
            type="checkbox"
            id="enable-email-notifications"
            checked={emailNotificationsEnabled}
            onChange={(e) => setEmailNotificationsEnabled(e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
          />
          <div className="flex-1">
            <label
              htmlFor="enable-email-notifications"
              className="font-medium text-foreground cursor-pointer"
            >
              Enable Email Notifications
            </label>
            <p className="text-sm text-muted-foreground mt-1">
              Receive email alerts for scan completion, errors, and deletion summaries.
            </p>
          </div>
        </div>

        {emailNotificationsEnabled && (
          <div className="space-y-4 p-4 rounded-lg border border-border bg-card">
            <div className="grid gap-4">
              <div>
                <Label htmlFor="notification-email">Notification Email</Label>
                <Input
                  id="notification-email"
                  type="email"
                  placeholder="notifications@example.com"
                  value={notificationEmail}
                  onChange={(e) => setNotificationEmail(e.target.value)}
                  className="mt-2"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="smtp-host">SMTP Host</Label>
                  <Input
                    id="smtp-host"
                    type="text"
                    placeholder="mail.example.com"
                    value={smtpHost}
                    onChange={(e) => setSmtpHost(e.target.value)}
                    className="mt-2"
                  />
                </div>
                <div>
                  <Label htmlFor="smtp-port">SMTP Port</Label>
                  <Input
                    id="smtp-port"
                    type="number"
                    placeholder="587"
                    value={smtpPort}
                    onChange={(e) => setSmtpPort(e.target.value)}
                    className="mt-2"
                  />
                </div>
              </div>

              <div>
                <Label htmlFor="smtp-user">SMTP Username</Label>
                <Input
                  id="smtp-user"
                  type="text"
                  placeholder="username"
                  value={smtpUser}
                  onChange={(e) => setSmtpUser(e.target.value)}
                  className="mt-2"
                />
              </div>

              <div>
                <Label htmlFor="smtp-password">SMTP Password</Label>
                <Input
                  id="smtp-password"
                  type="password"
                  placeholder={
                    smtpPasswordSaved ? "Saved - type a new password to replace it" : "••••••••"
                  }
                  value={smtpPassword}
                  onChange={(e) => setSmtpPassword(e.target.value)}
                  className="mt-2"
                />
              </div>

              <div className="flex items-start gap-2 mt-2">
                <Mail className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <p className="text-sm text-muted-foreground">
                  Some providers require app-specific passwords instead of your account password.
                </p>
              </div>

              {emailResult && !isTesting && (
                <div className="flex items-center gap-2 text-sm mt-3">
                  {emailResult.success ? (
                    <>
                      <Check className="w-4 h-4 text-primary" />
                      <span className="text-foreground">Test email sent successfully</span>
                    </>
                  ) : (
                    <>
                      <X className="w-4 h-4 text-destructive" />
                      <span className="text-destructive">
                        {emailResult.error || "Connection failed"}
                      </span>
                    </>
                  )}
                </div>
              )}

              <div className="flex items-center gap-3 pt-2">
                <Button
                  onClick={() =>
                    runTest(() =>
                      setupAPI.testEmail({
                        smtp_host: smtpHost,
                        smtp_port: Number(smtpPort),
                        smtp_user: smtpUser,
                        smtp_password: smtpPassword,
                        notification_email: notificationEmail,
                      })
                    )
                  }
                  disabled={
                    isTesting ||
                    !smtpHost ||
                    !smtpPort ||
                    !smtpUser ||
                    !(smtpPassword || smtpPasswordSaved) ||
                    !notificationEmail
                  }
                  className="flex-shrink-0"
                >
                  {isTesting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Test Email
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Scheduler Settings Section */}
      <div className="space-y-4">
        <h3 className="text-base font-semibold text-foreground">Automation</h3>

        {/* Scheduled Scans */}
        <div className="space-y-4 p-4 rounded-lg border border-border bg-card">
          <div className="flex items-start space-x-3">
            <input
              type="checkbox"
              id="enable-scheduled-scans"
              checked={scheduledScansEnabled}
              onChange={(e) => setScheduledScansEnabled(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-600"
            />
            <div className="flex-1">
              <label
                htmlFor="enable-scheduled-scans"
                className="font-medium text-foreground cursor-pointer"
              >
                Enable Scheduled Scans
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Automatically scan for duplicates at regular intervals
              </p>
            </div>
          </div>

          {scheduledScansEnabled && (
            <div className="ml-7 space-y-4">
              <div>
                <Label htmlFor="scan-time" className="block">
                  {scanMode === "daily" ? "Daily Scan Time" : "Starting Time"}
                </Label>
                <Input
                  id="scan-time"
                  type="time"
                  value={scanTime}
                  onChange={(e) => setScanTime(e.target.value)}
                  className="mt-2 max-w-xs"
                />
              </div>

              <div>
                <Label htmlFor="scan-mode" className="block">
                  Schedule Type
                </Label>
                <select
                  id="scan-mode"
                  value={scanMode}
                  onChange={(e) => setScanMode(e.target.value as "daily" | "interval")}
                  className="mt-2 max-w-xs w-full h-10 px-3 rounded-md border border-border bg-card text-foreground focus-visible:outline-none focus-visible:border-muted-foreground"
                >
                  <option value="daily">Daily at specific time</option>
                  <option value="interval">Every X hours</option>
                </select>
              </div>

              {scanMode === "interval" && (
                <div>
                  <Label htmlFor="scan-interval" className="block">
                    Interval (hours)
                  </Label>
                  <Input
                    id="scan-interval"
                    type="number"
                    min="1"
                    max="168"
                    value={scanIntervalHours}
                    onChange={(e) => setScanIntervalHours(parseInt(e.target.value) || 1)}
                    className="mt-2 max-w-xs"
                  />
                  <p className="text-sm text-muted-foreground mt-2">
                    Run every {scanIntervalHours} hour{scanIntervalHours !== 1 ? "s" : ""} starting
                    at {scanTime}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Scheduled Deletion */}
        <div className="space-y-4 p-4 rounded-lg border border-border bg-card">
          <div className="flex items-start space-x-3">
            <input
              type="checkbox"
              id="enable-scheduled-deletion"
              checked={scheduledDeletionEnabled}
              onChange={(e) => setScheduledDeletionEnabled(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-600"
            />
            <div className="flex-1">
              <label
                htmlFor="enable-scheduled-deletion"
                className="font-medium text-foreground cursor-pointer"
              >
                Enable Scheduled Deletion
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Automatically delete all duplicates 30 minutes after each scheduled scan completes
              </p>
              <div className="flex items-start gap-2 mt-2">
                <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <p className="text-sm text-muted-foreground">
                  All duplicates will be deleted automatically - be careful!
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface PlexSettingsProps {
  initialConfig: Awaited<ReturnType<typeof configAPI.getAll>>;
  selectedServer: string;
  setSelectedServer: (value: string) => void;
  result?: ConnectionTestResult;
  recordTest: RecordTest;
}

function PlexSettings({
  initialConfig,
  selectedServer,
  setSelectedServer,
  result,
  recordTest,
}: PlexSettingsProps) {
  // The token itself never reaches the browser: a blank one means the saved one
  const authenticated = !!initialConfig.plex_auth_token;
  const [isTesting, runTest] = useConnectionTest("plex", recordTest);

  const { data: serversData } = useQuery({
    queryKey: ["plexServers"],
    queryFn: () => setupAPI.getPlexServers(""),
    enabled: authenticated,
    staleTime: 5 * 60 * 1000,
  });

  const servers: PlexServer[] = serversData?.servers ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">Plex Configuration</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Authenticate with Plex using OAuth for secure access
        </p>
      </div>

      {!authenticated ? (
        <div className="p-4 rounded-lg bg-muted border border-border">
          <p className="text-sm text-muted-foreground">
            Plex is not configured. Please run the Setup Wizard to authenticate.
          </p>
        </div>
      ) : (
        <>
          <div className="p-4 rounded-lg bg-card border border-border">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Check className="w-4 h-4 text-primary" />
                <span className="text-sm font-medium">Authenticated with Plex</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  window.location.href = "/setup";
                }}
              >
                Logout
              </Button>
            </div>
          </div>

          <PlexServerSelect
            servers={servers}
            value={selectedServer}
            onChange={setSelectedServer}
            disabled={!serversData}
          />

          {selectedServer && (
            <Button
              onClick={() => runTest(() => setupAPI.testPlex("", selectedServer))}
              disabled={isTesting}
            >
              Test Connection
            </Button>
          )}
        </>
      )}

      <TestResultBadge result={result} testing={isTesting} />
    </div>
  );
}

// The connection test of each service that signs in with a URL and API key
const SERVICE_TESTS: Record<string, (config: ServiceConfig) => Promise<ServiceTestResponse>> = {
  jellyfin: setupAPI.testJellyfin,
  radarr: setupAPI.testRadarr,
  sonarr: setupAPI.testSonarr,
};

// The port each service listens on out of the box, for the URL placeholder
const DEFAULT_PORTS: Record<string, number> = {
  jellyfin: 8096,
  radarr: 7878,
  sonarr: 8989,
  qbittorrent: 8080,
};

interface ServiceSettingsProps {
  service: string;
  url: string;
  setUrl: (value: string) => void;
  apiKey?: string;
  setApiKey?: (value: string) => void;
  username?: string;
  setUsername?: (value: string) => void;
  password?: string;
  setPassword?: (value: string) => void;
  pathMappings?: string;
  setPathMappings?: (value: string) => void;
  /** A key or password is saved; the field is left blank, which keeps and tests it */
  secretSaved: boolean;
  result?: ConnectionTestResult;
  recordTest: RecordTest;
}

function ServiceSettings({
  service,
  url,
  setUrl,
  apiKey,
  setApiKey,
  username,
  setUsername,
  password,
  setPassword,
  pathMappings,
  setPathMappings,
  secretSaved,
  result,
  recordTest,
}: ServiceSettingsProps) {
  const isQBittorrent = service === "qbittorrent";
  const [isTesting, runTest] = useConnectionTest(service, recordTest);

  function testConnection() {
    runTest(() =>
      isQBittorrent
        ? setupAPI.testQBittorrent({ url, username: username ?? "", password: password ?? "" })
        : SERVICE_TESTS[service]({ url, api_key: apiKey ?? "" })
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-2 capitalize">{service} Configuration</h3>
        <p className="text-sm text-muted-foreground">Configure your {service} instance</p>
      </div>

      <div>
        <Label htmlFor="url">URL</Label>
        <Input
          id="url"
          type="url"
          placeholder={`http://localhost:${DEFAULT_PORTS[service] ?? 8080}`}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="mt-2"
        />
      </div>

      {isQBittorrent ? (
        <>
          <div>
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              type="text"
              placeholder="admin"
              value={username || ""}
              onChange={(e) => setUsername?.(e.target.value)}
              className="mt-2"
            />
          </div>

          <div>
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              placeholder={secretSaved ? "Saved - type a new password to replace it" : "Password"}
              value={password || ""}
              onChange={(e) => setPassword?.(e.target.value)}
              className="mt-2"
            />
          </div>
        </>
      ) : (
        <div>
          <Label htmlFor="api-key">API Key</Label>
          <Input
            id="api-key"
            type="password"
            placeholder={secretSaved ? "Saved - type a new key to replace it" : "API Key"}
            value={apiKey || ""}
            onChange={(e) => setApiKey?.(e.target.value)}
            className="mt-2"
          />
        </div>
      )}

      {setPathMappings && (
        <div>
          <Label htmlFor="path-mappings">Path mappings (optional)</Label>
          <textarea
            id="path-mappings"
            rows={3}
            placeholder={service === "radarr" ? "/data/movies=/movies" : "/data/series=/series"}
            value={pathMappings || ""}
            onChange={(e) => setPathMappings(e.target.value)}
            className="mt-2 flex w-full rounded-md border border-border bg-card px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:border-muted-foreground"
          />
          <p className="text-sm text-muted-foreground mt-2">
            Only needed when {service === "radarr" ? "Radarr" : "Sonarr"} and your media server see
            the library under different paths. One mapping per line, written as{" "}
            <code>
              path in {service === "radarr" ? "Radarr" : "Sonarr"}=path in the media server
            </code>
            .
          </p>
        </div>
      )}

      <Button onClick={testConnection} disabled={isTesting}>
        Test Connection
      </Button>

      <TestResultBadge result={result} testing={isTesting} />
    </div>
  );
}

export default function Settings() {
  const { data: plexConfig, isPending: plexPending } = useQuery({
    queryKey: ["config"],
    queryFn: () => configAPI.getAll(),
    staleTime: 10 * 60 * 1000,
  });

  const { data: schedulerConfig, isPending: schedulerPending } = useQuery({
    queryKey: ["schedulerConfig"],
    queryFn: () => configAPI.getSchedulerConfig(),
    staleTime: 5 * 60 * 1000,
  });

  if (plexPending || schedulerPending) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  // Use a key to force remount when config changes (React 19 pattern)
  const configKey = JSON.stringify({ plexConfig, schedulerConfig });
  return (
    <SettingsContent
      key={configKey}
      initialConfig={plexConfig || {}}
      schedulerConfig={schedulerConfig}
    />
  );
}

interface SettingsContentProps {
  initialConfig: Awaited<ReturnType<typeof configAPI.getAll>>;
  schedulerConfig: Awaited<ReturnType<typeof configAPI.getSchedulerConfig>> | undefined;
}

function SettingsContent({
  initialConfig,
  schedulerConfig: initialSchedulerConfig,
}: SettingsContentProps) {
  const queryClient = useQueryClient();
  const [isPending, startTransition] = useTransition();
  const [activeTab, setActiveTab] = useState("general");
  const [jellyfinUrl, setJellyfinUrl] = useState(initialConfig.jellyfin_url || "");
  // The API shows a saved key or password only as a mask, so secret fields
  // start blank, and blank keeps what is saved
  const [jellyfinApiKey, setJellyfinApiKey] = useState("");
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});

  function recordTest(service: string, result: ConnectionTestResult) {
    setTestResults((prev) => ({ ...prev, [service]: result }));
  }

  const [deepScanEnabled, setDeepScanEnabled] = useState(initialConfig.enable_deep_scan === "true");
  const [preferArrQualityProfile, setPreferArrQualityProfile] = useState(
    initialConfig.prefer_arr_quality_profile === "true"
  );
  const [emailNotificationsEnabled, setEmailNotificationsEnabled] = useState(
    initialConfig.email_notifications_enabled === "true"
  );
  const [notificationEmail, setNotificationEmail] = useState(
    initialConfig.notification_email || ""
  );
  const [smtpHost, setSmtpHost] = useState(initialConfig.smtp_host || "");
  const [smtpPort, setSmtpPort] = useState(initialConfig.smtp_port || "587");
  const [smtpUser, setSmtpUser] = useState(initialConfig.smtp_user || "");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [selectedServer, setSelectedServer] = useState(initialConfig.plex_server_name || "");
  const [radarrUrl, setRadarrUrl] = useState(initialConfig.radarr_url || "");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [radarrPathMappings, setRadarrPathMappings] = useState(
    initialConfig.radarr_path_mappings || ""
  );
  const [sonarrUrl, setSonarrUrl] = useState(initialConfig.sonarr_url || "");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [sonarrPathMappings, setSonarrPathMappings] = useState(
    initialConfig.sonarr_path_mappings || ""
  );
  const [qbitUrl, setQbitUrl] = useState(initialConfig.qbittorrent_url || "");
  const [qbitUsername, setQbitUsername] = useState(initialConfig.qbittorrent_username || "");
  const [qbitPassword, setQbitPassword] = useState("");

  // Scheduler settings - initialized from prop (component remounts when schedulerConfig changes)
  const [scheduledScansEnabled, setScheduledScansEnabled] = useState(
    initialSchedulerConfig?.enable_scheduled_scans ?? false
  );
  const [scanMode, setScanMode] = useState<"daily" | "interval">(
    initialSchedulerConfig?.scan_schedule_mode ?? "daily"
  );
  const [scanTime, setScanTime] = useState(initialSchedulerConfig?.scheduled_scan_time ?? "02:00");
  const [scanIntervalHours, setScanIntervalHours] = useState(
    initialSchedulerConfig?.scan_interval_hours ?? 24
  );
  const [scheduledDeletionEnabled, setScheduledDeletionEnabled] = useState(
    initialSchedulerConfig?.enable_scheduled_deletion ?? false
  );

  function handleSaveConfiguration() {
    startTransition(async () => {
      try {
        // Save deep scan setting first
        await configAPI.updateDeepScanSetting(deepScanEnabled);
        await configAPI.updateArrQualityProfileSetting(preferArrQualityProfile);

        // Build config object, only including non-empty values
        // Library selections are made on the Scan page, and the Plex token
        // in the setup wizard, so they are left out
        const config: Record<string, string> = {
          plex_server_name: selectedServer,
        };

        if (jellyfinUrl) {
          config.jellyfin_url = jellyfinUrl;
        }
        // A blank secret means "leave the saved one alone", not "clear it"
        if (jellyfinApiKey) {
          config.jellyfin_api_key = jellyfinApiKey;
        }

        // Add email notification settings
        if (emailNotificationsEnabled) {
          config.email_notifications_enabled = "true";
          config.notification_email = notificationEmail;
          config.smtp_host = smtpHost;
          config.smtp_port = smtpPort;
          config.smtp_user = smtpUser;
          if (smtpPassword) config.smtp_password = smtpPassword;
        } else {
          config.email_notifications_enabled = "false";
        }

        // Add optional services only if configured, with a secret typed or saved
        if (radarrUrl && (radarrApiKey || initialConfig.radarr_api_key)) {
          config.radarr_url = radarrUrl;
          if (radarrApiKey) config.radarr_api_key = radarrApiKey;
        }
        if (sonarrUrl && (sonarrApiKey || initialConfig.sonarr_api_key)) {
          config.sonarr_url = sonarrUrl;
          if (sonarrApiKey) config.sonarr_api_key = sonarrApiKey;
        }
        if (qbitUrl && qbitUsername && (qbitPassword || initialConfig.qbittorrent_password)) {
          config.qbittorrent_url = qbitUrl;
          config.qbittorrent_username = qbitUsername;
          if (qbitPassword) config.qbittorrent_password = qbitPassword;
        }

        await setupAPI.saveConfig(config);

        // Path mappings are saved on their own so that clearing them works
        await configAPI.setValue("radarr_path_mappings", radarrPathMappings);
        await configAPI.setValue("sonarr_path_mappings", sonarrPathMappings);

        // Invalidate caches to refetch fresh data from backend
        queryClient.invalidateQueries({ queryKey: ["config"] });
        queryClient.invalidateQueries({ queryKey: ["config", "deep-scan"] });

        // Save scheduler configuration
        await configAPI.updateSchedulerConfig({
          enable_scheduled_scans: scheduledScansEnabled,
          scan_schedule_mode: scanMode,
          scheduled_scan_time: scanTime,
          scan_interval_hours: scanIntervalHours,
          enable_scheduled_deletion: scheduledDeletionEnabled,
        });
        queryClient.invalidateQueries({ queryKey: ["schedulerConfig"] });

        // Clear test results after successful save
        setTestResults({});

        toast({
          title: "Configuration saved",
          description: <div>Your settings have been saved successfully.</div>,
        });
      } catch (error) {
        toast({
          title: "Save failed",
          description: (
            <div>{error instanceof Error ? error.message : "Failed to save configuration"}</div>
          ),
          variant: "destructive",
        });
      }
    });
  }

  function handleCancel() {
    // Reset all state to initial values
    setDeepScanEnabled(initialConfig.enable_deep_scan === "true");
    setPreferArrQualityProfile(initialConfig.prefer_arr_quality_profile === "true");
    setJellyfinUrl(initialConfig.jellyfin_url || "");
    setJellyfinApiKey("");
    setEmailNotificationsEnabled(initialConfig.email_notifications_enabled === "true");
    setNotificationEmail(initialConfig.notification_email || "");
    setSmtpHost(initialConfig.smtp_host || "");
    setSmtpPort(initialConfig.smtp_port || "587");
    setSmtpUser(initialConfig.smtp_user || "");
    setSmtpPassword("");
    setSelectedServer(initialConfig.plex_server_name || "");
    setRadarrUrl(initialConfig.radarr_url || "");
    setRadarrApiKey("");
    setSonarrUrl(initialConfig.sonarr_url || "");
    setSonarrApiKey("");
    setRadarrPathMappings(initialConfig.radarr_path_mappings || "");
    setSonarrPathMappings(initialConfig.sonarr_path_mappings || "");
    setQbitUrl(initialConfig.qbittorrent_url || "");
    setQbitUsername(initialConfig.qbittorrent_username || "");
    setQbitPassword("");

    // Reset scheduler settings
    if (initialSchedulerConfig) {
      setScheduledScansEnabled(initialSchedulerConfig.enable_scheduled_scans);
      setScanMode(initialSchedulerConfig.scan_schedule_mode);
      setScanTime(initialSchedulerConfig.scheduled_scan_time);
      setScanIntervalHours(initialSchedulerConfig.scan_interval_hours);
      setScheduledDeletionEnabled(initialSchedulerConfig.enable_scheduled_deletion);
    }
    toast({
      title: "Changes discarded",
      description: <div>Your unsaved changes have been discarded.</div>,
    });
  }

  return (
    <div className="space-y-6 md:space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-2xl md:text-3xl font-bold text-foreground">Settings</h1>
        <p className="text-sm md:text-base text-muted-foreground mt-1">
          Configure your services and application preferences
        </p>
      </div>

      {/* Tabs Card */}
      <Card className="overflow-hidden">
        {/* Tab Navigation - Horizontal scroll on mobile */}
        <div className="flex border-b bg-muted/30 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-4 md:px-6 py-3 md:py-4 text-xs md:text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex-shrink-0",
                activeTab === tab.id
                  ? "border-primary text-primary bg-background"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              <tab.icon className="w-4 h-4" />
              {tab.name}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="p-4 md:p-6">
          {activeTab === "general" && (
            <GeneralSettings
              deepScanEnabled={deepScanEnabled}
              setDeepScanEnabled={setDeepScanEnabled}
              preferArrQualityProfile={preferArrQualityProfile}
              setPreferArrQualityProfile={setPreferArrQualityProfile}
              emailNotificationsEnabled={emailNotificationsEnabled}
              setEmailNotificationsEnabled={setEmailNotificationsEnabled}
              smtpHost={smtpHost}
              setSmtpHost={setSmtpHost}
              smtpPort={smtpPort}
              setSmtpPort={setSmtpPort}
              smtpUser={smtpUser}
              setSmtpUser={setSmtpUser}
              smtpPassword={smtpPassword}
              setSmtpPassword={setSmtpPassword}
              smtpPasswordSaved={!!initialConfig.smtp_password}
              notificationEmail={notificationEmail}
              setNotificationEmail={setNotificationEmail}
              scheduledScansEnabled={scheduledScansEnabled}
              setScheduledScansEnabled={setScheduledScansEnabled}
              scanMode={scanMode}
              setScanMode={setScanMode}
              scanTime={scanTime}
              setScanTime={setScanTime}
              scanIntervalHours={scanIntervalHours}
              setScanIntervalHours={setScanIntervalHours}
              scheduledDeletionEnabled={scheduledDeletionEnabled}
              setScheduledDeletionEnabled={setScheduledDeletionEnabled}
              emailResult={testResults.email}
              recordTest={recordTest}
            />
          )}
          {activeTab === "plex" && (
            <PlexSettings
              initialConfig={initialConfig}
              selectedServer={selectedServer}
              setSelectedServer={setSelectedServer}
              result={testResults.plex}
              recordTest={recordTest}
            />
          )}
          {activeTab === "jellyfin" && (
            <ServiceSettings
              service="jellyfin"
              url={jellyfinUrl}
              setUrl={setJellyfinUrl}
              apiKey={jellyfinApiKey}
              setApiKey={setJellyfinApiKey}
              secretSaved={!!initialConfig.jellyfin_api_key}
              result={testResults.jellyfin}
              recordTest={recordTest}
            />
          )}
          {activeTab === "radarr" && (
            <ServiceSettings
              service="radarr"
              url={radarrUrl}
              setUrl={setRadarrUrl}
              apiKey={radarrApiKey}
              setApiKey={setRadarrApiKey}
              secretSaved={!!initialConfig.radarr_api_key}
              pathMappings={radarrPathMappings}
              setPathMappings={setRadarrPathMappings}
              result={testResults.radarr}
              recordTest={recordTest}
            />
          )}
          {activeTab === "sonarr" && (
            <ServiceSettings
              service="sonarr"
              url={sonarrUrl}
              setUrl={setSonarrUrl}
              apiKey={sonarrApiKey}
              setApiKey={setSonarrApiKey}
              secretSaved={!!initialConfig.sonarr_api_key}
              pathMappings={sonarrPathMappings}
              setPathMappings={setSonarrPathMappings}
              result={testResults.sonarr}
              recordTest={recordTest}
            />
          )}
          {activeTab === "qbittorrent" && (
            <ServiceSettings
              service="qbittorrent"
              url={qbitUrl}
              setUrl={setQbitUrl}
              username={qbitUsername}
              setUsername={setQbitUsername}
              password={qbitPassword}
              setPassword={setQbitPassword}
              secretSaved={!!initialConfig.qbittorrent_password}
              result={testResults.qbittorrent}
              recordTest={recordTest}
            />
          )}
        </div>
      </Card>

      {/* Actions */}
      <div className="flex flex-col sm:flex-row justify-end items-stretch sm:items-center gap-3">
        <Button
          variant="outline"
          onClick={handleCancel}
          disabled={isPending}
          className="w-full sm:w-auto"
        >
          Cancel
        </Button>
        <Button onClick={handleSaveConfiguration} disabled={isPending} className="w-full sm:w-auto">
          {isPending ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            "Save Configuration"
          )}
        </Button>
      </div>
    </div>
  );
}
