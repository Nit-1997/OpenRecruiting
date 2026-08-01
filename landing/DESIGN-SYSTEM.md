# OpenRecruiting Landing Page Design System

## Brand Vision

OpenRecruiting is building an autonomous AI talent acquisition partner — an AI employee that sits alongside recruiters, plans interviews, joins calls, generates feedback, and connects the dots across sourcing, ATS, and hiring workflows. The brand communicates: **calm intelligence, trust, autonomy, and modern sophistication**.

Positioning shift: "Interview copilot" → **"Your AI Talent Partner"**

---

## Typography

Three-font system creating editorial elegance with technical precision.

### Font Stack

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| Display | **Cormorant Garamond** (serif) | 300, 400, 500 | Hero headlines, section H2s, large display text |
| Body | **PP Neue Montreal** (sans-serif) | 400, 500 | Body copy, card titles, nav links, buttons |
| Mono | **PPSupplyMono** (monospace) | 400 | Section labels, step numbers, counters, metadata |

**Fallbacks:**
- Display: `"Cormorant Garamond", "Cormorant", Georgia, serif`
- Body: `"PP Neue Montreal", "Inter", -apple-system, BlinkMacSystemFont, sans-serif`
- Mono: `"PPSupplyMono", "JetBrains Mono", "SF Mono", monospace`

**Cormorant Garamond** is available on Google Fonts. PP Neue Montreal and PPSupplyMono are Pangram Pangram foundry fonts (self-hosted).

### Type Scale

| Token | Size | Weight | Font | Color | Usage |
|-------|------|--------|------|-------|-------|
| hero-h1 | 56–64px | 400 | Cormorant Garamond | #FFFFFF | Hero headline (dark bg) |
| section-h2 | 40–48px | 400 | Cormorant Garamond | #111111 | Section headings |
| card-h3 | 20–22px | 500 | PP Neue Montreal | #111111 | Card titles, feature names |
| section-label | 12–13px | 400 | PPSupplyMono | #888888 | Labels above sections, uppercase, tracked |
| body | 16px | 400 | PP Neue Montreal | #555555 | Paragraphs, descriptions |
| body-sm | 14px | 400 | PP Neue Montreal | #888888 | Meta text, timestamps |
| mono-counter | 14px | 400 | PPSupplyMono | #AAAAAA | Step numbers, slide counters |
| cta-button | 15px | 500 | PP Neue Montreal | inherit | Button text |
| nav-link | 14–15px | 400 | PP Neue Montreal | #111111 | Navigation links |

**Key rule:** Headings use font-weight 400 (normal). Visual hierarchy is created through SIZE and FONT FAMILY contrast (serif vs sans), not weight.

---

## Color Palette

### Light Mode (Primary — used for most sections)

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#FAF9F7` | Page background (warm off-white) |
| `--surface` | `#F2F0ED` | Card backgrounds, panels |
| `--surface-accent` | `#ECEAE6` | Elevated/bordered containers |
| `--text-primary` | `#111111` | Headings, body text |
| `--text-secondary` | `#555555` | Descriptions, body copy |
| `--text-muted` | `#888888` | Labels, secondary info |
| `--text-faint` | `#AAAAAA` | Timestamps, placeholders |
| `--border` | `#E5E3DF` | Card borders, dividers |
| `--cta-bg` | `#111111` | Primary button background |
| `--cta-text` | `#FFFFFF` | Primary button text |

### Dark Mode (Hero section only)

| Token | Value | Usage |
|-------|-------|-------|
| `--hero-bg` | `#0A0A0A` | Hero canvas background |
| `--hero-text` | `#FFFFFF` | Hero headline |
| `--hero-text-muted` | `rgba(255,255,255,0.6)` | Hero subtitle |
| `--hero-text-faint` | `rgba(255,255,255,0.35)` | Hero meta, logo labels |
| `--hero-accent` | `#D4AF37` | Optional gold accent (used sparingly) |

### Accent Gradient (CTA section, product showcase)

```css
background: linear-gradient(180deg, #C5D0F5 0%, #DAE2FA 40%, #EBF0FC 70%, #F2F4FC 100%);
```

Soft periwinkle-to-white. Used as full-bleed background on the CTA block and as a container for product screenshots.

---

## Spacing

8px base unit system.

| Token | Value | Usage |
|-------|-------|-------|
| `--space-1` | 4px | Tight gaps |
| `--space-2` | 8px | Icon gaps, inline spacing |
| `--space-3` | 12px | Small card padding |
| `--space-4` | 16px | Standard element gaps |
| `--space-6` | 24px | Card padding |
| `--space-8` | 32px | Section sub-spacing |
| `--space-12` | 48px | Large element spacing |
| `--space-16` | 64px | Section vertical gaps |
| `--space-20` | 80px | Full section padding |

**Section spacing:** 80–120px vertical between major sections.
**Max content width:** 960px centered.
**Page padding:** 24px mobile / 48px desktop.

---

## Border Radius

| Element | Radius |
|---------|--------|
| Buttons | 8px |
| Cards | 12px |
| Input fields | 8px |
| Dropdowns | 6px |
| Pill badges | 999px |
| Avatars | 50% |
| Hero/showcase containers | 16–20px |

---

## Shadows

Minimal. The design relies on surface color contrast and subtle borders.

- **Cards:** No shadow. Use `--surface` (#F2F0ED) against `--bg` (#FAF9F7) + 1px `--border`.
- **Floating UI mockups:** `box-shadow: 0 2px 12px rgba(0,0,0,0.06)` — only element with shadow.
- **Buttons on hover:** No shadow change. Subtle opacity/color transition only.

---

## Components

### Navigation Bar
- Height: 64px, sticky, no shadow, no border
- Background: `--bg` (#FAF9F7), blends into page
- Logo: "localhost:3000" in Pacifico (brand font, kept from current), ".ai" in muted color
- Nav links: PP Neue Montreal, 14px, 400 weight, #111111
- CTA: "Book a Demo" — black pill button (#111111 bg, white text, 8px radius)
- Mobile: hamburger menu

### Hero Section
- Full viewport height (100vh), dark background (#0A0A0A)
- Background visual: abstract network topology animation (WebGL/Three.js) — glowing nodes connected by thin luminous lines, slow breathing motion. Colors: muted blues, warm ambers, soft whites.
- Alternative: lumina slider effect (glass shader transitions between ambient images)
- Overlay: gradient from bottom (rgba(10,10,10,0.7) → transparent)
- Label: PPSupplyMono, 12px, uppercase, tracked, rgba(255,255,255,0.4)
- Headline: Cormorant Garamond, 56–64px, weight 400, white
- Subtitle: PP Neue Montreal, 18px, rgba(255,255,255,0.6)
- CTA: white button (#FFF bg, #111 text) with subtle glow
- Logo cloud: monochrome white logos, opacity 0.25, auto-scroll marquee

### Feature Cards (How It Works)
- Stacked card layout with -skew-y-[4deg] tilt
- Interaction: hover reveals back cards by pushing front cards down/aside, 500ms transitions
- Back cards have grayscale overlay that clears on hover
- Card: #F2F0ED bg, 1px #E5E3DF border, 12px radius, 24px padding
- Step pill: PPSupplyMono, 12px, in muted pill badge
- Title: PP Neue Montreal, 20px, 500 weight
- Description: PP Neue Montreal, 14px, #555555

### Testimonial Cards (Twitter/X style)
- Same stacked interaction as feature cards, -skew-y-[8deg] tilt
- White card bg, 1px #E5E3DF border, 12px radius
- Twitter/X icon top-right, verified badges
- Width: 380px, min-height: 180px

### Value Proposition Cards
- Horizontal row of 3 on desktop, stacked on mobile
- Same flat card styling as feature cards
- Small grayscale integration logos at top of each card

### CTA Section
- Full-width periwinkle gradient background
- Centered text + black CTA button
- 80px vertical padding

### Footer
- 4-column layout: Brand | Product | Company | Legal
- Same warm background (#FAF9F7)
- 1px border-top (#E5E3DF)
- PP Neue Montreal for all links, 14px

---

## Motion & Interaction

- **Hover transitions:** 150–200ms ease. Subtle opacity/color changes only.
- **Card hover:** lift -4px with smooth transition. No scale effects.
- **Logo marquee:** continuous horizontal scroll, 30s duration per loop.
- **Hero text:** GSAP stagger animations — character-by-character reveal on load.
- **Section entrances:** Framer Motion fade-up, triggered on viewport intersection.
- **Stacked card interactions:** 500ms transitions for card repositioning on hover.
- **No heavy animations** outside the hero section. The page should feel fast and static.

---

## Page Structure

```
<Header />
<Hero />                    ← dark bg, full viewport, WebGL/video backdrop
<ProductShowcase />         ← periwinkle gradient container, floating UI screenshot
<HowItWorks />              ← stacked cards, 6 steps in 2 groups
<WhyOpenRecruiting />              ← 3 value prop cards in a row
<Testimonials />            ← stacked Twitter-style cards
<IntegrationBar />          ← single row of grayscale partner logos
<CTASection />              ← periwinkle gradient, final conversion
<Footer />
```

---

## Key Design Principles

1. **Warmth over cold white** — #FAF9F7 everywhere, never #FFFFFF for backgrounds
2. **Serif + sans contrast** — Cormorant Garamond headings against PP Neue Montreal body creates editorial sophistication
3. **Weight restraint** — Headings use 400 weight. Hierarchy through size and font family
4. **Minimal color** — Near-monochrome. Only color accents: dark hero, periwinkle CTA gradient
5. **Flat cards** — No shadows. Surface color + border contrast
6. **Generous whitespace** — 80–120px between sections
7. **Centered layouts** — Constrained to 960px max-width
8. **One CTA** — "Book a Demo" in solid black, consistent everywhere
9. **Mono for metadata** — PPSupplyMono for labels, counters, step numbers — adds technical precision feel

---

## CSS Custom Properties (Implementation Reference)

```css
:root {
  --font-display: "Cormorant Garamond", Georgia, serif;
  --font-sans: "PP Neue Montreal", "Inter", -apple-system, sans-serif;
  --font-mono: "PPSupplyMono", "JetBrains Mono", monospace;

  --bg: #FAF9F7;
  --surface: #F2F0ED;
  --surface-accent: #ECEAE6;
  --border: #E5E3DF;
  --text-primary: #111111;
  --text-secondary: #555555;
  --text-muted: #888888;
  --text-faint: #AAAAAA;
  --cta-bg: #111111;
  --cta-text: #FFFFFF;

  --hero-bg: #0A0A0A;
  --hero-accent: #D4AF37;
  --accent-gradient-start: #C5D0F5;
  --accent-gradient-end: #F2F4FC;

  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-pill: 999px;

  --max-width: 960px;
  --section-spacing: 80px;
}
```

---

## Font Loading Strategy

```tsx
// layout.tsx — Google Fonts
import { Cormorant_Garamond } from "next/font/google";

const cormorantGaramond = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  display: "swap",
});

// PP Neue Montreal & PPSupplyMono — self-hosted in /public/fonts/
// Load via @font-face in globals.css
```

```css
/* globals.css */
@font-face {
  font-family: "PP Neue Montreal";
  src: url("/fonts/PPNeueMontreal-Regular.woff2") format("woff2");
  font-weight: 400;
  font-display: swap;
}
@font-face {
  font-family: "PP Neue Montreal";
  src: url("/fonts/PPNeueMontreal-Medium.woff2") format("woff2");
  font-weight: 500;
  font-display: swap;
}
@font-face {
  font-family: "PPSupplyMono";
  src: url("/fonts/PPSupplyMono-Regular.woff2") format("woff2");
  font-weight: 400;
  font-display: swap;
}
```
