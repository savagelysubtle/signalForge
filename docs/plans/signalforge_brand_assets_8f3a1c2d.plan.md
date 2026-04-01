---
name: SignalForge brand asset refresh
overview:
  Replace the app's placeholder branding assets with a cohesive SignalForge logo,
  icon, favicon, and hero set derived from the approved premium dark-mode concept.
  Remove old hero/logo asset files first so the frontend only contains the new
  brand system and there is no overlap between placeholder and production assets.
todos:
  - id: remove-old-assets
    content: Delete old frontend hero and placeholder logo assets that should not remain in the app.
    status: completed
  - id: create-brand-assets
    content: Create the new SignalForge favicon, icon, logo, and hero assets.
    status: completed
  - id: wire-branding
    content: Update frontend usage points to reference the new branding assets and verify quality.
    status: completed
isProject: false
---

# SignalForge brand asset refresh

## Problem

The frontend still contains placeholder and legacy branding assets such as the old
favicon and starter SVGs. The app also uses temporary text and monogram branding in
UI entry points like the login page and sidebar. This creates overlap with the new
SignalForge visual direction and makes the product feel inconsistent.

## Solution

Remove obsolete hero/logo asset files from the frontend first, then add a single
cohesive asset set based on the approved SignalForge concept. Use SVG for logo/icon
assets so they scale cleanly from favicon to in-app logo usage, and replace the
existing hero with a new branded hero image.

## Implementation Steps

### Step 1: remove-old-assets

Delete the current placeholder asset files that would conflict with the new brand set:

- [src/frontend/src/assets/hero.png](src/frontend/src/assets/hero.png)
- [src/frontend/src/assets/vite.svg](src/frontend/src/assets/vite.svg)
- [src/frontend/src/assets/react.svg](src/frontend/src/assets/react.svg)
- [src/frontend/public/favicon.svg](src/frontend/public/favicon.svg)

Keep unrelated icon assets unless they are proven to be obsolete.

### Step 2: create-brand-assets

Create a new brand asset family under frontend asset/public paths:

- [src/frontend/src/assets/branding/](src/frontend/src/assets/branding/)
- [src/frontend/public/](src/frontend/public/)

Planned outputs:

- `signalforge-logo-horizontal.svg`
- `signalforge-logo-icon.svg`
- `signalforge-logo-stacked.svg`
- `signalforge-hero.png`
- `favicon.svg`

All new assets should reuse the approved forged-signal visual language and remain
legible at both hero and favicon sizes.

### Step 3: wire-branding

Update the key frontend usage points to consume the new assets:

- [src/frontend/index.html](src/frontend/index.html)
- [src/frontend/src/components/auth/LoginPage.tsx](src/frontend/src/components/auth/LoginPage.tsx)
- [src/frontend/src/components/layout/Sidebar.tsx](src/frontend/src/components/layout/Sidebar.tsx)

Also update the document title and verify there are no stale references to removed
assets.

## Risks / Open Questions

- The favicon and sidebar icon require a simplified emblem, so some hero-level detail
  from the concept image must be reduced for clarity.
- If the user later wants additional platform assets such as social cards or app
  manifests, those should be added in a follow-up pass.

## Branch

Current working branch.
