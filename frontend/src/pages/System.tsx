import { useQuery } from "@tanstack/react-query";
import { systemAPI } from "@/services/api";
import {
  PageContainer,
  PageHeader,
  ContentGrid,
} from "@/components/DefaultPageLayout";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RefreshCw, Server, Database, Activity, Package, ExternalLink } from "lucide-react";
import { useState } from "react";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

function formatUptime(seconds: number | null): string {
  if (!seconds) return "Unknown";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function getLevelColor(level: string): string {
  switch (level.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return "text-red-500";
    case "WARNING":
      return "text-yellow-500";
    case "INFO":
      return "text-blue-500";
    case "DEBUG":
      return "text-gray-500";
    default:
      return "text-foreground";
  }
}

function getLevelBadgeVariant(level: string): "default" | "secondary" | "destructive" | "outline" {
  switch (level.toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
      return "destructive";
    case "WARNING":
      return "outline";
    case "INFO":
      return "default";
    case "DEBUG":
      return "secondary";
    default:
      return "default";
  }
}

export default function System() {
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [logLimit, setLogLimit] = useState(100);

  // Query with auto-refresh every 5 seconds if enabled
  const { data: versionInfo, isLoading: versionLoading } = useQuery({
    queryKey: ["systemVersion"],
    queryFn: () => systemAPI.getVersionInfo(),
    refetchInterval: autoRefresh ? 30000 : false, // 30 seconds for version
  });

  const { data: systemInfo, isLoading: systemLoading } = useQuery({
    queryKey: ["systemInfo"],
    queryFn: () => systemAPI.getSystemInfo(),
    refetchInterval: autoRefresh ? 5000 : false, // 5 seconds
  });

  const { data: appInfo, isLoading: appLoading } = useQuery({
    queryKey: ["appInfo"],
    queryFn: () => systemAPI.getAppInfo(),
    refetchInterval: autoRefresh ? 5000 : false, // 5 seconds
  });

  const { data: logsData, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ["systemLogs", logLimit],
    queryFn: () => systemAPI.getLogs(logLimit),
    refetchInterval: autoRefresh ? 2000 : false, // 2 seconds for logs
  });

  const isLoading = versionLoading || systemLoading || appLoading || logsLoading;

  if (isLoading && !versionInfo && !systemInfo) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">Loading system information...</div>
      </div>
    );
  }

  return (
    <PageContainer>
      <PageHeader 
        title="System Information" 
        description="Live system status, logs, and configuration details"
      />

      <ContentGrid columns={2}>
        {/* Application Info */}
        {appInfo && (
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Package className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">Application</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name:</span>
                <span className="font-medium">{appInfo.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Version:</span>
                <span className="font-medium">{appInfo.version}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Log Level:</span>
                <Badge variant="outline">{appInfo.config.log_level}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Scheduled Scans:</span>
                <Badge variant={appInfo.config.enable_scheduled_scans ? "default" : "secondary"}>
                  {appInfo.config.enable_scheduled_scans ? `Every ${appInfo.config.scan_interval_hours}h` : "Disabled"}
                </Badge>
              </div>
            </div>
          </Card>
        )}

        {/* Version Info */}
        {versionInfo && (
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Package className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">Component Versions</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Deduparr:</span>
                <span className="font-medium">{versionInfo.deduparr}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Python:</span>
                <span className="font-medium">{versionInfo.python}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">FastAPI:</span>
                <span className="font-medium">{versionInfo.fastapi}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">SQLAlchemy:</span>
                <span className="font-medium">{versionInfo.sqlalchemy}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Architecture:</span>
                <span className="font-medium">{versionInfo.architecture}</span>
              </div>
            </div>
          </Card>
        )}

        {/* System Info */}
        {systemInfo && (
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Server className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">System</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Hostname:</span>
                <span className="font-medium">{systemInfo.hostname}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">OS:</span>
                <span className="font-medium">{systemInfo.platform.system} {systemInfo.platform.release}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Platform:</span>
                <span className="font-medium text-xs">{versionInfo?.platform || "N/A"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Uptime:</span>
                <span className="font-medium">{formatUptime(systemInfo.uptime_seconds)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Timezone:</span>
                <span className="font-medium">{systemInfo.timezone}</span>
              </div>
            </div>
          </Card>
        )}

        {/* Process Info */}
        {systemInfo && (
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Activity className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">Process</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">PID:</span>
                <span className="font-medium">{systemInfo.process.pid}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Memory (RSS):</span>
                <span className="font-medium">{formatBytes(systemInfo.process.memory_rss)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Memory (VMS):</span>
                <span className="font-medium">{formatBytes(systemInfo.process.memory_vms)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">CPU:</span>
                <span className="font-medium">{systemInfo.process.cpu_percent.toFixed(1)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Threads:</span>
                <span className="font-medium">{systemInfo.process.threads}</span>
              </div>
            </div>
          </Card>
        )}

        {/* Database Info */}
        {appInfo && (
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Database className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">Database</h3>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">URL:</span>
                <span className="font-medium text-xs truncate max-w-[200px]" title={appInfo.database.url}>
                  {appInfo.database.url}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status:</span>
                <Badge variant={appInfo.database.status === "connected" ? "default" : "destructive"}>
                  {appInfo.database.status}
                </Badge>
              </div>
              {appInfo.database.size_bytes && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Size:</span>
                  <span className="font-medium">{formatBytes(appInfo.database.size_bytes)}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted-foreground">Data Directory:</span>
                <span className="font-medium text-xs">{appInfo.config.data_dir}</span>
              </div>
            </div>
          </Card>
        )}

        {/* Support */}
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <ExternalLink className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-lg">Support</h3>
          </div>
          <div className="space-y-3 text-sm">
            <a
              href="https://github.com/deduparr-dev/deduparr"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between hover:text-primary transition-colors"
            >
              <span className="text-muted-foreground">GitHub Repository</span>
              <ExternalLink className="w-4 h-4" />
            </a>
            <a
              href="https://github.com/deduparr-dev/deduparr/issues/new"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between hover:text-primary transition-colors"
            >
              <span className="text-muted-foreground">Report Issue</span>
              <ExternalLink className="w-4 h-4" />
            </a>
            <a
              href="https://github.com/deduparr-dev/deduparr/blob/main/README.md"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between hover:text-primary transition-colors"
            >
              <span className="text-muted-foreground">Documentation</span>
              <ExternalLink className="w-4 h-4" />
            </a>
          </div>
        </Card>
      </ContentGrid>

      {/* Logs Section */}
      {logsData && (
        <Card className="p-6 mt-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              <h3 className="font-semibold text-lg">Live Application Logs</h3>
              <Badge variant="outline">{logsData.total} entries</Badge>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAutoRefresh(!autoRefresh)}
              >
                <Activity className={`w-4 h-4 mr-2 ${autoRefresh ? "animate-pulse text-primary" : ""}`} />
                {autoRefresh ? "Auto ON" : "Auto OFF"}
              </Button>
              <select
                value={logLimit}
                onChange={(e) => setLogLimit(Number(e.target.value))}
                className="px-3 py-1.5 text-sm bg-background text-foreground border border-input rounded-md hover:bg-accent hover:text-accent-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 transition-colors"
              >
                <option value={50}>Last 50</option>
                <option value={100}>Last 100</option>
                <option value={200}>Last 200</option>
                <option value={500}>Last 500</option>
                <option value={1000}>Last 1000</option>
              </select>
              <Button variant="outline" size="sm" onClick={() => refetchLogs()}>
                <RefreshCw className="w-4 h-4" />
              </Button>
            </div>
          </div>
          
          <div className="bg-black rounded-lg p-4 font-mono text-xs overflow-auto max-h-[600px] space-y-1">
            {logsData.logs.length === 0 ? (
              <div className="text-gray-500">No logs available</div>
            ) : (
              logsData.logs.map((log, index) => (
                <div key={index} className="flex gap-2 hover:bg-gray-900 px-2 py-1 rounded">
                  <span className="text-gray-500 shrink-0">
                    {new Date(log.timestamp).toLocaleString()}
                  </span>
                  <Badge 
                    variant={getLevelBadgeVariant(log.level)} 
                    className="shrink-0 h-5 text-[10px]"
                  >
                    {log.level}
                  </Badge>
                  <span className="text-blue-400 shrink-0">[{log.logger}]</span>
                  <span className={`${getLevelColor(log.level)} break-all`}>{log.message}</span>
                </div>
              ))
            )}
          </div>
        </Card>
      )}
    </PageContainer>
  );
}
