# Page Layout Components

Reusable layout components for consistent responsive design across Deduparr.

## Components

### `PageContainer`
Wrapper for all page content with consistent spacing.

```tsx
<PageContainer>
  {/* Your page content */}
</PageContainer>
```

### `PageHeader`
Page title with optional description and action button.

```tsx
<PageHeader 
  title="Dashboard"
  description="Overview of your duplicate detection system"
  action={<Button>Add New</Button>}
/>
```

### `StatsGrid`
Responsive grid for stat cards (2, 3, or 4 columns).

```tsx
<StatsGrid columns={4}>
  <StatCard title="Total" value={100} icon={Film} />
  <StatCard title="Pending" value={50} icon={Clock} />
</StatsGrid>
```

### `StatCard`
Individual stat card with icon.

```tsx
<StatCard 
  title="Movies"
  value={57}
  subtitle="Duplicate movie sets"
  icon={Film}
  trend="+5 this week"
/>
```

### `ContentGrid`
Grid for content cards (1 or 2 columns).

```tsx
<ContentGrid columns={2}>
  <Card>Activity Feed</Card>
  <Card>Recent Deletions</Card>
</ContentGrid>
```

## Complete Page Example

```tsx
import {
  PageContainer,
  PageHeader,
  StatsGrid,
  StatCard,
  ContentGrid,
} from "@/components/DefaultPageLayout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Film, Clock, HardDrive } from "lucide-react";

export default function ExamplePage() {
  return (
    <PageContainer>
      {/* Page Header */}
      <PageHeader
        title="My Feature"
        description="Description of this feature"
        action={<Button>New Item</Button>}
      />

      {/* Stats Section */}
      <StatsGrid columns={3}>
        <StatCard title="Total Items" value={100} icon={Film} />
        <StatCard title="Pending" value={25} icon={Clock} />
        <StatCard title="Space Used" value="1.2 GB" icon={HardDrive} />
      </StatsGrid>

      {/* Content Section */}
      <ContentGrid columns={2}>
        <Card className="p-4 md:p-6">
          {/* Activity content */}
        </Card>
        <Card className="p-4 md:p-6">
          {/* Other content */}
        </Card>
      </ContentGrid>
    </PageContainer>
  );
}
```

## Responsive Behavior

All components are responsive by default:

- **Mobile**: Full width, stacked layout, smaller text
- **Small tablet (sm)**: 2-column stat grids, the page header's action beside its title
- **Tablet (md)**: larger text, padding and gaps
- **Desktop (lg)**: 3- or 4-column stat grids, 2-column content grids

### Breakpoints
- `sm`: 640px (small tablets)
- `md`: 768px (tablets)
- `lg`: 1024px (desktops)

## Design Principles

1. **Mobile-first**: Everything works on small screens
2. **Progressive enhancement**: Better on larger screens
3. **Consistent spacing**: 4/6 gaps on mobile, 6/8 from tablets (md)
4. **Flexible actions**: The page header's action stacks on mobile, and sits beside the title from sm
5. **Smart grids**: Automatic column adjustment based on screen size

## Adding New Features

When adding new pages/features:

1. Start with `PageContainer`
2. Add `PageHeader` for the page title
3. Use `StatsGrid` + `StatCard` for metrics
4. Use `ContentGrid` for content sections

This ensures consistent layout, spacing, and responsive behavior across the entire app!
