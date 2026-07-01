---
name: app-ui-conventions
description: UI conventions for building or changing app pages in the secretcodes repo — the authenticated list/home header ("Your X" + "+ New" button), breadcrumb back-nav ("All X", no arrows), the public marketing landing hero, and the standard wording. Use whenever creating a new app or adding pages to an existing one so the apps stay visually consistent.
---

# App UI conventions (secretcodes)

Every app (expenses, surveys, content_planner, qrcode_manager, …) should follow
these patterns so a new app looks and reads like the existing ones. Human-facing
version: `docs/conventions/ui-patterns.md` (docs.secretcodes.dev).

## 1. Authenticated list / home page

The app's main page for a signed-in, authorized user. A flex header: heading on
the left, actions on the right. Heading is **"Your {things}"** as an `h1.h3`.

```html
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1 class="h3 mb-0">
        Your <em class="sc-italic">{things}</em>
    </h1>
    <div class="d-flex gap-2">
        {# secondary actions first, styled btn-outline-secondary #}
        <a class="btn btn-primary" href="{% url 'app:thing_create' %}">+ New {thing}</a>
    </div>
</div>
```

- Heading wording: **"Your X"** — "Your boards", "Your events", "Your surveys", "Your QR codes".
- The **noun** is wrapped in `<em class="sc-italic">…</em>`, the site-wide accent voice: display-font italic in the brand accent (theme-aware orange), as in the landing's "for myself" and the login's welcome "back". The leading word (e.g. "Your") stays default ink.
- Heading element: **always `<h1 class="h3 mb-0">`** (never a bare `<h1>`; that renders full display size and looks inconsistent).
- Primary action: `btn btn-primary`, labelled **"+ New {thing}"**, on the right.
- Extra actions: `btn btn-outline-secondary`, to the left of the primary, inside a `d-flex gap-2`.
- Gate the actions with `perms.app.codename` (see the has-perm convention), not group checks.

## 2. Detail / sub pages — breadcrumb back-nav

Any page below the list (a single event, a board's tabs, a create form) starts
with a Bootstrap breadcrumb. **No arrows.** Parent crumb is **"All {things}"**
linking to the list; the current page is the active crumb.

```html
<nav aria-label="breadcrumb">
    <ol class="breadcrumb">
        <li class="breadcrumb-item">
            <a href="{% url 'app:thing_list' %}">All {things}</a>
        </li>
        <li class="breadcrumb-item active" aria-current="page">
            {{ current_thing }}
        </li>
    </ol>
</nav>
```

- Back-link wording: **"All X"** — "All events", "All surveys", "All boards", "All QR codes".
- Never use a `←` arrow or a `btn btn-link` back-button; always the breadcrumb.
- When a page has section **tabs** (surveys `_subnav.html`, content `_board_nav.html`),
  put the breadcrumb above/inline with the tabs; keep the tabs.
- Put shared breadcrumb+tabs in a `_subnav`/`_board_nav` partial so every page in
  the app inherits it from one place.

## 3. Public / unauthenticated landing (marketing hero)

The page an **anonymous or non-invited** visitor sees. Reuse the shared hero
partial — do not hand-roll it:

```django
{% include "_app_landing.html" with num="07" name="QR codes" title_lead="Short links," title_accent="scannable codes" lede="One or two sentences." status="open to all" show_signin=True %}
```

This renders the numbered eyebrow (matches the home-page tile), the two-tone
`sc-display` title, the lede, an optional access note, and the `sc-coords` status
bar. `num` matches the home-page tile number.

**This is a different page from #1.** The hero is the *marketing landing* for
anonymous visitors; the "Your X" header (#1) is the *working page* for signed-in
users. Don't put the hero on the authenticated list page.

## 4. Wording cheat-sheet

| Context | Wording |
|---|---|
| Authenticated list heading | **Your {things}** |
| Create button | **+ New {thing}** |
| Breadcrumb back-link | **All {things}** |
| Public landing title | two-tone via `_app_landing.html` |

## 5. Related conventions (already in the repo)

- **Permissions:** gate reads with `user.has_perm` / `perms.app.codename`; groups only grant the perm.
- **CSS:** add to the external `secretcodes/static/brand/secret-codes.css`, never inline `<style>`.
- **Theme:** brand `.sc-*` classes + CSS vars, dark/light aware. Bootstrap `list-group-item-action` uses the full text colour via `--bs-list-group-action-color` (already set) so clickable lists don't look greyed out.
- **Landing partial:** `secretcodes/templates/_app_landing.html`.