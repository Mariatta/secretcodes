---
name: secret-codes-brand
description: The Secret Codes brand system: design tokens (--sc-* colours), typography (Fraunces/Inter/JetBrains Mono), the accent-italic voice, dark mode, Bootstrap remapping, logo usage, and tone of voice. Use whenever writing UI, CSS, or copy so it matches the brand kit. Pair with app-ui-conventions for page layout.
---

# Secret Codes brand system

Enforced by `secretcodes/static/brand/secret-codes.css` (loaded after Bootstrap).
Human version: `docs/conventions/brand-guidelines.md`. Source kit: `handoff/`.
The look is a tribute to Darren Hayes's *Secret Codes & Battleships* (battleship
grid, signal-flag accents, cipher/morse motifs): never explained, just felt.

## Tokens: use the variables, never raw hex

- Ink/paper: `--sc-ink` `#0E1730`, `--sc-ink-soft` `#1B2747`, `--sc-paper` `#F2ECDD`, `--sc-paper-warm` `#E8DFC6`
- Signals (sparingly): `--sc-signal` `#D84C2F` (**primary accent/CTA**), `--sc-gold` `#C79A3A` (success), `--sc-teal` `#2E6E6A`, `--sc-lilac` `#8A7AB8`
- **Prefer the semantic tokens** (they flip in dark mode): `--sc-bg`, `--sc-fg`, `--sc-muted`, `--sc-accent` (signal red on light, warm orange `#F0A06B` on dark), `--sc-rule`
- Accent is a spice: CTAs, the active thing, the italic highlight word. Never a whole surface.

## Type

- **Fraunces** = `--sc-font-display` (headlines, quotes). `h1`–`h3` already use it.
- **Inter** = `--sc-font-body` (body + UI).
- **JetBrains Mono** = `--sc-font-mono` (code, labels, coordinates, eyebrows).
- Signature move: the accent-italic word `<em class="sc-italic">…</em>` (italic Fraunces in accent), e.g. "for myself", welcome "back", "Your *boards*".

## Utility classes

`.sc-display`, `.sc-italic`, `.sc-mono`, `.sc-eyebrow`, `.sc-muted`,
`.sc-btn` / `.sc-btn--ghost` / `.sc-btn--accent`,
`.sc-bg-ink` / `.sc-bg-paper` / `.sc-bg-signal` / `.sc-bg-teal`,
`.sc-hero`, `.sc-coords`, `.sc-num`.

## Dark mode

Auto via `prefers-color-scheme`; force with `class="sc-light"` / `class="sc-dark"`
on `<html>`. Every new component must read semantic tokens so it adapts. Bootstrap
sets `--bs-card-bg: #fff` on `.card` directly, so dark overrides for cards /
list-group-items must be written at that selector for `.sc-dark` (see the CSS).

## Bootstrap remapping

The CSS maps `--bs-*` (`--bs-body-bg`, `--bs-primary`, `--bs-link-color`,
`--bs-list-group-action-color`, …) to the theme. Build with normal Bootstrap
classes; they inherit. Use `.sc-*` utilities for branded flourishes.

## Logos (`static/brand/`, `currentColor` + `--sc-accent`)

`logo-wordmark` (headers/about), `logo-monogram` (avatars/social/large),
`favicon.svg` (tab). Recolour with `color:` in CSS.

## Tone

Warm, dry, a little cryptic. Plain and honest, never salesy.

- ✓ "I built this for myself. You're welcome to fork it." / "No cookies, no trackers, no accounts."
- ✗ "Revolutionize your workflow with AI-powered…" / "Join 10,000+ creators…"
- **No em dashes (`—`)** in copy or docs: use a colon or a comma instead.

## Rules of thumb when building UI

1. No hard-coded colours: reference `--sc-*` (or the `--bs-*` the CSS already maps).
2. New CSS goes in `secret-codes.css`, never inline `<style>`.
3. Headings in Fraunces; highlight one word with `.sc-italic`, don't colour the whole line.
4. Verify both light and dark before calling it done.
5. Copy follows the tone above.