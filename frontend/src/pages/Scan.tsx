import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  ChevronDown,
  ChevronUp,
  Trash2,
  AlertTriangle,
  Search,
  Loader2,
  HardDrive,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { scanAPI, configAPI, type DuplicateSet as ApiDuplicateSet } from "@/services/api";
import { toast } from "@/components/ui/use-toast";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

function DuplicateSetCard({
  dupSet,
  onDelete,
  isDeleting,
}: {
  dupSet: ApiDuplicateSet;
  onDelete: (setId: number, dryRun: boolean) => void;
  isDeleting: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [dryRun, setDryRun] = useState(true);

  const filesToDelete = dupSet.files.filter((f) => !f.keep);
  const filesToKeep = dupSet.files.filter((f) => f.keep);

  function handleDelete() {
    onDelete(dupSet.id, dryRun);
    setShowDeleteConfirm(false);
  }

  return (
    <Card className="overflow-hidden">
      {/* Header */}
      <div className="p-3 md:p-4 bg-muted/50">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex-1 flex items-start gap-2 md:gap-3 text-left hover:opacity-80 transition-opacity"
            disabled={isDeleting}
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4 md:w-5 md:h-5 text-muted-foreground mt-0.5 flex-shrink-0" />
            ) : (
              <ChevronDown className="w-4 h-4 md:w-5 md:h-5 text-muted-foreground mt-0.5 flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <h4 className="font-semibold text-sm md:text-base text-foreground break-words">
                {dupSet.title}
              </h4>
              <div className="flex flex-wrap items-center gap-1.5 md:gap-2 mt-2">
                <Badge
                  variant={dupSet.status === "pending" ? "outline" : "default"}
                  className="text-xs"
                >
                  {dupSet.status.charAt(0).toUpperCase() + dupSet.status.slice(1)}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {dupSet.media_type}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  Versions: {dupSet.files.length}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  Can reclaim: {formatBytes(dupSet.space_to_reclaim)}
                </Badge>
              </div>
            </div>
          </button>

          {dupSet.status === "pending" && !isDeleting && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setShowDeleteConfirm(!showDeleteConfirm)}
              className="w-full md:w-auto md:flex-shrink-0 text-xs md:text-sm"
            >
              <Trash2 className="w-3 h-3 md:w-4 md:h-4 mr-2" />
              Delete Duplicates
            </Button>
          )}

          {isDeleting && (
            <div className="p-3 md:p-4 rounded-lg bg-muted border border-border">
              <div className="flex items-center gap-3">
                <Loader2 className="w-5 h-5 animate-spin text-primary" />
                <div>
                  <p className="text-sm font-medium">Processing deletion...</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    This may take up to 30 seconds
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Delete Confirmation */}
        {showDeleteConfirm && !isDeleting && (
          <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-warning-light border border-warning-border">
            <div className="flex items-start gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 md:w-5 md:h-5 text-warning flex-shrink-0 mt-0.5" />
              <div>
                <h5 className="font-semibold text-sm md:text-base text-foreground">
                  Confirm Deletion
                </h5>
                <p className="text-xs md:text-sm text-muted-foreground mt-1">
                  This will delete <strong>{filesToDelete.length}</strong> file
                  {filesToDelete.length === 1 ? "" : "s"} and keep{" "}
                  <strong>{filesToKeep.length}</strong> file
                  {filesToKeep.length === 1 ? "" : "s"}.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-2 mb-3">
              <Checkbox
                id="dry-run"
                checked={dryRun}
                onCheckedChange={(checked) => setDryRun(checked === true)}
                className="mt-0.5"
              />
              <label htmlFor="dry-run" className="text-xs md:text-sm font-medium">
                Dry Run{" "}
                <span className="text-muted-foreground font-normal">(Test without deleting)</span>
              </label>
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <Button
                size="sm"
                variant={dryRun ? "secondary" : "destructive"}
                onClick={handleDelete}
                className="text-xs md:text-sm w-full sm:w-auto"
              >
                {dryRun ? "Test Deletion (Dry Run)" : "Delete Permanently"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowDeleteConfirm(false)}
                className="text-xs md:text-sm w-full sm:w-auto"
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="p-3 md:p-4 space-y-2 md:space-y-3">
          <div className="text-xs text-muted-foreground">
            Found: {new Date(dupSet.found_at).toLocaleString()}
          </div>
          {dupSet.files.map((file) => (
            <div
              key={file.id}
              className={cn(
                "p-3 md:p-4 rounded-lg border transition-colors",
                file.keep ? "border-primary bg-primary/10" : "border-border bg-card"
              )}
            >
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 md:gap-4">
                <div className="flex-1 min-w-0">
                  <div className="text-xs md:text-sm font-mono break-all">{file.file_path}</div>
                  <div className="flex flex-wrap items-center gap-2 md:gap-3 mt-2 text-xs text-muted-foreground">
                    <span>Size: {formatBytes(file.file_size)}</span>
                    <span>Score: {file.score}</span>
                    {file.file_metadata?.resolution && <span>{file.file_metadata.resolution}</span>}
                    {file.file_metadata?.video_codec && (
                      <span>{file.file_metadata.video_codec}</span>
                    )}
                    {file.file_metadata?.audio_codec && (
                      <span>{file.file_metadata.audio_codec}</span>
                    )}
                  </div>
                </div>
                <Badge
                  variant={file.keep ? "default" : "destructive"}
                  className="text-xs self-start"
                >
                  {file.keep ? "Keep" : "Delete"}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function Scan() {
  const [selectedLibraries, setSelectedLibraries] = useState<string[]>([]);
  const queryClient = useQueryClient();

  // Check if Plex is configured
  const { data: config } = useQuery({
    queryKey: ["plexConfig"],
    queryFn: () => configAPI.getAll(),
    staleTime: 10 * 60 * 1000,
  });

  const plexConfigured = !!config?.plex_auth_token;

  // Fetch deep scan setting
  const { data: deepScanData } = useQuery({
    queryKey: ["config", "deep-scan"],
    queryFn: () => configAPI.getDeepScanSetting(),
    staleTime: 5 * 60 * 1000,
  });

  const deepScanEnabled = deepScanData?.enabled ?? false;

  // Fetch Plex libraries only if Plex authentication token exists in database
  const { data: libraries = [], isPending: librariesPending } = useQuery({
    queryKey: ["plexLibraries"],
    queryFn: () => configAPI.getPlexLibraries(),
    enabled: plexConfigured, // Only run query if plex_auth_token exists in config
    staleTime: 10 * 60 * 1000, // Cache for 10 minutes
    retry: false, // Don't retry failed requests to avoid delays
  });

  // Fetch scan status with caching
  const { data: scanStatus } = useQuery({
    queryKey: ["scanStatus"],
    queryFn: () => scanAPI.getScanStatus(),
    staleTime: 30 * 1000, // Cache for 30 seconds (updates more frequently)
    refetchInterval: 30 * 1000, // Auto-refresh every 30 seconds
  });

  // Fetch duplicates with caching
  const { data: duplicates = [] } = useQuery({
    queryKey: ["duplicates"],
    queryFn: () => scanAPI.getDuplicates(),
    staleTime: 30 * 1000, // Cache for 30 seconds
  });

  // Start scan mutation
  const startScanMutation = useMutation({
    mutationFn: (libraryNames: string[]) => scanAPI.startScan({ library_names: libraryNames }),
    onSuccess: async (data) => {
      const totalSets = data.total_sets || data.sets_created;
      const newSets = data.sets_created || 0;
      const existingSets = data.sets_already_exist || 0;

      // Build description with helpful context
      const mainMessage = `Found ${data.duplicates_found} duplicate files. ${newSets} new sets, ${existingSets} existing sets (${totalSets} total).`;

      // Add helpful explanation if files found but no sets created
      const showWarning = data.duplicates_found > 0 && totalSets === 0;

      toast({
        title: "Scan Complete",
        description: showWarning ? (
          <div>
            <div>{mainMessage}</div>
            <div className="mt-2">No sets created because files are missing on disk.</div>
          </div>
        ) : (
          <div>{mainMessage}</div>
        ),
      });

      // Invalidate all caches to update dashboard immediately
      await queryClient.invalidateQueries({ queryKey: ["duplicates"] });
      await queryClient.invalidateQueries({ queryKey: ["scanStatus"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboardStats"] });
      await queryClient.invalidateQueries({ queryKey: ["recentActivity"] });
    },
    onError: (error: Error) => {
      toast({
        title: "Scan Failed",
        description: <div>{error.message}</div>,
        variant: "destructive",
      });
    },
  });

  // Delete duplicate set mutation
  const deleteMutation = useMutation({
    mutationFn: ({ setId, dryRun }: { setId: number; dryRun: boolean }) =>
      scanAPI.deleteDuplicateSet(setId, dryRun),
    onSuccess: (data) => {
      toast({
        title: data.dry_run ? "Dry Run Complete" : "Deletion Complete",
        description: <div>{data.message}</div>,
      });
      if (!data.dry_run) {
        // Invalidate all relevant caches to show updated stats immediately
        queryClient.invalidateQueries({ queryKey: ["duplicates"] });
        queryClient.invalidateQueries({ queryKey: ["scanStatus"] });
        queryClient.invalidateQueries({ queryKey: ["dashboardStats"] });
        queryClient.invalidateQueries({ queryKey: ["recentActivity"] });
        queryClient.invalidateQueries({ queryKey: ["recentDeletions"] });
      }
    },
    onError: (error: Error) => {
      toast({
        title: "Deletion Failed",
        description: <div>{error.message}</div>,
        variant: "destructive",
      });
    },
  });

  function handleStartScan() {
    if (selectedLibraries.length === 0) return;
    startScanMutation.mutate(selectedLibraries);
  }

  function handleDelete(setId: number, dryRun: boolean) {
    deleteMutation.mutate({ setId, dryRun });
  }

  function toggleLibrary(library: string) {
    setSelectedLibraries((prev) =>
      prev.includes(library) ? prev.filter((l) => l !== library) : [...prev, library]
    );
  }

  const isScanning = startScanMutation.isPending;

  return (
    <div className="space-y-6 md:space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-2xl md:text-3xl font-bold text-foreground">Scan for Duplicates</h1>
        <p className="text-sm md:text-base text-muted-foreground mt-1">
          Find duplicate media files in your Plex libraries
        </p>
      </div>

      {/* Status Summary */}
      <Card className="p-4 md:p-6 bg-gradient-to-br from-primary/5 to-secondary/5 border-primary/20">
        <h3 className="font-semibold text-base md:text-lg mb-4">Current Status</h3>
        <div className="grid gap-4 md:gap-6 grid-cols-1 sm:grid-cols-3">
          <div>
            <div className="text-xs md:text-sm text-muted-foreground mb-1">Duplicate Items</div>
            <div className="text-2xl md:text-3xl font-bold text-foreground">
              {scanStatus?.total_duplicate_sets ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs md:text-sm text-muted-foreground mb-1">Pending Review</div>
            <div className="text-2xl md:text-3xl font-bold text-foreground">
              {scanStatus?.pending_sets ?? 0}
            </div>
          </div>
          <div>
            <div className="text-xs md:text-sm text-muted-foreground mb-1">Space Reclaimable</div>
            <div className="text-2xl md:text-3xl font-bold text-primary">
              {formatBytes(scanStatus?.total_space_reclaimable ?? 0)}
            </div>
          </div>
        </div>
      </Card>

      {/* Scan Configuration */}
      <Card className="p-4 md:p-6">
        <div className="flex items-center gap-2 mb-4">
          <h3 className="text-base md:text-lg font-semibold">Scan Configuration</h3>
          <Badge variant={deepScanEnabled ? "default" : "outline"}>
            <HardDrive className="h-3 w-3 mr-1.5" />
            Deep Scan: {deepScanEnabled ? "Enabled" : "Disabled"}
          </Badge>
        </div>

        <div className="space-y-4 mb-6">
          <div>
            <label className="block text-sm font-medium mb-3">Libraries to Scan</label>
            {librariesPending ? (
              <div className="flex items-center gap-3 py-4">
                <Loader2 className="w-5 h-5 animate-spin text-primary" />
                <span className="text-sm text-muted-foreground">Loading libraries...</span>
              </div>
            ) : libraries.length === 0 ? (
              <div className="p-4 rounded-lg bg-muted border border-border">
                <p className="text-sm text-muted-foreground">
                  No libraries found. Please{" "}
                  <Link to="/setup" className="text-primary hover:underline">
                    run the Setup Wizard
                  </Link>{" "}
                  to configure Plex.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {libraries.map((library) => (
                  <div key={library.key} className="flex items-center gap-2">
                    <Checkbox
                      id={library.key}
                      checked={selectedLibraries.includes(library.title)}
                      onCheckedChange={() => toggleLibrary(library.title)}
                    />
                    <label htmlFor={library.key} className="text-sm cursor-pointer">
                      {library.title}{" "}
                      <span className="text-muted-foreground">({library.type})</span>
                    </label>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <Button
          size="lg"
          disabled={selectedLibraries.length === 0 || isScanning}
          onClick={handleStartScan}
          className="w-full sm:w-auto"
        >
          <Search className="w-4 h-4 mr-2" />
          {isScanning ? "Scanning..." : "Start Scan"}
        </Button>
      </Card>

      {/* Results */}
      <div className="space-y-3 md:space-y-4">
        <h3 className="text-base md:text-lg font-semibold">Duplicate Sets Found</h3>
        {duplicates.length === 0 ? (
          <Card className="p-6 md:p-8 text-center text-sm md:text-base text-muted-foreground">
            No duplicates found. Start a scan to find duplicate media files.
          </Card>
        ) : (
          duplicates.map((dupSet) => (
            <DuplicateSetCard
              key={dupSet.id}
              dupSet={dupSet}
              onDelete={handleDelete}
              isDeleting={deleteMutation.isPending}
            />
          ))
        )}
      </div>
    </div>
  );
}
