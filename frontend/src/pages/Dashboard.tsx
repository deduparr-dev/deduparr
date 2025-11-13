import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { HardDrive, Clock, Film, Tv } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { statsAPI } from "@/services/api";
import {
  PageContainer,
  PageHeader,
  StatsGrid,
  StatCard,
  ContentGrid,
} from "@/components/DefaultPageLayout";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
}

function getStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "pending") return "outline";
  if (status === "approved") return "secondary";
  if (status === "processed") return "default";
  return "outline";
}

export default function Dashboard() {
  // Fetch dashboard stats with 10-minute cache
  const { data: stats, isPending: statsPending } = useQuery({
    queryKey: ["dashboardStats"],
    queryFn: () => statsAPI.getDashboardStats(),
    staleTime: 10 * 60 * 1000, // Cache for 10 minutes
  });

  // Fetch recent activity (get all for accurate counts) with 10-minute cache
  const { data: activities = [], isPending: activitiesPending } = useQuery({
    queryKey: ["recentActivity"],
    queryFn: () => statsAPI.getRecentActivity(1000), // Fetch all activities for stats
    staleTime: 10 * 60 * 1000, // Cache for 10 minutes
  });

  // Fetch recent deletions with 10-minute cache
  const { data: deletions = [], isPending: deletionsPending } = useQuery({
    queryKey: ["recentDeletions"],
    queryFn: () => statsAPI.getRecentDeletions(10),
    staleTime: 10 * 60 * 1000, // Cache for 10 minutes
  });

  if (statsPending || activitiesPending || deletionsPending) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">Loading dashboard...</div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">No data available</div>
      </div>
    );
  }

  return (
    <PageContainer>
      {/* Header */}
      <PageHeader title="Dashboard" description="Overview of your duplicate detection system" />

      {/* Stats Grid */}
      <StatsGrid columns={4}>
        <StatCard
          title="Movies"
          value={activities.filter((a) => a.media_type === "movie").length}
          subtitle="Duplicate movie sets"
          icon={Film}
        />
        <StatCard
          title="TV Shows"
          value={activities.filter((a) => a.media_type === "episode").length}
          subtitle="Duplicate episode sets"
          icon={Tv}
        />
        <StatCard
          title="Total Duplicates"
          value={stats.total_duplicates}
          subtitle={`${stats.total_duplicate_files} duplicate files`}
          icon={HardDrive}
        />
        <StatCard
          title="Space to Reclaim"
          value={formatBytes(stats.space_to_reclaim)}
          subtitle={`${stats.pending_duplicates} pending review`}
          icon={Clock}
          highlight
        />
      </StatsGrid>

      {/* Activity Tables */}
      <ContentGrid columns={2}>
        {/* Recent Activity */}
        <Card className="p-4 md:p-6">
          <h2 className="text-lg md:text-xl font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-3 md:space-y-4">
            {activities.map((activity) => (
              <div
                key={activity.id}
                className="flex flex-col sm:flex-row sm:items-start sm:justify-between p-3 md:p-4 rounded-lg border bg-card hover:bg-accent/50 transition-colors gap-2"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm md:text-base break-words">
                    {activity.title}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <Badge variant={getStatusVariant(activity.status)}>
                      {activity.status.charAt(0).toUpperCase() + activity.status.slice(1)}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{activity.media_type}</span>
                  </div>
                  <div className="text-xs md:text-sm text-muted-foreground mt-2">
                    Space: {formatBytes(activity.space_to_reclaim)}
                  </div>
                </div>
                <div className="text-xs text-muted-foreground sm:whitespace-nowrap sm:ml-4">
                  {new Date(activity.found_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Recent Deletions */}
        <Card className="p-4 md:p-6">
          <h2 className="text-lg md:text-xl font-semibold mb-4">Recent Deletions</h2>
          <div className="space-y-3 md:space-y-4">
            {deletions.map((deletion) => {
              const hasWarnings = deletion.error && deletion.is_complete;
              const statusText = deletion.is_complete
                ? hasWarnings
                  ? "Partial"
                  : "Complete"
                : "Failed";

              let badgeVariant: "default" | "destructive" | "outline" = "default";
              let badgeClassName = "";

              if (deletion.is_complete) {
                if (hasWarnings) {
                  badgeVariant = "outline";
                  badgeClassName = "border-warning-border bg-warning-light text-warning-foreground";
                } else {
                  badgeVariant = "outline";
                  badgeClassName = "border-success-border bg-success-light text-success-foreground";
                }
              } else {
                badgeVariant = "destructive";
              }

              return (
                <div
                  key={deletion.id}
                  className="flex flex-col sm:flex-row sm:items-start sm:justify-between p-3 md:p-4 rounded-lg border bg-card hover:bg-accent/50 transition-colors gap-2"
                >
                  <div className="flex-1 min-w-0">
                    <div
                      className="text-xs md:text-sm font-mono break-all"
                      title={deletion.file_path}
                    >
                      {deletion.file_path}
                    </div>
                    <div className="mt-2">
                      <Badge variant={badgeVariant} className={badgeClassName}>
                        {statusText}
                      </Badge>
                    </div>
                    {deletion.error && (
                      <div className="text-xs text-destructive mt-2">{deletion.error}</div>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground sm:whitespace-nowrap sm:ml-4">
                    {new Date(deletion.deleted_at).toLocaleString()}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </ContentGrid>
    </PageContainer>
  );
}
