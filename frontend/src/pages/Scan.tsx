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
  RotateCcw,
  FlaskConical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MEDIA_SERVER_NAMES,
  scanAPI,
  configAPI,
  setupAPI,
  type AppConfig,
  type DuplicateSet as ApiDuplicateSet,
  type DuplicateFile,
  type DeleteResponse,
  type DeleteAllResponse,
  type LibrarySelection,
  type MediaLibrary,
} from "@/services/api";
import { toast } from "@/components/ui/use-toast";

const SHOWN_ERRORS = 3;
const SETS_PER_PAGE = 100;

function deletionTitle({ success, dry_run }: DeleteResponse | DeleteAllResponse): string {
  if (!success) return dry_run ? "Dry Run Found Problems" : "Deletion Incomplete";
  return dry_run ? "Dry Run Complete" : "Deletion Complete";
}

function showDeletionResult(result: DeleteResponse | DeleteAllResponse) {
  const hidden = result.errors.length - SHOWN_ERRORS;
  toast({
    title: deletionTitle(result),
    description: (
      <div className="space-y-1">
        <div>{result.message}</div>
        {result.errors.slice(0, SHOWN_ERRORS).map((error) => (
          <div key={error} className="text-xs break-all">
            {error}
          </div>
        ))}
        {hidden > 0 && <div className="text-xs">…and {hidden} more</div>}
      </div>
    ),
    variant: result.success ? undefined : "destructive",
  });
}

function namesIn(value?: string): string[] {
  return (value ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
}

/** The libraries each server is set to scan, as stored */
function storedSelection(config?: AppConfig): LibrarySelection {
  return {
    plex: namesIn(config?.plex_libraries),
    jellyfin: namesIn(config?.jellyfin_libraries),
  };
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

function DeleteConfirmPanel({
  id,
  heading,
  description,
  dryRun,
  onDryRunChange,
  onConfirm,
  onCancel,
}: {
  id: string;
  heading: string;
  description: React.ReactNode;
  dryRun: boolean;
  onDryRunChange: (value: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const checkboxId = `dry-run-${id}`;

  return (
    <div
      data-testid={`delete-confirm-${id}`}
      className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-warning-light border border-warning-border"
    >
      <div className="flex items-start gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 md:w-5 md:h-5 text-warning flex-shrink-0 mt-0.5" />
        <div>
          <h5 className="font-semibold text-sm md:text-base text-foreground">{heading}</h5>
          <p className="text-xs md:text-sm text-muted-foreground mt-1">{description}</p>
        </div>
      </div>

      <div className="flex items-start gap-2 mb-3">
        <Checkbox
          id={checkboxId}
          checked={dryRun}
          onCheckedChange={(checked) => onDryRunChange(checked === true)}
          className="mt-0.5"
        />
        <label htmlFor={checkboxId} className="text-xs md:text-sm font-medium">
          Dry Run <span className="text-muted-foreground font-normal">(Test without deleting)</span>
        </label>
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <Button
          size="sm"
          variant={dryRun ? "secondary" : "destructive"}
          onClick={onConfirm}
          className="text-xs md:text-sm w-full sm:w-auto"
        >
          {dryRun ? "Test Deletion (Dry Run)" : "Delete Permanently"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onCancel}
          className="text-xs md:text-sm w-full sm:w-auto"
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

function DuplicateSetCard({
  dupSet,
  onDelete,
  onToggleKeep,
  isDeleting,
  isTogglingFile,
}: {
  dupSet: ApiDuplicateSet;
  onDelete: (setId: number, dryRun: boolean) => void;
  onToggleKeep: (setId: number, fileId: number, keep: boolean) => void;
  isDeleting: boolean;
  isTogglingFile: number | null;
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

  function handleToggleKeep(file: DuplicateFile) {
    // Prevent toggling if this would result in all files being deleted
    if (file.keep && filesToKeep.length <= 1) {
      toast({
        variant: "destructive",
        title: "Cannot remove last keeper",
        description: "At least one file must be marked to keep.",
      });
      return;
    }
    onToggleKeep(dupSet.id, file.id, !file.keep);
  }

  return (
    <Card className="overflow-hidden" data-testid={`duplicate-set-${dupSet.id}`}>
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
                <Badge variant="outline" className="text-xs" data-testid="set-media-server">
                  {MEDIA_SERVER_NAMES[dupSet.media_server] ?? dupSet.media_server}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  Versions: {dupSet.files.length}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {dupSet.status === "processed" ? "Reclaimed" : "Can reclaim"}:{" "}
                  {formatBytes(dupSet.space_to_reclaim)}
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

        {showDeleteConfirm && !isDeleting && (
          <DeleteConfirmPanel
            id={String(dupSet.id)}
            heading="Confirm Deletion"
            description={
              <>
                This will delete <strong>{filesToDelete.length}</strong> file
                {filesToDelete.length === 1 ? "" : "s"} and keep{" "}
                <strong>{filesToKeep.length}</strong> file
                {filesToKeep.length === 1 ? "" : "s"}.
              </>
            }
            dryRun={dryRun}
            onDryRunChange={setDryRun}
            onConfirm={handleDelete}
            onCancel={() => setShowDeleteConfirm(false)}
          />
        )}
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="p-3 md:p-4 space-y-2 md:space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-xs text-muted-foreground">
              Found: {new Date(dupSet.found_at).toLocaleString()}
            </div>
            {dupSet.status === "pending" && (
              <div className="text-xs text-muted-foreground">
                Click badges to toggle keep/delete
              </div>
            )}
          </div>
          {dupSet.files.map((file) => {
            const isToggling = isTogglingFile === file.id;
            const canToggle = dupSet.status === "pending" && !isDeleting && !isToggling;
            const isLastKeeper = file.keep && filesToKeep.length <= 1;

            return (
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
                      {file.file_metadata?.resolution && (
                        <span>{file.file_metadata.resolution}</span>
                      )}
                      {file.file_metadata?.video_codec && (
                        <span>{file.file_metadata.video_codec}</span>
                      )}
                      {file.file_metadata?.audio_codec && (
                        <span>{file.file_metadata.audio_codec}</span>
                      )}
                      {file.file_metadata?.arr_quality && (
                        <span>
                          {file.file_metadata.arr_quality} (CF score:{" "}
                          {file.file_metadata.arr_custom_format_score})
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => canToggle && handleToggleKeep(file)}
                    disabled={!canToggle}
                    className={cn(
                      "self-start transition-all",
                      canToggle && !isLastKeeper && "hover:scale-105 cursor-pointer",
                      (!canToggle || isLastKeeper) && "cursor-not-allowed opacity-70"
                    )}
                    title={
                      isToggling
                        ? "Updating..."
                        : isLastKeeper
                          ? "Cannot remove last keeper"
                          : `Click to ${file.keep ? "mark for deletion" : "keep this file"}`
                    }
                  >
                    {isToggling ? (
                      <Badge variant="outline" className="text-xs">
                        <Loader2 className="w-3 h-3 animate-spin mr-1" />
                        Updating...
                      </Badge>
                    ) : (
                      <Badge
                        variant={file.keep ? "default" : "destructive"}
                        className={cn("text-xs", canToggle && !isLastKeeper && "hover:opacity-80")}
                      >
                        {file.keep ? "Keep" : "Delete"}
                        {canToggle && !isLastKeeper && <RotateCcw className="w-3 h-3 ml-1" />}
                      </Badge>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export default function Scan() {
  // The stored selection until the user changes it here
  const [pickedLibraries, setPickedLibraries] = useState<LibrarySelection | null>(null);
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => configAPI.getAll(),
  });
  const selection = pickedLibraries ?? storedSelection(config);
  const queryClient = useQueryClient();

  // Everything a scan or a deletion can change
  const refreshDuplicateQueries = () => {
    for (const key of [
      "duplicates",
      "scanStatus",
      "dashboardStats",
      "recentActivity",
      "recentDeletions",
    ]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  // Fetch deep scan setting
  const { data: deepScanData } = useQuery({
    queryKey: ["config", "deep-scan"],
    queryFn: () => configAPI.getDeepScanSetting(),
    staleTime: 5 * 60 * 1000,
  });

  const deepScanEnabled = deepScanData?.enabled ?? false;

  // Libraries from every configured media server, each tagged with its origin
  const { data: libraries = [], isPending: librariesPending } = useQuery({
    queryKey: ["mediaLibraries"],
    queryFn: () => setupAPI.getMediaLibraries(),
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

  // Fetch duplicates a page at a time, each page starting where the last ended
  const {
    data: duplicatePages,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    refetch: refetchDuplicates,
  } = useInfiniteQuery({
    queryKey: ["duplicates"],
    queryFn: ({ pageParam }) => scanAPI.getDuplicates(pageParam, SETS_PER_PAGE),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _pages, offset) => {
      const next = offset + lastPage.sets.length;
      return next < lastPage.total ? next : undefined;
    },
    staleTime: 30 * 1000, // Cache for 30 seconds
  });
  const pages = duplicatePages?.pages ?? [];
  // A set found or removed after the first page loaded shifts the others
  // between pages: loadMore then loads every page again, and until it has, a
  // set shifted onto the next page is listed once
  const duplicates = [
    ...new Map(pages.flatMap((page) => page.sets).map((set) => [set.id, set])).values(),
  ];
  const totalSets = pages[pages.length - 1]?.total ?? 0;

  async function loadMore() {
    const { data } = await fetchNextPage();
    const loaded = data?.pages ?? [];
    if (loaded[0]?.total !== loaded[loaded.length - 1]?.total) await refetchDuplicates();
  }

  // Start scan mutation
  const startScanMutation = useMutation({
    mutationFn: (libraries: LibrarySelection) => scanAPI.startScan({ libraries }),
    onSuccess: (data) => {
      toast({
        title: "Scan Complete",
        description: (
          <div>
            <div>{data.message}</div>
            {data.duplicates_found > 0 && data.total_sets === 0 && (
              <div className="mt-2">No sets created because files are missing on disk.</div>
            )}
          </div>
        ),
      });
      refreshDuplicateQueries();
      // The selection scanned is now the stored one
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
    onError: (error: Error) => {
      toast({
        title: "Scan Failed",
        description: <div>{error.message}</div>,
        variant: "destructive",
      });
    },
  });

  const [showDeleteAllConfirm, setShowDeleteAllConfirm] = useState(false);
  const [deleteAllDryRun, setDeleteAllDryRun] = useState(true);

  // Delete duplicate set mutation
  const deleteMutation = useMutation({
    mutationFn: ({ setId, dryRun }: { setId: number; dryRun: boolean }) =>
      scanAPI.deleteDuplicateSet(setId, dryRun),
    onSuccess: (data) => {
      showDeletionResult(data);
      if (!data.dry_run) refreshDuplicateQueries();
    },
    onError: (error: Error) => {
      toast({
        title: "Deletion Failed",
        description: <div>{error.message}</div>,
        variant: "destructive",
      });
    },
  });

  // Delete every pending set in one pass
  const deleteAllMutation = useMutation({
    mutationFn: (dryRun: boolean) => scanAPI.deleteAllDuplicateSets(dryRun),
    onSuccess: (data) => {
      showDeletionResult(data);
      setShowDeleteAllConfirm(false);
      if (!data.dry_run) refreshDuplicateQueries();
    },
    onError: (error: Error) => {
      toast({
        title: "Deletion Failed",
        description: <div>{error.message}</div>,
        variant: "destructive",
      });
    },
  });

  // Toggle file keep flag mutation
  const [togglingFileId, setTogglingFileId] = useState<number | null>(null);
  const toggleKeepMutation = useMutation({
    mutationFn: ({ setId, fileId, keep }: { setId: number; fileId: number; keep: boolean }) => {
      setTogglingFileId(fileId);
      return scanAPI.updateFileKeep(setId, fileId, keep);
    },
    onSuccess: (data) => {
      toast({
        title: "File Updated",
        description: data.message,
      });
      // Invalidate duplicates to refresh the UI
      queryClient.invalidateQueries({ queryKey: ["duplicates"] });
      queryClient.invalidateQueries({ queryKey: ["scanStatus"] });
    },
    onError: (error: Error) => {
      toast({
        title: "Update Failed",
        description: error.message,
        variant: "destructive",
      });
    },
    onSettled: () => {
      setTogglingFileId(null);
    },
  });

  function isSelected(library: MediaLibrary) {
    return selection[library.server]?.includes(library.title) ?? false;
  }

  // Every listed server is sent, so one with nothing ticked stores that; a
  // server that could not be listed keeps its selection.
  const scanSelection: LibrarySelection = Object.fromEntries(
    [...new Set(libraries.map((library) => library.server))].map((server) => [
      server,
      libraries
        .filter((library) => library.server === server && isSelected(library))
        .map((library) => library.title),
    ])
  );
  const nothingSelected = Object.values(scanSelection).every((titles) => titles.length === 0);

  function handleStartScan() {
    if (nothingSelected) return;
    startScanMutation.mutate(scanSelection);
  }

  function handleDelete(setId: number, dryRun: boolean) {
    deleteMutation.mutate({ setId, dryRun });
  }

  function handleToggleKeep(setId: number, fileId: number, keep: boolean) {
    toggleKeepMutation.mutate({ setId, fileId, keep });
  }

  function toggleLibrary(library: MediaLibrary) {
    const titles = selection[library.server] ?? [];
    setPickedLibraries({
      ...selection,
      [library.server]: isSelected(library)
        ? titles.filter((title) => title !== library.title)
        : [...titles, library.title],
    });
  }

  const isScanning = startScanMutation.isPending;

  // Delete All covers every pending set, not only the pages loaded
  const setsToDelete = scanStatus?.sets_to_delete ?? 0;
  const pendingFilesToDelete = scanStatus?.pending_files_to_delete ?? 0;
  const pendingSpace = scanStatus?.total_space_reclaimable ?? 0;

  // Dev-only: Direct disk scan mutation
  const devScanMutation = useMutation({
    mutationFn: () => scanAPI.devDiskScan(),
    onSuccess: (data) => {
      toast({
        title: "Dev Scan Complete",
        description: `Created ${data.sets_created} duplicate sets (${data.duplicates_found} files)`,
      });
      refreshDuplicateQueries();
    },
    onError: (error: Error) => {
      toast({
        title: "Dev Scan Failed",
        description: error.message.includes("403")
          ? "Dev endpoint only available when LOG_LEVEL=DEBUG"
          : error.message,
        variant: "destructive",
      });
    },
  });

  const isDev = import.meta.env.DEV;

  return (
    <div className="space-y-6 md:space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-2xl md:text-3xl font-bold text-foreground">Scan for Duplicates</h1>
        <p className="text-sm md:text-base text-muted-foreground mt-1">
          Find duplicate media files in your libraries
        </p>
      </div>

      {/* Status Summary */}
      <Card className="p-4 md:p-6 bg-gradient-to-br from-primary/5 to-secondary/5 border-primary/20">
        <h3 className="font-semibold text-base md:text-lg mb-4">Current Status</h3>
        <div className="grid gap-4 md:gap-6 grid-cols-1 sm:grid-cols-3">
          <div>
            <div className="text-xs md:text-sm text-muted-foreground mb-1">Duplicate Items</div>
            <div
              className="text-2xl md:text-3xl font-bold text-foreground"
              data-testid="duplicate-items"
            >
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
                  No libraries found. Check your media server in{" "}
                  <Link to="/settings" className="text-primary hover:underline">
                    Settings
                  </Link>
                  .
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {libraries.map((library) => (
                  <div key={`${library.server}:${library.key}`} className="flex items-center gap-2">
                    <Checkbox
                      id={`scan-${library.server}-${library.key}`}
                      checked={isSelected(library)}
                      onCheckedChange={() => toggleLibrary(library)}
                    />
                    <label
                      htmlFor={`scan-${library.server}-${library.key}`}
                      className="text-sm cursor-pointer"
                    >
                      {library.title}{" "}
                      <span className="text-muted-foreground">
                        ({library.type}) on {MEDIA_SERVER_NAMES[library.server] ?? library.server}
                      </span>
                    </label>
                  </div>
                ))}
                <p className="text-xs text-muted-foreground pt-1">
                  Scheduled scans use the same selection.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="lg"
            disabled={nothingSelected || isScanning}
            onClick={handleStartScan}
            className="w-full sm:w-auto"
          >
            <Search className="w-4 h-4 mr-2" />
            {isScanning ? "Scanning..." : "Start Scan"}
          </Button>

          {isDev && (
            <Button
              size="lg"
              variant="outline"
              disabled={devScanMutation.isPending}
              onClick={() => devScanMutation.mutate()}
              className="w-full sm:w-auto border-dashed"
            >
              <FlaskConical className="w-4 h-4 mr-2" />
              {devScanMutation.isPending ? "Scanning..." : "Dev: Disk Scan"}
            </Button>
          )}
        </div>
      </Card>

      {/* Results */}
      <div className="space-y-3 md:space-y-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
          <h3 className="text-base md:text-lg font-semibold">Duplicate Sets Found</h3>
          {setsToDelete > 0 && (
            <Button
              size="sm"
              variant="destructive"
              data-testid="delete-all"
              disabled={deleteAllMutation.isPending}
              onClick={() => setShowDeleteAllConfirm(!showDeleteAllConfirm)}
              className="w-full md:w-auto text-xs md:text-sm"
            >
              {deleteAllMutation.isPending ? (
                <Loader2 className="w-3 h-3 md:w-4 md:h-4 mr-2 animate-spin" />
              ) : (
                <Trash2 className="w-3 h-3 md:w-4 md:h-4 mr-2" />
              )}
              Delete All ({setsToDelete})
            </Button>
          )}
        </div>

        {showDeleteAllConfirm && !deleteAllMutation.isPending && (
          <DeleteConfirmPanel
            id="all"
            heading="Delete every pending duplicate set"
            description={
              <>
                This will delete <strong>{pendingFilesToDelete}</strong> file
                {pendingFilesToDelete === 1 ? "" : "s"} across <strong>{setsToDelete}</strong> set
                {setsToDelete === 1 ? "" : "s"}, keeping the highest ranked file in each, and
                reclaim about <strong>{formatBytes(pendingSpace)}</strong>.
              </>
            }
            dryRun={deleteAllDryRun}
            onDryRunChange={setDeleteAllDryRun}
            onConfirm={() => deleteAllMutation.mutate(deleteAllDryRun)}
            onCancel={() => setShowDeleteAllConfirm(false)}
          />
        )}
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
              onToggleKeep={handleToggleKeep}
              isDeleting={deleteMutation.isPending}
              isTogglingFile={togglingFileId}
            />
          ))
        )}

        {hasNextPage && (
          <div className="flex flex-col items-center gap-2">
            <p className="text-xs md:text-sm text-muted-foreground" data-testid="sets-shown">
              Showing {duplicates.length} of {totalSets} duplicate sets
            </p>
            <Button
              variant="outline"
              data-testid="load-more"
              disabled={isFetchingNextPage}
              onClick={loadMore}
              className="w-full sm:w-auto"
            >
              {isFetchingNextPage && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Load More
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
