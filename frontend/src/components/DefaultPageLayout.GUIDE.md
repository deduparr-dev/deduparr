# DefaultPageLayout Component Quick Reference

## ✅ DO: Use DefaultPageLayout Components

### Example: Dashboard Page (After)
```tsx
import {
  PageContainer,
  PageHeader,
  StatsGrid,
  StatCard,
  ContentGrid,
} from "@/components/DefaultPageLayout";

export default function Dashboard() {
  return (
    <PageContainer>
      <PageHeader
        title="Dashboard"
        description="Overview of your system"
      />
      
      <StatsGrid columns={4}>
        <StatCard title="Movies" value={57} icon={Film} />
        <StatCard title="TV Shows" value={23} icon={Tv} />
      </StatsGrid>
      
      <ContentGrid columns={2}>
        <Card>Recent Activity</Card>
        <Card>Recent Deletions</Card>
      </ContentGrid>
    </PageContainer>
  );
}
```

## ❌ DON'T: Manual Layout

### Example: Old Way (Before)
```tsx
export default function Dashboard() {
  return (
    <div className="space-y-6 md:space-y-8 animate-fade-in">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold">Dashboard</h1>
        <p className="text-sm md:text-base text-muted-foreground mt-1">
          Overview of your system
        </p>
      </div>
      
      <div className="grid gap-4 md:gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {/* Manual stat cards */}
      </div>
    </div>
  );
}
```

## Common Patterns

### 1. Page with Stats and Content
```tsx
<PageContainer>
  <PageHeader title="Feature Name" description="Description" />
  <StatsGrid columns={3}>
    <StatCard />
    <StatCard />
    <StatCard />
  </StatsGrid>
  <ContentGrid columns={2}>
    <Card />
    <Card />
  </ContentGrid>
</PageContainer>
```

## Key Benefits

1. **Consistency**: Same layout across all pages
2. **Responsive**: Automatically adapts to screen size
3. **Maintainable**: Change once, update everywhere
4. **Fast**: Copy/paste patterns for new features
5. **Type-safe**: Full TypeScript support

## Component Checklist

When creating a new page:
- [ ] Wrap in `PageContainer`
- [ ] Add `PageHeader` with title
- [ ] Use `StatsGrid` for metrics
- [ ] Use `ContentGrid` for content sections

## Migration Guide

To convert an existing page:

1. Import layout components
2. Replace `<div className="space-y-...">` with `<PageContainer>`
3. Replace page header div with `<PageHeader>`
4. Replace stats grid div with `<StatsGrid>`
5. Replace content grid div with `<ContentGrid>`
6. Test on mobile, tablet, and desktop
