---
name: Obsidian Kinetic FinTech
colors:
  surface: '#111318'
  surface-dim: '#111318'
  surface-bright: '#37393f'
  surface-container-lowest: '#0c0e13'
  surface-container-low: '#1a1b21'
  surface-container: '#1e1f25'
  surface-container-high: '#282a2f'
  surface-container-highest: '#33353a'
  on-surface: '#e2e2e9'
  on-surface-variant: '#bacac1'
  inverse-surface: '#e2e2e9'
  inverse-on-surface: '#2e3036'
  outline: '#85948c'
  outline-variant: '#3c4a43'
  surface-tint: '#2fe0aa'
  primary: '#44edb7'
  on-primary: '#003828'
  primary-container: '#00d09c'
  on-primary-container: '#00533c'
  inverse-primary: '#006c4f'
  secondary: '#bcc2ff'
  on-secondary: '#00179b'
  secondary-container: '#152ecf'
  on-secondary-container: '#aab3ff'
  tertiary: '#cdd2e6'
  on-tertiary: '#2a303f'
  tertiary-container: '#b1b7ca'
  on-tertiary-container: '#424858'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#59fdc5'
  primary-fixed-dim: '#2fe0aa'
  on-primary-fixed: '#002116'
  on-primary-fixed-variant: '#00513b'
  secondary-fixed: '#dfe0ff'
  secondary-fixed-dim: '#bcc2ff'
  on-secondary-fixed: '#000b62'
  on-secondary-fixed-variant: '#102bcd'
  tertiary-fixed: '#dde2f6'
  tertiary-fixed-dim: '#c1c6d9'
  on-tertiary-fixed: '#151b29'
  on-tertiary-fixed-variant: '#414756'
  background: '#111318'
  on-background: '#e2e2e9'
  surface-variant: '#33353a'
  canvas-base: '#0B0D12'
  surface-card: '#121620'
  surface-elevated: '#1A202E'
  border-crisp: '#232B3B'
  primary-glow: '#00E6AD'
  text-muted: '#94A3B8'
  status-warning: '#FFB800'
  status-refusal: '#FF5656'
typography:
  display:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
  code-inline:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-lg: 1.5rem
  margin: 1rem
  margin-md: 2rem
  margin-lg: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system crafts a modern, high-precision conversational interface for the Mutual Fund AI Assistant. Tailored for retail investors, wealth managers, and financial analysts, the interface establishes an atmosphere of algorithmic certainty, technological sophistication, and unwavering regulatory trust. 

The aesthetic is anchored in a deep **Obsidian Minimalist** framework: deep-space dark surfaces layered with crisp, hairline borders and vibrant kinetic green and royal blue illuminations. It eliminates visual clutter to surface dense financial disclosures, NAV trajectories, and AI-driven advisory answers with immaculate legibility. The mood is analytical yet approachable—delivering the instantaneous feel of a Bloomberg terminal softened by consumer-grade conversational flow.

## Colors

The palette operates under an uncompromising dark system where contrast dictates data priority. 

- **Primary (`#00D09C`) & Kinetic Glow (`#00E6AD`):** The signature emerald-teal acts as the primary visual beacon for affirmative conversational states, user action triggers, returns/NAV appreciation, and verified compliance markers.
- **Secondary (`#5367FF`):** A technical royal blue reserved for assistant query highlights, deep-link references, interactive chip selectors, and algorithmic processing states.
- **Canvas & Surface Tiering (`#0B0D12`, `#121620`, `#1A202E`):** Surfaces rely on monochromatic slate-navy stepping rather than pure black, reducing ocular fatigue while maintaining pitch contrast.
- **Semantic Accents:** Regulatory refusals and compliance flags strictly leverage `#FF5656`, whereas risk advisories, exit-load alerts, and tax warnings utilize `#FFB800`.
- **Text & Borders:** Strict optical separation uses `#FFFFFF` for primary headers, `#94A3B8` for secondary conversational context, and `#232B3B` for surgical 1px containment borders.

## Typography

The typographic hierarchy pairs the structured geometry of **Plus Jakarta Sans** for prominent figures, section titles, and fund names with the hyper-legible neutrality of **Inter** for conversational bubbles, mathematical breakdowns, and tabular FAQ answers.

Tabular figures (`font-variant-numeric: tabular-nums`) must be enabled across all numerical outputs (CAGR, expense ratios, AUM, exit loads). Body copy maintains a generous 1.6x line-height ratio to preserve reading comfort over prolonged assistant interactions. Compliance statements and micro-disclaimers are rendered in uppercase `label-sm` with widened letter-spacing for crisp legal rendering.

## Layout & Spacing

The conversational interface uses an 8pt base spacing rhythm governed by a central layout thread:

- **Desktop (min-width: 1024px):** A dual-column architecture with an asymmetrical split. The assistant chat panel occupies a focused 720px fluid track, bounded by a 360px sticky sidebar dedicated to fund metrics, peer comparison matrices, and SEBI compliance summaries. Gutters hold strictly at `1.5rem`.
- **Tablet (768px - 1023px):** A single-column view with an off-canvas drawer for auxiliary fund data. Content margins standardise to `2rem`.
- **Mobile (< 768px):** A full-bleed chat container with pinned bottom prompt controls. Canvas margins contract to `1rem` to maximise conversational horizontal density. Message bubbles take up to 88% of screen width.

## Elevation & Depth

Visual hierarchy does not rely on diffused drop shadows, which dilute the clarity of dark modes. Instead, elevation uses a **Tonal Surface Stacking** strategy paired with precise borders:

- **Base Floor (Level 0):** Pure `#0B0D12`, zero border, absolute background plane.
- **Card Tier (Level 1):** `#121620` resting on canvas, framed with a 1px solid border of `#232B3B`.
- **Elevated Interactive Tier (Level 2):** `#1A202E` with 1px border `#232B3B` plus an ambient, faint glow: `0 4px 20px -2px rgba(0, 0, 0, 0.5)`. Used for active message cards, dropdown menus, and prompt suggestions.
- **Active / Focused Overlays (Level 3):** Modal overlays, regulatory warning panels, and bottom sheets leverage an ultra-subtle primary halo: `0 0 0 1px #00D09C, 0 12px 32px rgba(0, 208, 156, 0.08)`.

## Shapes

The design system maintains a modern, balanced shape geometry with `roundedness: 2`. Standard containers, input fields, and chat dialogue bubbles feature an 8px (`0.5rem`) corner radius. Larger parent surfaces and interactive fund comparison cards take `rounded-lg` (16px / `1rem`), while compliance status badges and action chips leverage full pill styling (`9999px`) to immediately telegraph tapability.

## Components

### Buttons
- **Primary:** Background `#00D09C`, text `#0B0D12`, font weight 600. Hover triggers an instant transition to `#00E6AD` accompanied by a micro-box-shadow `0 0 16px rgba(0, 230, 173, 0.3)`.
- **Secondary:** Surface `#1A202E`, border 1px solid `#232B3B`, text `#FFFFFF`. Hover elevates border to `#5367FF` with text shifted to `#5367FF`.
- **Ghost:** Transparent background, text `#94A3B8`, hovering transitions to text `#FFFFFF` and surface `#121620`.

### Message Bubbles
- **User Query:** Anchored right, surface `#1A202E`, border 1px solid `#232B3B`, text `#FFFFFF`. Radius: `16px 16px 4px 16px`.
- **Assistant Response:** Anchored left, surface `#121620`, border 1px solid `#232B3B`, text `#94A3B8`, with bold sections in `#FFFFFF`. Left edge accented with a 2px vertical stroke of `#00D09C`. Radius: `16px 16px 16px 4px`.

### Prompt Chips & Suggestions
Pill-shaped containers (`padding: 6px 14px`), background `#121620`, border 1px solid `#232B3B`, label text `#94A3B8`. On hover, border activates to `#00D09C` and label glows `#FFFFFF`.

### Inputs
Pinned prompt bar with a continuous `#121620` surface, 1px solid `#232B3B` border, text `#FFFFFF`, and placeholder `#94A3B8`. Focus state removes default browser rings, applying a crisp 1px stroke of `#00D09C` and a localized inset glow.

### Badges & Compliance Status Pills
- **SEBI Approved / Low Risk:** Pill badge with translucent green fill `rgba(0, 208, 156, 0.1)`, 1px border `rgba(0, 208, 156, 0.3)`, text `#00D09C`.
- **Refusal / High Risk / Lock-In Warning:** Pill badge with translucent red fill `rgba(255, 86, 86, 0.1)`, 1px border `rgba(255, 86, 86, 0.3)`, text `#FF5656`.

### Cards (Fund & NAV Disclosures)
Structured `#121620` surfaces with a 1px `#232B3B` perimeter. Header displays fund title (`Plus Jakarta Sans`, 16px, `#FFFFFF`), followed by horizontal split stats (NAV, 3Y Returns, Expense Ratio) in tabular `Inter`. Positive trajectories render in `#00D09C`; benchmark deficits render in `#FF5656`.