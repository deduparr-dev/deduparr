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

### `SectionHeader`
Section title within a page.

```tsx
<SectionHeader 
  title="Recent Activity"
  description="Latest duplicate detections"
  action={<Button size="sm">View All</Button>}
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

### `ActionCard`
Card for forms, configuration, or actions.

```tsx
<ActionCard 
  title="Scan Configuration"
  description="Select libraries to scan"
  highlight={true}  // Adds gradient background
>
  {/* Form content */}
</ActionCard>
```

### `ContentGrid`
Grid for content cards (1 or 2 columns).

```tsx
<ContentGrid columns={2}>
  <Card>Activity Feed</Card>
  <Card>Recent Deletions</Card>
</ContentGrid>
```

### `ExpandableCardHeader`
Header for expandable/collapsible cards.

```tsx
<ExpandableCardHeader
  expanded={expanded}
  onToggle={() => setExpanded(!expanded)}
  title="Duplicate Set Name"
  badges={<Badge>Pending</Badge>}
  action={<Button variant="destructive">Delete</Button>}
/>
```

### `FormActions`
Container for form action buttons (responsive).

```tsx
<FormActions>
  <Button variant="outline">Cancel</Button>
  <Button>Save</Button>
</FormActions>
```

## Complete Page Example

```tsx
import {
  PageContainer,
  PageHeader,
  StatsGrid,
  StatCard,
  ActionCard,
  ContentGrid,
  SectionHeader,
  FormActions,
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

      {/* Action Card */}
      <ActionCard
        title="Configuration"
        description="Configure your settings"
        highlight={true}
      >
        <div className="space-y-4">
          {/* Form fields */}
          <FormActions>
            <Button variant="outline">Reset</Button>
            <Button>Save Changes</Button>
          </FormActions>
        </div>
      </ActionCard>

      {/* Content Section */}
      <SectionHeader title="Recent Activity" />
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
- **Small tablet (sm)**: 2-column stat grids, headers and buttons in a row
- **Tablet (md)**: expandable card headers in a row
- **Desktop (lg)**: 3- or 4-column stat grids, 2-column content grids

### Breakpoints
- `sm`: 640px (small tablets)
- `md`: 768px (tablets)
- `lg`: 1024px (desktops)

## Design Principles

1. **Mobile-first**: Everything works on small screens
2. **Progressive enhancement**: Better on larger screens
3. **Consistent spacing**: 4/6 gap on mobile, 6/8 on desktop
4. **Flexible actions**: Buttons stack on mobile, inline on desktop
5. **Smart grids**: Automatic column adjustment based on screen size

## Adding New Features

When adding new pages/features:

1. Start with `PageContainer`
2. Add `PageHeader` for the page title
3. Use `StatsGrid` + `StatCard` for metrics
4. Use `ActionCard` for forms/configuration
5. Use `ContentGrid` for content sections
6. Use `FormActions` for button groups

This ensures consistent layout, spacing, and responsive behavior across the entire app!
