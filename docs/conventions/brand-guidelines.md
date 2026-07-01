# Brand guidelines

The Secret Codes visual language. Everything here is enforced by the shared
stylesheet `secretcodes/static/brand/secret-codes.css` (loaded after Bootstrap
so its overrides win). When building UI, use these tokens and classes rather
than hard-coded values, and pair this with the [UI patterns](ui-patterns.md).

The look is a tribute to Darren Hayes's album *Secret Codes & Battleships*:
battleship-grid monogram, signal-flag colour accents, morse and cipher motifs.
You never explain that on the site; it just has to feel right.

## Design tokens

Use the CSS variables, never raw hex.

| Token | Value | Use |
|---|---|---|
| `--sc-ink` | `#0E1730` | Primary ink (text, dark surfaces) |
| `--sc-ink-soft` | `#1B2747` | Raised dark surface (cards in dark mode) |
| `--sc-paper` | `#F2ECDD` | Paper background |
| `--sc-paper-warm` | `#E8DFC6` | Warmer paper inset |
| `--sc-signal` | `#D84C2F` | **Primary accent**, CTAs, highlights (use sparingly) |
| `--sc-gold` | `#C79A3A` | Success, "decoded" moments |
| `--sc-teal` | `#2E6E6A` | Secondary accent |
| `--sc-lilac` | `#8A7AB8` | Softer synth accent |

Semantic roles resolve to the above and flip in dark mode, so **prefer these**:

- `--sc-bg` / `--sc-fg` : page background / foreground
- `--sc-muted` : ~60% ink, for meta text
- `--sc-accent` : the live accent (signal red on light, warm orange `#F0A06B` on dark)
- `--sc-rule` : hairline borders

!!! warning "Accent is a spice, not a base"
    `--sc-accent` marks "found" moments: CTAs, the active/current thing, the
    italic highlight word. Don't paint whole surfaces with it.

## Typography

Three self-hosted families (vendored under `static/vendor/fonts/`):

| Family | Token | Use |
|---|---|---|
| **Fraunces** (serif) | `--sc-font-display` | Headlines, quotes, the display voice |
| **Inter** (sans) | `--sc-font-body` | Body copy and UI |
| **JetBrains Mono** | `--sc-font-mono` | Code, labels, coordinates, eyebrows |

`h1`–`h3` already use the display serif. The signature move is the
**accent-italic word**: `<em class="sc-italic">…</em>` renders italic Fraunces
in the accent colour, e.g. the landing's "for myself", the login's welcome
"back", and the app headings' "Your *boards*".

## Utility classes

| Class | Effect |
|---|---|
| `.sc-display` | Force the display serif |
| `.sc-italic` | Accent-coloured italic serif (the "Secret *Codes*" treatment) |
| `.sc-mono`, `.sc-eyebrow` | Monospace labels; eyebrow is uppercased, tracked |
| `.sc-muted` | 60% ink |
| `.sc-btn`, `.sc-btn--ghost`, `.sc-btn--accent` | Brand buttons |
| `.sc-bg-ink`, `.sc-bg-paper`, `.sc-bg-signal`, `.sc-bg-teal` | Background helpers |
| `.sc-hero`, `.sc-coords`, `.sc-num` | Landing hero, coordinate status bar, tile number |

## Dark mode

Three modes, all handled by the stylesheet:

- **Auto** (default): follows the OS via `prefers-color-scheme`.
- **Force light**: `class="sc-light"` on `<html>`.
- **Force dark**: `class="sc-dark"` on `<html>`.

Any new component must read the semantic tokens (`--sc-bg`, `--sc-fg`, …) so it
adapts automatically. Bootstrap components inherit through the `--bs-*` remap
below; if you set colours directly on a `.card` or `.list-group-item`, override
at that selector for `.sc-dark` too (see the card/list-group rules in the CSS).

## Bootstrap remapping

The stylesheet sets `--bs-*` variables (`--bs-body-bg`, `--bs-primary`,
`--bs-link-color`, `--bs-list-group-action-color`, …) so stock Bootstrap
components adopt the theme without markup changes. Build with normal Bootstrap
classes and they inherit; reach for `.sc-*` utilities for the branded flourishes.

## Logos

Under `static/brand/` (and mirrored in `handoff/`). All SVGs use `currentColor`
for the ink and `--sc-accent` for the red, so they recolour with CSS.

| Asset | Use |
|---|---|
| `logo-wordmark` | Headers, about pages |
| `logo-monogram` | Avatars, social cards, large marks (SC on a battleship grid) |
| `favicon.svg` | Tab icon |

```css
.site-logo { color: var(--sc-ink); width: 240px; }
.site-logo:hover { color: var(--sc-signal); }
```

## Tone of voice

Warm, dry, a little cryptic. Plain and honest, never salesy.

- ✓ "I built this for myself. You're welcome to fork it."
- ✓ "No cookies, no trackers, no accounts."
- ✗ "Revolutionize your workflow with AI-powered…"
- ✗ "Join 10,000+ creators using…"

**Punctuation:** no em dashes (`—`) in copy or generated content. Use a colon
or a comma, whichever fits the sentence. (Same rule applies to these docs.)

!!! tip "For Claude Code"
    These guidelines are also the `secret-codes-brand` skill in `.claude/skills/`,
    so an agent building UI applies them automatically. The source brand kit
    lives in `handoff/` (README, `secret-codes.css`, logos).
