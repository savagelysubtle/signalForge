---
name: ui-ux-review
description: >
  Review React + TypeScript + Tailwind v4 frontend code for UI/UX quality.
  Use when creating or modifying frontend components, views, or styles.
  Covers accessibility (WCAG 2.2 AA), design token enforcement, dark theme
  contrast, component state coverage, and Tailwind best practices.
---

# UI/UX Review

## Design Tokens

SignalForge tokens live in `src/frontend/src/theme/globals.css`. Use these exclusively — never hardcode hex values.

**Tailwind classes** (via `@theme`):

| Use | Tailwind Class | Hex |
|-----|---------------|-----|
| Page background | `bg-bg-primary` | `#0d1117` |
| Cards/panels | `bg-bg-secondary` | `#161b22` |
| Raised surface | `bg-bg-tertiary` | `#21262d` |
| Borders | `border-border` | `#30363d` |
| Primary text | `text-text-primary` | `#e6edf3` |
| Muted text | `text-text-secondary` | `#8b949e` |
| Bullish/success | `text-accent-green` | `#3fb950` |
| Bearish/error | `text-accent-red` | `#f85149` |
| Warning/neutral | `text-accent-yellow` | `#d29922` |
| Links/info | `text-accent-blue` | `#58a6ff` |

**CSS variables** (via `:root`): `var(--bg-primary)`, `var(--text-primary)`, etc.

## Review Workflow

### Step 1: Scan for Token Violations

Search target files for hardcoded values:

```bash
# Hardcoded hex colors
rg "#[0-9a-fA-F]{3,8}" --glob "*.tsx" --glob "*.css" src/frontend/src/

# Arbitrary Tailwind values
rg "\b(bg|text|border|p|m|gap|w|h)-\[" --glob "*.tsx" src/frontend/src/

# Default Tailwind palette (should use semantic tokens)
rg "\b(bg|text|border)-(red|blue|green|yellow|gray|slate|zinc|neutral)-\d" --glob "*.tsx" src/frontend/src/

# Inline styles with raw values
rg "style=\{\{" --glob "*.tsx" src/frontend/src/
```

**Fix pattern:** Replace with the matching token from the table above.

### Step 2: Check Accessibility

Search for common violations:

```bash
# Clickable divs without keyboard support
rg "onClick" --glob "*.tsx" -l src/frontend/src/
# Then verify each has: role="button", tabIndex={0}, onKeyDown

# Outline removed without replacement
rg "outline-none|outline-0" --glob "*.tsx" src/frontend/src/
# Must pair with: focus-visible:ring-2 focus-visible:ring-accent-blue

# Images without alt
rg "<img" --glob "*.tsx" src/frontend/src/
# Every <img> needs alt="description" or alt="" for decorative

# Inputs without labels
rg "<input|<select|<textarea" --glob "*.tsx" -l src/frontend/src/
# Verify each has <label> or aria-label

# Icon buttons without labels
rg "lucide-react" --glob "*.tsx" -l src/frontend/src/
# Icon-only buttons need aria-label
```

### Step 3: Verify Component States

For every component that fetches data, verify these 4 states exist:

| State | What to Look For |
|-------|-----------------|
| **Loading** | Conditional render when `isLoading` / `loading` / `!data` — show skeleton or spinner |
| **Error** | Conditional render when `error` — show message + retry button |
| **Empty** | Conditional render when `data` is empty array/null — show helpful message |
| **Data** | Normal render with populated data |

```bash
# Find data-fetching components
rg "useQuery|useFetch|useState.*\[\]|fetch\(|client\." --glob "*.tsx" -l src/frontend/src/
```

### Step 4: Check Tailwind Patterns

| Anti-Pattern | Grep | Fix |
|-------------|------|-----|
| Dynamic classes | `` `${` `` in className | Use `clsx` with complete class names |
| `@apply` | `@apply` in CSS | Move utilities to JSX className |
| Missing responsive | Components with fixed widths | Add `sm:`, `md:`, `lg:` variants |
| Bare outline-none | `outline-none` alone | Add `focus-visible:ring-2` |

### Step 5: Dark Theme Contrast

Verify contrast ratios for any custom color combinations:

| Combination | Min Ratio | Status |
|-------------|-----------|--------|
| `text-primary` on `bg-primary` | 4.5:1 | 13.2:1 ✓ |
| `text-secondary` on `bg-primary` | 4.5:1 | 5.5:1 ✓ |
| `text-primary` on `bg-secondary` | 4.5:1 | 11.7:1 ✓ |
| `text-secondary` on `bg-secondary` | 4.5:1 | 4.9:1 ✓ |
| `text-secondary` on `bg-tertiary` | 4.5:1 | 4.2:1 ⚠️ borderline |
| `accent-green` on `bg-primary` | 3:1 (UI) | 5.9:1 ✓ |
| `accent-red` on `bg-primary` | 3:1 (UI) | 5.1:1 ✓ |
| `accent-blue` on `bg-primary` | 3:1 (UI) | 5.4:1 ✓ |
| `border` on `bg-primary` | 3:1 (UI) | 3.1:1 ✓ barely |

Flag any new color combinations not in this table for manual contrast check.

## Component Conventions

### File structure

```
components/
├── auth/             Auth-specific (LoginPage, ProtectedRoute)
├── layout/           App shell (MainLayout, Sidebar, CommandBar)
├── recommendations/  Pipeline output display (DetailView, tabs, cards)
└── shared/           Reusable (AssetTypeBadge, TradingViewWidget)

views/                Full page views (route-level components)
```

### Class merging

```tsx
import clsx from "clsx";
import { twMerge } from "tailwind-merge";

// Correct pattern for conditional + mergeable classes
className={twMerge(clsx(
  "base-classes",
  condition && "conditional-classes",
  className,
))}
```

### Keyboard-accessible interactive elements

```tsx
// Correct: button element (keyboard-accessible by default)
<button onClick={handleClick} className="...">

// If must use div: add role + tabIndex + keyboard handler
<div
  role="button"
  tabIndex={0}
  onClick={handleClick}
  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleClick(); }}
>
```

### Focus indicator

```tsx
// Correct: visible focus ring using project accent
className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-blue"
```

## Quick Reference: Common Fixes

| Issue | Before | After |
|-------|--------|-------|
| Hardcoded color | `bg-[#161b22]` | `bg-bg-secondary` |
| Bare outline-none | `outline-none` | `outline-none focus-visible:ring-2 focus-visible:ring-accent-blue` |
| Missing alt | `<img src={url} />` | `<img src={url} alt="Chart for AAPL" />` |
| Icon button | `<button><Icon /></button>` | `<button aria-label="Close"><Icon /></button>` |
| Default palette | `text-gray-400` | `text-text-secondary` |
| Missing error state | `{data && <List />}` | `{error ? <Error /> : loading ? <Skeleton /> : data?.length ? <List /> : <Empty />}` |
