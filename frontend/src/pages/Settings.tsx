import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Film,
  Tv,
  Download,
  Check,
  X,
  Loader2,
  Settings as SettingsIcon,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { configAPI } from "@/services/api";
import { toast } from "@/components/ui/use-toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface PlexServer {
  name: string;
  client_identifier: string;
  product: string;
  platform: string;
  owned: boolean;
}

const tabs = [
  { id: "general", name: "General", icon: SettingsIcon },
  { id: "plex", name: "Plex", icon: Film },
  { id: "radarr", name: "Radarr", icon: Film },
  { id: "sonarr", name: "Sonarr", icon: Tv },
  { id: "qbittorrent", name: "qBittorrent", icon: Download },
];

interface TestResult {
  success: boolean;
  loading?: boolean;
  error?: string;
  version?: string;
  server_name?: string;
}

function TestResultBadge({
  service,
  testResults,
}: {
  service: string;
  testResults: Record<string, TestResult>;
}) {
  const result = testResults[service];
  if (!result) return null;

  if (result.loading) {
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
}: {
  deepScanEnabled: boolean;
  setDeepScanEnabled: (value: boolean) => void;
}) {
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
              Scans filesystem directly alongside Plex API to find duplicates that might be missed - case-sensitivity, cross-directory files, and similar.
            </p>
            <div className="flex items-start gap-2 mt-3">
              <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
              <p className="text-sm text-muted-foreground">
                Please note that this might significantly slow down scans for large libraries.
              </p>
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
  setTestResults: React.Dispatch<React.SetStateAction<Record<string, TestResult>>>;
  testResults: Record<string, TestResult>;
}

function PlexSettings({
  initialConfig,
  selectedServer,
  setSelectedServer,
  setTestResults,
  testResults,
}: PlexSettingsProps) {
  const authenticated = !!initialConfig.plex_auth_token;
  const encryptedToken = initialConfig.plex_auth_token || "";

  const { data: serversData } = useQuery({
    queryKey: ["plexServers", encryptedToken],
    queryFn: async () => {
      if (!encryptedToken) return { servers: [] };
      const response = await fetch(`/api/setup/plex/servers/${encryptedToken}`);
      return response.json();
    },
    enabled: !!encryptedToken,
    staleTime: 5 * 60 * 1000,
  });

  const servers: PlexServer[] = serversData?.servers || [];

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

          <div>
            <Label htmlFor="server">Select Plex Server</Label>
            <select
              id="server"
              value={selectedServer}
              onChange={(e) => setSelectedServer(e.target.value)}
              className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              disabled={!serversData}
            >
              <option value="">Choose a server...</option>
              {servers.map((server) => (
                <option key={server.client_identifier} value={server.name}>
                  {server.name} ({server.platform})
                </option>
              ))}
            </select>
          </div>

          {selectedServer && (
            <Button
              onClick={async () => {
                setTestResults((prev) => ({
                  ...prev,
                  plex: { success: false, loading: true },
                }));
                try {
                  const response = await fetch("/api/setup/test/plex", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      auth_token: encryptedToken,
                      server_name: selectedServer,
                    }),
                  });
                  const result = await response.json();
                  setTestResults((prev) => ({
                    ...prev,
                    plex: {
                      success: result.success,
                      server_name: result.server_name,
                      version: result.version,
                      error: result.success ? undefined : result.message,
                    },
                  }));
                } catch {
                  setTestResults((prev) => ({
                    ...prev,
                    plex: {
                      success: false,
                      error: "Connection failed",
                    },
                  }));
                }
              }}
            >
              Test Connection
            </Button>
          )}
        </>
      )}

      <TestResultBadge service="plex" testResults={testResults} />
    </div>
  );
}

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
  setTestResults: React.Dispatch<React.SetStateAction<Record<string, TestResult>>>;
  testResults: Record<string, TestResult>;
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
  setTestResults,
  testResults,
}: ServiceSettingsProps) {
  const isQBittorrent = service === "qbittorrent";

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
          placeholder={
            isQBittorrent
              ? "http://localhost:8080"
              : `http://localhost:${service === "radarr" ? "7878" : "8989"}`
          }
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
              placeholder="Password"
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
            placeholder="API Key"
            value={apiKey || ""}
            onChange={(e) => setApiKey?.(e.target.value)}
            className="mt-2"
          />
        </div>
      )}

      <Button
        onClick={async () => {
          setTestResults((prev) => ({
            ...prev,
            [service]: { success: false, loading: true },
          }));

          try {
            const endpoint = isQBittorrent
              ? "/api/setup/test/qbittorrent"
              : `/api/setup/test/${service}`;
            const response = await fetch(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(
                isQBittorrent ? { url, username, password } : { url, api_key: apiKey }
              ),
            });

            const result = await response.json();
            setTestResults((prev) => ({
              ...prev,
              [service]: {
                success: result.success,
                version: result.version,
                error: result.success ? undefined : result.message,
              },
            }));
          } catch (error) {
            setTestResults((prev) => ({
              ...prev,
              [service]: {
                success: false,
                error: error instanceof Error ? error.message : "Connection failed",
              },
            }));
          }
        }}
      >
        Test Connection
      </Button>

      <TestResultBadge service={service} testResults={testResults} />
    </div>
  );
}

export default function Settings() {
  const { data: plexConfig, isLoading } = useQuery({
    queryKey: ["plexConfig"],
    queryFn: () => configAPI.getAll(),
    staleTime: 10 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  // Use a key to force remount when config changes (React 19 pattern)
  const configKey = JSON.stringify(plexConfig);
  return <SettingsContent key={configKey} initialConfig={plexConfig || {}} />;
}

interface SettingsContentProps {
  initialConfig: Awaited<ReturnType<typeof configAPI.getAll>>;
}

function SettingsContent({ initialConfig }: SettingsContentProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("general");
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [isSaving, setIsSaving] = useState(false);

  const [deepScanEnabled, setDeepScanEnabled] = useState(initialConfig.enable_deep_scan === "true");
  const [selectedServer, setSelectedServer] = useState(initialConfig.plex_server_name || "");
  const [radarrUrl, setRadarrUrl] = useState(initialConfig.radarr_url || "");
  const [radarrApiKey, setRadarrApiKey] = useState(initialConfig.radarr_api_key || "");
  const [sonarrUrl, setSonarrUrl] = useState(initialConfig.sonarr_url || "");
  const [sonarrApiKey, setSonarrApiKey] = useState(initialConfig.sonarr_api_key || "");
  const [qbitUrl, setQbitUrl] = useState(initialConfig.qbittorrent_url || "");
  const [qbitUsername, setQbitUsername] = useState(initialConfig.qbittorrent_username || "");
  const [qbitPassword, setQbitPassword] = useState(initialConfig.qbittorrent_password || "");

  async function handleSaveConfiguration() {
    setIsSaving(true);
    try {
      // Save deep scan setting first
      await configAPI.updateDeepScanSetting(deepScanEnabled);

      // Build config object, only including non-empty values
      const config: Record<string, string> = {
        plex_auth_token: initialConfig.plex_auth_token || "",
        plex_server_name: selectedServer,
        plex_libraries: initialConfig.plex_libraries || "",
      };

      // Add optional services only if configured
      if (radarrUrl && radarrApiKey) {
        config.radarr_url = radarrUrl;
        config.radarr_api_key = radarrApiKey;
      }
      if (sonarrUrl && sonarrApiKey) {
        config.sonarr_url = sonarrUrl;
        config.sonarr_api_key = sonarrApiKey;
      }
      if (qbitUrl && qbitUsername && qbitPassword) {
        config.qbittorrent_url = qbitUrl;
        config.qbittorrent_username = qbitUsername;
        config.qbittorrent_password = qbitPassword;
      }

      const response = await fetch("/api/setup/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to save configuration");
      }

      // Invalidate caches to refetch fresh data from backend
      queryClient.invalidateQueries({ queryKey: ["plexConfig"] });
      queryClient.invalidateQueries({ queryKey: ["config", "deep-scan"] });

      toast({
        title: "Configuration saved",
        description: "Your settings have been saved successfully.",
      });
    } catch (error) {
      toast({
        title: "Save failed",
        description: error instanceof Error ? error.message : "Failed to save configuration",
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  }

  function handleCancel() {
    // Reset all state to initial values
    setDeepScanEnabled(initialConfig.enable_deep_scan === "true");
    setSelectedServer(initialConfig.plex_server_name || "");
    setRadarrUrl(initialConfig.radarr_url || "");
    setRadarrApiKey(initialConfig.radarr_api_key || "");
    setSonarrUrl(initialConfig.sonarr_url || "");
    setSonarrApiKey(initialConfig.sonarr_api_key || "");
    setQbitUrl(initialConfig.qbittorrent_url || "");
    setQbitUsername(initialConfig.qbittorrent_username || "");
    setQbitPassword(initialConfig.qbittorrent_password || "");

    toast({
      title: "Changes discarded",
      description: "Your unsaved changes have been discarded.",
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
            />
          )}
          {activeTab === "plex" && (
            <PlexSettings
              initialConfig={initialConfig}
              selectedServer={selectedServer}
              setSelectedServer={setSelectedServer}
              setTestResults={setTestResults}
              testResults={testResults}
            />
          )}
          {activeTab === "radarr" && (
            <ServiceSettings
              service="radarr"
              url={radarrUrl}
              setUrl={setRadarrUrl}
              apiKey={radarrApiKey}
              setApiKey={setRadarrApiKey}
              setTestResults={setTestResults}
              testResults={testResults}
            />
          )}
          {activeTab === "sonarr" && (
            <ServiceSettings
              service="sonarr"
              url={sonarrUrl}
              setUrl={setSonarrUrl}
              apiKey={sonarrApiKey}
              setApiKey={setSonarrApiKey}
              setTestResults={setTestResults}
              testResults={testResults}
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
              setTestResults={setTestResults}
              testResults={testResults}
            />
          )}
        </div>
      </Card>

      {/* Actions */}
      <div className="flex flex-col sm:flex-row justify-end items-stretch sm:items-center gap-3">
        <Button
          variant="outline"
          onClick={handleCancel}
          disabled={isSaving}
          className="w-full sm:w-auto"
        >
          Cancel
        </Button>
        <Button onClick={handleSaveConfiguration} disabled={isSaving} className="w-full sm:w-auto">
          {isSaving ? (
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
