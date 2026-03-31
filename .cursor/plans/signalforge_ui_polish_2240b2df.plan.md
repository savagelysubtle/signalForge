---
name: SignalForge UI Polish
overview:
  Address all 13 issues from the visual audit plus a full-stack SELL->SHORT
  rename to take SignalForge from "good indie product" to "world-class trading
  workspace." Changes span signal terminology, confidence bar logic, pill
  contrast, pipeline progress visualization, risk factor navigation, and several
  polish items.
todos:
  - id: sell-to-short-rename
    content:
      'Full-stack rename SELL to SHORT: Pydantic schemas, GPT prompts, database
      migration, TypeScript types, and all frontend components'
    status: completed
  - id: confidence-bar
    content:
      Fix confidence bar color to reflect signal direction (BUY=green,
      SHORT=red, HOLD=amber) instead of pure confidence threshold
    status: completed
  - id: pill-contrast
    content:
      Increase BUY/SHORT/HOLD pill opacity from 15% to 25% and add border for
      better contrast on dark background
    status: completed
  - id: footer-metadata
    content:
      'Redesign DetailView footer: add run timestamp, human-readable duration,
      mode pill, strategy name, screening summary on hover'
    status: completed
  - id: typography-hierarchy
    content:
      Bump ticker to text-3xl, dim company name, add inline action pill and
      sector tag to DetailView header
    status: completed
  - id: judge-reasoning-expand
    content:
      Add line-clamp-4 default + expand/collapse toggle with Motion animation on
      Judge Reasoning block
    status: completed
  - id: timeframe-grouping
    content:
      Remove border-b from timeframe selector, visually merge it with Chart tab
      content area
    status: completed
  - id: risk-nav
    content:
      Wire TickerCard risk badge click to navigate to Overview tab and scroll to
      risk section
    status: completed
  - id: raw-tab-redesign
    content:
      Rename to Evidence Trail, structure by pipeline stage, add collapsible
      sections and copy buttons
    status: completed
  - id: skeleton-states
    content:
      Create reusable Skeleton component and apply to TickerCardList and
      DetailView tabs during loading
    status: completed
  - id: first-run-experience
    content:
      Detect new user, show onboarding hints on SearchScreen, highlight strategy
      cards
    status: completed
  - id: pipeline-progress
    content:
      Build stage-by-stage progress visualization with backend polling endpoint
      and PipelineProgress component
    status: completed
isProject: false
---

# SignalForge UI Visual Audit - Complete Polish Plan

## Issue 0: Full-Stack SELL -> SHORT Rename (CRITICAL)

**Problem:** "SELL" in a trading context implies selling shares you already own.
For a recommendation tool that identifies shorting opportunities, "SHORT" is the
correct signal term. This affects every layer of the stack.

**Scope -- all files that reference the SELL action literal:**

### Backend (Python)

| File                             | Lines                  | What changes                                                                          |
| -------------------------------- | ---------------------- | ------------------------------------------------------------------------------------- |
| `pipeline/schemas.py`            | 275, 677               | `Literal["BUY", "SELL", "HOLD"]` -> `Literal["BUY", "SHORT", "HOLD"]`                 |
| `pipeline/prompts/gpt_debate.py` | 111, 120, 153, 163-214 | All prompt text: "BUY/SELL/HOLD" -> "BUY/SHORT/HOLD", SELL-specific guidance -> SHORT |
| `pipeline/stages/gpt.py`         | 217                    | `("BUY", "SELL")` -> `("BUY", "SHORT")`                                               |
| `services/reflection.py`         | 377, 634               | `"SELL"` checks -> `"SHORT"`, `sell_win_rate` -> `short_win_rate`                     |

### Frontend (TypeScript/React)

| File                | Lines    | What changes                                                     |
| ------------------- | -------- | ---------------------------------------------------------------- | ------ | --------------- | ------- | ------- |
| `types/index.ts`    | 124, 401 | `"BUY"                                                           | "SELL" | "HOLD"`->`"BUY" | "SHORT" | "HOLD"` |
| `SynthesisTab.tsx`  | 13       | `SELL: { text: 'SELL', ... }` -> `SHORT: { text: 'SHORT', ... }` |
| `FeedbackTab.tsx`   | 120      | `=== "SELL"` -> `=== "SHORT"`                                    |
| `PriceLevelMap.tsx` | 218      | `=== 'SELL'` -> `=== 'SHORT'`                                    |
| `InsightsView.tsx`  | 345      | `=== "SELL"` -> `=== "SHORT"`                                    |

### Database

| File                                         | What changes                                                                                                                                                                                                     |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New migration `010_rename_sell_to_short.sql` | `ALTER TABLE recommendations DROP CONSTRAINT ...; ALTER TABLE recommendations ADD CONSTRAINT ... CHECK (action IN ('BUY', 'SHORT', 'HOLD')); UPDATE recommendations SET action = 'SHORT' WHERE action = 'SELL';` |

### Prompt version bump

Since `gpt_debate.py` prompt text changes substantially, bump `PROMPT_VERSION`
in that file.

### Note on `fmp_context.py`

Lines 37 and 132 reference "NET SELLING" which is **insider trading activity**
(not signal direction). These do NOT change -- insiders selling shares is
correctly called selling.

---

## Issue 1: Confidence Bar Color/Direction Logic (CRITICAL)

**Problem:** `confidenceBarColor()` in
[SynthesisTab.tsx](src/frontend/src/components/recommendations/SynthesisTab.tsx)
maps color purely by confidence threshold (>=0.7 green, >=0.55 amber, else red).
A SHORT at 71% shows a green bar. Green = bullish in a trader's brain.

**Fix:** Replace with a two-dimensional color system that accounts for **both**
signal direction and confidence level:

- BUY signal: green bar (accent-profit), opacity/intensity scales with
  confidence
- SHORT signal: red bar (accent-loss), opacity/intensity scales with confidence
- HOLD signal: amber bar (accent-alert), opacity/intensity scales with
  confidence
- Bar width = confidence percentage (this part already works correctly)

```typescript
function confidenceBarColor(confidence: number, action: string): string {
  if (action === 'BUY') return 'bg-accent-profit';
  if (action === 'SHORT') return 'bg-accent-loss';
  return 'bg-accent-alert';
}
```

Also apply the same fix to the confidence text color next to the percentage
display.

**Files:**
[SynthesisTab.tsx](src/frontend/src/components/recommendations/SynthesisTab.tsx)
lines 17-21, 143-149

---

## Issue 2: BUY/SELL/HOLD Pill Contrast (CRITICAL)

**Problem:** `ACTION_CONFIG` uses `bg-accent-profit/15` (15% opacity tint) which
creates dark maroon/olive backgrounds that are hard to read at a glance on the
dark UI.

**Fix:** Increase background opacity and add a subtle border for better
definition:

- BUY: `bg-accent-profit/25 border border-accent-profit/40`
- SHORT: `bg-accent-loss/25 border border-accent-loss/40`
- HOLD: `bg-accent-alert/25 border border-accent-alert/40`

Also increase text boldness and ensure the pill stands out as the primary visual
anchor on the page.

**Files:**
[SynthesisTab.tsx](src/frontend/src/components/recommendations/SynthesisTab.tsx)
lines 11-15,
[FeedbackTab.tsx](src/frontend/src/components/recommendations/FeedbackTab.tsx)
lines 117-122

---

## Issue 3: Pipeline Run Progress Visualization (CRITICAL)

**Problem:** A 394-second run shows only a single `Loader2` spinner with
"Loading analysis results..." in
[ResultsScreen.tsx](src/frontend/src/components/search/ResultsScreen.tsx) lines
38-44. No stage-by-stage progress. The `usePipeline` hook (lines 12-38) does a
one-shot await with no polling.

**Fix:** Build a multi-stage progress pipeline visualization:

### Backend changes

- Add a `GET /api/pipeline/progress/{run_id}` endpoint that returns which stages
  have completed, which is running, and estimated time remaining
- The orchestrator already logs stage completions -- expose this via the
  existing `pipeline_runs` and `stage_outputs` tables

### Frontend changes

1. **New `PipelineProgress` component** -- a horizontal stepper showing 5
   stages: FMP Screening -> Perplexity -> Gemini Sentiment -> Claude Charts ->
   GPT Synthesis
2. Each stage has states: pending (dim), running (pulsing accent-signal),
   completed (accent-profit check), failed (accent-loss X), skipped (text-muted
   dash)
3. Show elapsed time and estimated remaining time
4. **Modify `usePipeline` hook** to poll `GET /api/pipeline/progress/{run_id}`
   every 3-5 seconds while `isRunning` is true
5. Replace the spinner in `SearchScreen.tsx` (lines 353-361) and
   `ResultsScreen.tsx` (lines 38-44) with the `PipelineProgress` component
6. When run completes, auto-transition to results with a brief success animation

### Types

Add to [types/index.ts](src/frontend/src/types/index.ts):

```typescript
interface PipelineProgress {
  run_id: string;
  status: 'running' | 'completed' | 'failed' | 'partial';
  stages: StageProgress[];
  elapsed_seconds: number;
  started_at: string;
}

interface StageProgress {
  stage: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  started_at: string | null;
  completed_at: string | null;
  ticker_count: number | null;
}
```

**Files:**

- New: `src/frontend/src/components/shared/PipelineProgress.tsx`
- New: `src/backend/api/pipeline.py` (new endpoint)
- Modify: [usePipeline.ts](src/frontend/src/hooks/usePipeline.ts),
  [SearchScreen.tsx](src/frontend/src/components/search/SearchScreen.tsx),
  [ResultsScreen.tsx](src/frontend/src/components/search/ResultsScreen.tsx),
  [types/index.ts](src/frontend/src/types/index.ts)

---

## Issue 4: Risk Factors Badge -> Section Navigation (MODERATE)

**Problem:** `TickerCard.tsx` (lines 46-50) shows "2 risk factors" with an
AlertTriangle icon, but clicking it just selects the ticker. No navigation to
the risk section.

**Fix:**

1. Make the risk factors badge a separate clickable element within `TickerCard`
   that triggers both ticker selection AND tab navigation to the Overview tab
2. In `DetailView.tsx`, expose a prop or callback to control the active tab
3. Pass an `onRiskClick` callback from `ResultsScreen` -> `TickerCardList` ->
   `TickerCard` that sets `activeTab='overview'` and scrolls to the risk section
4. Add an `id="risk-factors"` anchor to the Risk Factors section in
   `OverviewTab.tsx` (line 53) for scroll targeting

**Files:**
[TickerCard.tsx](src/frontend/src/components/recommendations/TickerCard.tsx),
[TickerCardList.tsx](src/frontend/src/components/recommendations/TickerCardList.tsx),
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx),
[OverviewTab.tsx](src/frontend/src/components/recommendations/OverviewTab.tsx),
[ResultsScreen.tsx](src/frontend/src/components/search/ResultsScreen.tsx)

---

## Issue 5: Status Bar / Run Metadata Footer (MODERATE)

**Problem:** The footer in
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
lines 92-102 is tiny `text-xs text-text-muted` with screening summary, mode, and
duration crammed together. No run timestamp or run identity visible.

**Fix:**

1. Redesign the footer as a more prominent, structured bar:

- Left: Run timestamp (from `fullResult.timestamp` -- the field exists in
  `PipelineResult` but isn't displayed)
- Center: Mode badge (discovery/analysis/combined/prompt) with a color-coded
  pill
- Right: Duration with appropriate formatting (e.g., "6m 35s" instead of
  "394.9s")
- Screening summary available on hover/tooltip rather than truncated inline

1. Format the duration human-readable: `formatDuration(seconds)` -> "6m 35s"
2. Strategy name should be visible when one was used

**Files:**
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
lines 92-102

---

## Issue 6: Raw Data Tab Polish (MODERATE)

**Problem:**
[RawTab.tsx](src/frontend/src/components/recommendations/RawTab.tsx) is a bare
`JSON.stringify` dump. Reads as debug UI left in production.

**Fix:**

1. Rename the tab label from "Raw Data" to "Evidence Trail" in
   [DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
2. Structure the raw data into collapsible sections by pipeline stage:
   Screening, Sentiment, Chart Analysis, Synthesis
3. Add a "Copy JSON" button for each section
4. Show timestamps per stage and prompt version hashes
5. Add basic syntax highlighting for JSON (or at minimum, color-code keys vs
   values)

**Files:** [RawTab.tsx](src/frontend/src/components/recommendations/RawTab.tsx),
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
line 32

---

## Issue 7: Timeframe Selector Visual Grouping (MODERATE)

**Problem:** The timeframe buttons bar in
[ChartTab.tsx](src/frontend/src/components/recommendations/ChartTab.tsx) (lines
380-400) sits in its own `border-b` row, visually disconnected from the Chart
tab.

**Fix:**

1. Remove the `border-b` from the timeframe bar wrapper
2. Add visual grouping: wrap the timeframe bar in a container that connects it
   to the tab bar above (same bg, continuous visual flow)
3. Add a small label indicator showing which timeframes have analysis data vs
   ad-hoc fetch (already partially done via `analysisTimeframes.has(tf)`
   styling, but could use a dot indicator)

**Files:**
[ChartTab.tsx](src/frontend/src/components/recommendations/ChartTab.tsx) lines
380-400

---

## Issue 8: Judge Reasoning Expand/Collapse (POLISH)

**Problem:** Judge reasoning text in
[SynthesisTab.tsx](src/frontend/src/components/recommendations/SynthesisTab.tsx)
lines 180-186 renders as a full `<p>` with no truncation. Long reasoning blocks
push content below the fold.

**Fix:**

1. Default to 4-5 lines with `line-clamp-4`
2. Add a "Read full reasoning" button with a ChevronDown icon
3. Animated expand/collapse using Motion
4. When expanded, show full text with a "Show less" collapse button

**Files:**
[SynthesisTab.tsx](src/frontend/src/components/recommendations/SynthesisTab.tsx)
lines 180-186

---

## Issue 9: Typography Hierarchy (POLISH)

**Problem:** In
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
lines 39-40, ticker (`text-2xl font-bold`) and company name
(`text-sm text-text-secondary`) are reasonably differentiated but could be more
pronounced. The ticker should be the dominant identity.

**Fix:**

1. Bump ticker to `text-3xl` or `text-[28px]` with `tracking-tight`
2. Keep company name at `text-sm` but add `text-text-muted` (dimmer than
   `text-text-secondary`)
3. Add the action signal (BUY/SHORT/HOLD) as a small inline pill next to the
   ticker in the header, so the direction is visible without switching to the
   Synthesis tab
4. Add sector tag below company name in `text-xs text-text-muted`

**Files:**
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)
lines 37-41

---

## Issue 10: Run Timestamp / Session Identity (POLISH)

**Problem:** No "Run at 10:22 PM on March 28" anywhere visible.
`PipelineResult.timestamp` exists in
[types/index.ts](src/frontend/src/types/index.ts) line 153 but is never
rendered.

**Fix:** This is handled as part of Issue 5 (footer redesign). The timestamp
will be displayed in the redesigned metadata bar. Additionally:

1. Show run timestamp in the `DetailView` header area (near the ticker)
2. Format as relative time for recent runs ("12 minutes ago") with full datetime
   on hover

**Files:** Covered by Issue 5 changes to
[DetailView.tsx](src/frontend/src/components/recommendations/DetailView.tsx)

---

## Issue 11: Loading/Skeleton States (POLISH)

**Problem:** No skeleton loading states anywhere. Only `Loader2` spinners.

**Fix:** Create a reusable `Skeleton` component and apply it to:

1. `TickerCardList` -- skeleton cards while loading
2. `DetailView` tabs -- skeleton content blocks while data loads
3. Use pulse animation with `bg-bg-steel animate-pulse` blocks matching the
   layout of the real content

**Files:** New: `src/frontend/src/components/shared/Skeleton.tsx`. Modify:
[ResultsScreen.tsx](src/frontend/src/components/search/ResultsScreen.tsx),
[TickerCardList.tsx](src/frontend/src/components/recommendations/TickerCardList.tsx)

---

## Issue 12: First-Run / Empty State (POLISH)

**Problem:**
[SearchScreen.tsx](src/frontend/src/components/search/SearchScreen.tsx) has a
hero with "What would you like to analyze?" but no onboarding flow for new
users.

**Fix:**

1. Detect first-time user (no previous pipeline runs via `usePipeline.history`)
2. Show a subtle onboarding hint below the hero: "Start by selecting a strategy
   below, then hit Run Analysis"
3. Add a pulsing highlight on the strategy cards for first-time users
4. Show recent runs as quick-access chips when history exists

**Files:**
[SearchScreen.tsx](src/frontend/src/components/search/SearchScreen.tsx)

---

## Issue 13: Background Hero Images on Overview Cards

**Problem:** The user mentioned hero images on some cards -- exploration
confirmed there are **no** background images in `OverviewTab.tsx`. All cards use
flat `bg-bg-concrete`. The user may be referring to the photo background
bleeding through or screenshots from a different branch.

**Fix:** Since the Urban Finance design system uses a real photo background that
shows through semi-transparent surfaces, and the Overview cards already use
`bg-bg-concrete` (which is opaque), no changes needed here unless the user
specifically requests hero images on metric cards. The current flat card design
is clean and consistent. Skip this item.

---

## Implementation Order

Organized by impact and dependency:

1. **Issue 0** (SELL -> SHORT full-stack rename) -- must come first since Issues
   1 and 2 touch the same code paths
2. **Issue 1** (confidence bar) + **Issue 2** (pill contrast) -- quick wins,
   highest trust impact, build on the renamed action values
3. **Issue 5** (footer metadata) + **Issue 10** (timestamp) -- related,
   implement together
4. **Issue 9** (typography hierarchy) -- quick styling change
5. **Issue 8** (judge reasoning expand) -- self-contained
6. **Issue 7** (timeframe grouping) -- self-contained
7. **Issue 4** (risk factors navigation) -- moderate wiring
8. **Issue 6** (Raw Data tab redesign) -- moderate scope
9. **Issue 11** (skeleton states) -- reusable component
10. **Issue 12** (first-run experience) -- product polish
11. **Issue 3** (pipeline progress) -- largest scope, requires backend +
    frontend
