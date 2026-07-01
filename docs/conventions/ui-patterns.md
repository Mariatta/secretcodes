# UI patterns

Conventions every app on this site follows (expenses, surveys, content planner,
QR codes) so a new app looks and reads like the existing ones. When adding an
app or a page, match these.

There are three recurring page types: the **public landing** an anonymous
visitor sees, the **authenticated list/home** page, and the **detail/sub pages**
below it.

## Wording, at a glance

| Context | Wording |
|---|---|
| Authenticated list heading | **Your {things}** (Your boards, Your events, Your surveys, Your QR codes) |
| Create button | **+ New {thing}** |
| Breadcrumb back-link | **All {things}** (All events, All surveys, All boards, All QR codes) |

The split is deliberate: the page you own is headed "Your X", and the link back
up to it reads "All X".

## 1. Authenticated list / home page

The app's main page for a signed-in, authorized user. A flex header with the
heading on the left and the actions on the right.

```html
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1 class="h3 mb-0">
        Your <em class="sc-italic">boards</em>
    </h1>
    <a class="btn btn-primary" href="{% url 'content_planner:board_create' %}">+ New board</a>
</div>
```

The noun is wrapped in `<em class="sc-italic">`, the site-wide accent voice:
display-font italic in the brand accent (a theme-aware orange, signal red-orange
on light and warm orange on dark), the same treatment as the landing's "for
myself" and the login's welcome "back". The leading word stays the default ink
colour, so the section name pops.

!!! warning "Heading is always `h1.h3`, never a bare `h1`"
    A bare `<h1>` renders at full display size and stands out against the other
    apps. Use `<h1 class="h3 mb-0">`. (Expenses' "Your events" was the odd one
    out until it was aligned.)

- Primary action: `btn btn-primary`, labelled "+ New {thing}", on the right.
- Extra actions: `btn btn-outline-secondary`, to the left of the primary, wrapped
  in a `<div class="d-flex gap-2">`.
- Gate actions with `perms.app.codename`, not group membership.

## 2. Detail / sub pages: breadcrumb back-nav

Any page below the list starts with a Bootstrap breadcrumb. The parent crumb is
"All {things}" and links to the list; the current page is the active crumb.

```html
<nav aria-label="breadcrumb">
    <ol class="breadcrumb">
        <li class="breadcrumb-item">
            <a href="{% url 'expenses:event_list' %}">All events</a>
        </li>
        <li class="breadcrumb-item active" aria-current="page">
            {{ event.name }}
        </li>
    </ol>
</nav>
```

!!! danger "No arrows, no `btn-link` back-buttons"
    Don't use `← All surveys` or a link-styled back button. Always the
    breadcrumb above. Surveys used an arrow link and content used an "All boards"
    button; both were converted so every app matches.

When a page has section **tabs** (the surveys `_subnav.html`, the content
`_board_nav.html`), the breadcrumb sits above or inline with the tabs, and the
tabs stay. Put the shared breadcrumb + tabs in a `_subnav` / `_board_nav`
partial so every page in the app inherits it from one place.

## 3. Public / unauthenticated landing

The page an **anonymous or non-invited** visitor sees. Reuse the shared hero
partial rather than hand-rolling it:

```django
{% include "_app_landing.html" with num="07" name="QR codes" title_lead="Short links," title_accent="scannable codes" lede="One or two sentences about the app." status="open to all" show_signin=True %}
```

It renders the numbered eyebrow (matching the home-page tile), a two-tone
`sc-display` title, the lede, an optional access note, and the `sc-coords`
status bar.

!!! note "The landing is not the list page"
    The hero is the marketing landing for anonymous visitors. The "Your X"
    header (section 1) is the working page for signed-in users. Keep them
    separate: don't put the hero on the authenticated list.

## Related conventions

- **CSS** goes in `secretcodes/static/brand/secret-codes.css`, never inline `<style>`.
- **Theme:** brand `.sc-*` classes and CSS variables, dark/light aware.
- **Permissions:** gate reads through `user.has_perm`; groups only grant the permission.

!!! tip "For Claude Code"
    These conventions are also an invokable skill (`app-ui-conventions`) in
    `.claude/skills/`, so an agent building a new app applies them automatically.
