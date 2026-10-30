import { Card } from "@/components/ui/card";
import { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold text-foreground">{title}</h1>
        {description && (
          <p className="text-sm md:text-base text-muted-foreground mt-1">{description}</p>
        )}
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  );
}

interface PageContainerProps {
  children: ReactNode;
}

export function PageContainer({ children }: PageContainerProps) {
  return <div className="space-y-6 md:space-y-8 animate-fade-in">{children}</div>;
}

interface StatsGridProps {
  children: ReactNode;
  columns?: 2 | 3 | 4;
}

export function StatsGrid({ children, columns = 4 }: StatsGridProps) {
  const gridCols = {
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-2 lg:grid-cols-3",
    4: "sm:grid-cols-2 lg:grid-cols-4",
  };

  return <div className={`grid gap-4 md:gap-6 ${gridCols[columns]}`}>{children}</div>;
}

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  trend?: string;
  highlight?: boolean;
}

export function StatCard({ title, value, subtitle, icon: Icon, trend, highlight }: StatCardProps) {
  return (
    <Card className="p-4 md:p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-xs md:text-sm font-medium text-muted-foreground">{title}</p>
          <h3
            className={`text-2xl md:text-3xl font-bold mt-1 md:mt-2 ${highlight ? "text-primary" : "text-foreground"}`}
          >
            {value}
          </h3>
          {subtitle && <p className="text-xs md:text-sm text-muted-foreground mt-1">{subtitle}</p>}
          {trend && <p className="text-xs text-primary mt-2">{trend}</p>}
        </div>
        <div className="w-10 h-10 md:w-12 md:h-12 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 md:w-6 md:h-6 text-primary" />
        </div>
      </div>
    </Card>
  );
}

interface ContentGridProps {
  children: ReactNode;
  columns?: 1 | 2;
}

export function ContentGrid({ children, columns = 2 }: ContentGridProps) {
  const gridCols = columns === 2 ? "lg:grid-cols-2" : "";
  return <div className={`grid gap-4 md:gap-6 ${gridCols}`}>{children}</div>;
}
