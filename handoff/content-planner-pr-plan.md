# `content_planner/` — implementation PR plan

Breaks `content-planner-design.md` into small, independently-reviewable PRs.
Each PR should build green, pass `makemigrations --check`, and ship its own tests.

## Confirm before coding (settled recommendations in the design)

These change the Phase 1 model shape, so lock them before PR 1.x:

- **D1 → (a) flat access, seamed for future roles.** v1 behavior: any collaborator can do
  anything on a board except invite others or delete the board. But wire the seams now so
  varying access rights are a later helper-rewrite, not a refactor:
  - Keep `Post.created_by` (set once, never changes) even though flat mode doesn't gate on it.
    It's the data a future per-post rule needs and can't be backfilled accurately later.
  - Route every authz decision through named helpers in `permissions.py`
    (`can_edit_post`, `can_publish_post`, `can_manage_collaborators`, `can_delete_board`,
    `can_edit_campaign`), each implementing the flat rule in v1. Views/templates never inline
    the rule. Future tiers = rewrite the helper bodies.
  - Add `ContentCollaborator.role` (CharField + choices, single default value e.g. `"editor"`
    in v1) as the structural hook, so adding `"viewer"`/`"approver"`/etc. later needs no data
    backfill. Helpers may ignore `role` in v1.
- **D2 → (a) URL-only survey links.** No cross-app polymorphic relation in v1.
- **D3 → no encryption for assets.** `FileField` + `source_url`, standard `MEDIA_ROOT`/`MEDIA_URL`.

Plan below assumes all three. Repo conventions to follow: mirror the `surveys/` app
(`models.py`, `admin.py`, `forms.py`, `permissions.py`, `services/`, `urls.py`, `views.py`,
`templates/`). Imports top-of-file, isort order. CSS goes in the external stylesheet, not inline.

### Permission-check convention (required)

All "can this user do X?" gating goes through Django's permission system, never a
direct group-membership test:

- **App-level gate:** `user.has_perm("content_planner.access_content_planner")` (and
  `{% if perms.content_planner.access_content_planner %}` in templates). Mirror
  `surveys/permissions.py` — a thin `is_content_user(user)` wrapper around `has_perm`.
- The `content_planner_users` group is only the **grant vehicle**: the
  `access_content_planner` permission is attached to that group, and `grant_app_access`
  adds users to it. Reads must NOT call `user.groups.filter(...)`.
- **Deviation from accounts-design `has_app_access`:** that helper checks
  `user.groups.filter(name=...).exists()` directly — do not use it for gating in this app.
  Use `has_perm` instead. (Keep `grant_app_access`/`revoke_app_access` for the grant side.)
- **Object-level access** (this board, owner ∪ collaborator) uses a
  `can_access_board(user, board)` helper mirroring `can_access_survey`: superuser passes,
  `board.owner_id == user.id`, else `board.collaborators.filter(user=user).exists()`. This
  is data-model membership on the board, not a Django auth Group — distinct from the rule above.

---

## Track 0 — accounts extraction (ALREADY DONE — in `core`, not `accounts`)

**Resolved.** The shared bases the design expected from an `accounts` app already exist
in the **`core`** app, and availability/surveys/expenses already use them:

- `core.models`: `BaseModel`, `AbstractInvitation`, `AbstractMembership`, `mint_invitation_key`
- `core.permissions`: `has_app_access`, `grant_app_access`, `revoke_app_access` — and
  `has_app_access` already delegates to `user.has_perm()`, satisfying the gating convention.

So there is no `accounts` app to build, and the design doc's `from accounts.models import ...`
should read **`from core.models import ...`**. content_planner imports from `core`.

---

## Phase 1 — Core models + Django admin  ✅ BUILT on branch `content-planner-phase1`

Goal: validate the model shape by entering real campaigns through admin. No web UI yet.

**Status: implemented and tested** (PRs 1.1–1.6 landed together as the Phase 1 slice).
Files: `content_planner/{models,permissions,billing,admin,scheduling,slugs,apps}.py`,
migrations `0001_initial` + `0002_seed_content_planner_user_group`, settings wiring
(`INSTALLED_APPS`, `CONTENT_INVITATION_EXPIRY_DAYS`), and tests
`tests/test_content_planner_{models,permissions,admin}.py`. Full suite: 795 passed, 100%
coverage; `makemigrations --check` clean.

- **PR 1.1 — App scaffold + board/membership models.**
  `content_planner` app + `INSTALLED_APPS`. `ContentBoard` (with `access_content_planner`
  permission), `ContentCollaborator` (carries a `role` field, single default value in v1 — the
  D1 seam), `ContentInvitation`. Migration attaches
  `access_content_planner` to the `content_planner_users` group so `grant_app_access` (adding
  to the group) confers the permission. `permissions.py` with `is_content_user(user)` →
  `has_perm`, `can_access_board(user, board)`, plus the flat-rule authz helpers
  (`can_edit_post`, `can_publish_post`, `can_manage_collaborators`, `can_delete_board`,
  `can_edit_campaign`). Admin for all three. First migration.
- **PR 1.2 — Tag + Campaign.** Models, admin, per-board uniqueness constraints,
  case-insensitive `Tag` functional index + whitespace strip, Campaign slug generation
  (regenerate-on-save, per-board collision suffixes, word-boundary trim, skip-if-unchanged).
  Tests: tag case-insensitive uniqueness, tag per-board coexistence, slug collisions.
- **PR 1.3 — Asset.** Model + admin, `FileField` + `source_url`, status enum, media storage
  wiring (D3). Per-board scoping. Test: nothing heavy yet (storage smoke).
- **PR 1.4 — Post.** Model + admin, status enum, `channel`, `created_by` (recording-only in
  v1; the D1 seam), `date_locked`,
  `is_all_day`, M2M to Asset, Post slug generation (per-campaign). Form-layer asset-board
  scoping comes in Phase 2; here just the model + constraint. Test: per-campaign slug uniqueness.
- **PR 1.5 — Event anchoring + tz behavior.** `scheduled_at` compute from
  `event_date + anchor_offset_days + time-of-day`; recompute all anchored posts on
  `event_date` change (skip locked, preserve time-of-day, default 09:00). Tests: auto-compute
  `anchor_offset_days`, recompute-on-event-date-change, UTC↔board-tz round-trip without drift.
- **PR 1.6 — Billing seams.** `content_planner/billing.py` with no-op `has_feature` and
  `check_quota`. Tests: both pass for every v1 feature/site. (~15 lines; cheap to land early.)

## Phase 2 — Web UI, single (personal) board

**Status: PRs 2.1–2.4 BUILT on branch `content-planner-phase1`** (the navigable read+create
core). Added `views.py`, `forms.py`, `urls.py`, `selectors.py`, `tagging.py`, 10 templates
under `content_planner/templates/content_planner/`, root-URL include (`/content/`), and a
"Content" navbar link. Slug `reserved` support + `ContentBoard.assign_slug` (reserved-slug
validation) added. Tests: `tests/test_content_planner_{views,selectors}.py` + model/slug
additions. content_planner app 100% covered; full suite green. **Deferred: PRs 2.5 (asset
library), 2.6 (bulk-shift), 2.7 (clone).** Note: per-channel status-subset validation (2.4) was
left out — all 7 statuses apply to posts in v1, so there's nothing to restrict yet; revisit if a
channel needs a narrower set.

- **PR 2.1 — Access gating + shell + board index.** ✅ Gate via
  `has_perm("content_planner.access_content_planner")` (per the convention above) + per-board
  `can_access_board`, base templates + nav,
  `/content/` board index with pending/overdue counts, single-board redirect, reserved-slug
  validation.
- **PR 2.2 — Daily overview (board home).** ✅ Overdue / Today / This week / Awaiting your action /
  Recently published sections, board-tz aware (logic in `selectors.py`). Test: stalled filter
  `(now - modified_date) > N days AND status == DRAFTING`.
- **PR 2.3 — Campaign list + manual create/edit form.** ✅ Tags entered comma-separated, resolved
  against the board (existing reused, new created) on submit. (Autocomplete UI deferred to polish.)
- **PR 2.4 — Campaign detail + Post detail + post create/edit.** ✅ Asset picker scoped to board
  (form-layer validation). Test: cross-board asset attach raises ValidationError. (Per-channel
  status-subset validation not needed in v1 — see note above.)
- **PR 2.5 — Asset library page.** `/content/<board>/assets/` list/upload/edit/archive. Test:
  lists only current-board assets. Wire `check_quota` at upload site.
- **PR 2.6 — Bulk-shift.** Shift-by-delta + re-anchor, diff preview → confirm, locked posts
  skipped. Reusable diff component (also used by 4b). Tests: skips `date_locked`, re-anchor
  recompute.
- **PR 2.7 — Clone.** Dialog (name, target board, new event_date, copy posts/assets/notes/tags),
  status reset to DRAFTING, `published_url` cleared, within-board keeps asset refs, cross-board
  drops them, scheduled_at recompute/null. Tests: all the clone cases in the design's test list.
  Wire `check_quota` at campaign-create site.

## Phase 3 — Multi-board / collaboration

- **PR 3.1 — Invitation + collaborator management.** Send/accept flow on `ContentInvitation`,
  collaborator list/remove UI. `check_quota` at invite site.
- **PR 3.2 — Board switcher + cross-board overview.** `/content/all/` aggregated daily view with
  per-row board tag; switcher "All boards" entry.
- **PR 3.3 — Authz enforcement (D1a flat).** Wire views to the `permissions.py` authz helpers:
  any collaborator may edit/publish posts and campaigns; only the board owner can manage
  collaborators or delete the board. Tests assert the flat rule AND that the helper boundary
  exists (so a future role split is a helper change). Keeps `created_by`/`role` unused-but-present.

## Phase 4a — Claude loop

- **PR 4a.1 — Export-as-JSON.** `/content/<board>/c/<slug>/export/` (JSON + `?view=html`
  wrapper). Smallest; ship first. Test: includes id/slug/status/published_url.
- **PR 4a.2 — MCP read-only server.** `/mcp/content/`: `list_boards`, `list_campaigns`,
  `get_campaign`, `list_upcoming`, `list_stalled`; every response carries id + slug. Enforce
  with `has_perm` app gate + `can_access_board` per board. Tests:
  board-membership enforcement (collaborator on A blocked on B; no-membership reads nothing).
  Gate behind `has_feature("mcp_loop")` seam.
- **PR 4a.3 — Create-from-chat form.** Paste JSON → editable cards → single-transaction create;
  tag resolution against target board, scheduled_at compute (anchored + absolute), all posts
  DRAFTING, `created_by` set. Gate behind `has_feature("create_from_chat")`. Tests: export→import
  round-trip forces DRAFTING; import ignores id/status/published_url; unknown tags created.

## Phase 4b — Reschedule via paste (optional)

- **PR 4b.1 — Import box.** `/content/<board>/c/<slug>/import/`, one line per post, id-canonical
  matching with rename surfacing, diff → confirm, locked skipped, all-or-nothing. Reuses 2.6's
  diff component. Build only if it beats bulk-shift UI in practice.

## Phase 5 — Polish (each independent)

- **PR 5.1** — ✅ BUILT. Schedule grid (month) at `/content/<board>/schedule/`: Sunday-first
  calendar, posts placed on board-local dates, prev/next month nav, "Schedule" board tab.
  Grid logic in `selectors.month_schedule`. Tests in
  `tests/test_content_planner_{selectors,views}.py`.
- **PR 5.1b** — ✅ BUILT (requested 2026-06-26). Channel picker is now tag-style toggle buttons
  (`btn-check`) instead of a dropdown. On **create**, channels is multi-select and fans out into
  one `Post` per channel (sharing body/schedule/metadata, each independently trackable) —
  `PostCreateForm.create_posts`. On **edit**, single-select. Partial `_channel_picker.html`.
- **PR 5.2** — Stalled-item hint UI on overview/cards.
- **PR 5.3** — Clone stale-content banner + date/proper-noun heuristic.
- **PR 5.4** — ✅ PARTIAL (requested 2026-06-26). Live, non-blocking body char counter on the
  post form with per-platform limit cues (Bluesky 300, X 280, Mastodon/Threads 500, LinkedIn
  3000), shown for all platforms regardless of selected channel. Count includes any hashtags
  typed in the body. (Remaining: hard-enforce option if ever wanted — currently warn-only.)
- **PR 5.1c — Post form polish (requested 2026-06-26).** ✅ 2-column layout (short fields share
  rows), status rendered as a dot+pill toggle group mirroring the surveys status UI
  (`_status_picker.html` + `.sc-status-*` CSS), channel toggle chips with a clear selected state
  in both themes (`.sc-chip`), removed the stray blank "----" channel option, dark-mode calendar
  "today" fix (`.sc-today`), and converted a stray multi-line `{# #}` to `{% comment %}`.
- **PR 5.1d — Consistency + nav polish (requested 2026-06-26).** ✅ Reusable status pill used
  everywhere (`_status_badge.html` read-only pill + calendar status dot, all sharing the
  `.sc-st-*` colours); bigger body textarea (10 rows); Instagram channel added
  (`0003_alter_post_channel`, char limit 2200); post-form field regrouping (is_all_day under the
  date, anchor + date_locked together); breadcrumbs on post detail / post form / campaign detail;
  full-width post form. **Overdue marker**: `Post.is_overdue` (past board-local date, not
  terminal) surfaced as a red badge on list rows + detail and bold-red on the calendar.
- **PR 5.1e — Scheduling input chooser (requested 2026-06-26).** ✅ Non-event campaigns show only
  the absolute `scheduled_at` (offset removed). Event-anchored campaigns get a **"Schedule by"**
  toggle (Days from event date ↔ Specific date) that reveals the chosen field; the unused one is
  cleared in `clean` so the model derives it (`_resolve_schedule_mode`). `is_all_day` applies in
  both cases (only flags whether the time component is shown). Either way the post stays anchored
  — entering a specific date just stores the equivalent offset.
- **PR 5.5 — Hashtags (copy-time append, channel-aware).** New, requested 2026-06-26. NOT the
  same as `Tag` (which is internal campaign grouping — keep separate; don't promote private
  tags to public hashtags). Design:
  - Add a `hashtags` CharField default set at the **Campaign** level (the reused set), plus an
    optional per-**Post** `hashtags` field for additions/overrides. Stored **outside**
    `body_snippet` so the body stays clean and the hashtags stay reusable and channel-tunable.
  - Appended at **copy time** by the post-detail Copy button (show a preview of the final text),
    and **only for social channels** (mastodon/x/linkedin) — never blog/newsletter.
  - Pairs with 5.4: hashtags count toward the X 280 limit, so surface the char count at copy
    time. Pairs with 4a (export/import): include `hashtags` in the JSON schema when those land.
  - Effective hashtags for a post = campaign default ∪ post-level, de-duplicated, normalized to
    `#tag` form. ~1 field per model + a small copy-time helper; one self-contained PR.

## Deferred (not in v1 — see design open questions)

ICS feed, email digest, recurring/template campaigns, cross-app survey linking (D2b),
template DSL, analytics ingestion, two-way MCP writes, BillingAccount/Teams tier.

---

## Suggested merge order

`0.1` → `1.1–1.6` (sequential; 1.6 can slot anywhere after 1.1) → Phase 2 in order
(2.6/2.7 depend on 2.4) → Phase 3 → `4a.1` then `4a.2`/`4a.3` → optional `4b` → Phase 5
(any order). Phase 2 alone is usable solo; Phase 3 unlocks community boards; Phase 4 closes
the Claude loop.