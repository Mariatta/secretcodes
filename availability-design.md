# Availability Portal — Design Brief

A new feature for [`secretcodes`](https://github.com/mariatta/secretcodes):
a public availability surface so visitors (and their agents) can see when
Mariatta is free without asking. A paid-booking layer comes later.

## Goals

- Public web page showing a free/busy shadow across all Google calendars
- Quick "is she free at X time?" lookup
- Day-level **availability recommendations** — summary-first view that tags
  each day ("Available" / "Likely available" / "Tight" / "Unlikely" /
  "Unavailable") and surfaces a suggested day for the week, so askers
  don't have to scan a grid of 30-minute cells to gauge fit
- MCP server exposing the same reads to AI agents
- (Phase 3) Stripe-gated booking for paid meetings

## Non-goals

- Replacing Google Calendar as source of truth
- Full Calendly clone
- Auto-booking by agents (humans only, payment required)
- Two-way sync

---

## Architecture

### Django app layout

New app `availability/` alongside `qrcode_manager/`.

```
secretcodes/
├── qrcode_manager/            # existing
├── availability/              # NEW
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── services/
│   │   ├── google.py          # OAuth + freeBusy wrapper
│   │   └── availability.py    # pure computation (no I/O)
│   ├── mcp_server/            # MCP tools
│   └── templates/availability/
├── storage_backend/           # existing
└── secretcodes/               # existing project settings
```

### Data model

**`GoogleAccount`** — one per connected Google account
- `label` (e.g. "personal", "work", "pyladies")
- `email`
- `refresh_token` (encrypted at rest)
- `scopes_granted`
- timestamps

**`TrackedCalendar`** — which sub-calendars count as busy
- `account` → FK `GoogleAccount`
- `google_calendar_id`
- `display_label`
- `is_active`

**`AvailabilityProfile`** — the rules (singleton for MVP)
- `timezone` (default `America/Vancouver`)
- `business_hours` — JSON: weekday → `[(start, end), …]`
- `extended_hours` — JSON: weekday → `[(start, end), …]`
- `default_slot_minutes` (30)
- `min_notice_hours`
- `max_horizon_days`
- `extended_reveal_threshold` — N free business slots in visible week below
  which the "need a different time?" affordance appears

**Phase 3 additions (don't build yet):**
- `BookingProduct` — duration, price, allowed band(s), which calendar to write to
- `BookingPayment` — Stripe session, status, one-time token
- `Booking` — confirmed event, links to Google event ID
- `CompCode` — single-use bypass tokens for friends/community

### Core computation

Pure function in `services/availability.py`:

```python
def compute_availability(
    range_start: datetime,
    range_end: datetime,
    busy_blocks: list[BusyBlock],
    profile: AvailabilityProfile,
    duration: timedelta = timedelta(minutes=30),
    include_extended: bool = False,
) -> AvailabilityResult: ...
```

Returns free slots tagged by band (`business` / `extended`), the count of
business slots in the requested range, and any ranges outside all hours.
No network I/O — trivially unit-testable. The same function powers the web UI,
the check-a-time endpoint, and the MCP tools.

### URL / endpoint structure

**Public**
- `GET  /availability/` — week grid (default: business hours only)
- `GET  /availability/slots.json?start=&end=&duration=&include_extended=`
- `POST /availability/check/` — `{datetime, duration}` → `{free, band, reason}`

**Admin (login-gated)**
- `GET  /availability/admin/` — connected accounts, tracked calendars, profile edit
- `GET  /availability/oauth/start/`
- `GET  /availability/oauth/callback/`

**MCP** (mounted at `/mcp/`)
- Streamable HTTP transport
- Tools:
  - `check_availability(start, end) → {free, band}`
  - `list_free_slots(start, end, duration_min, include_extended=False)`
  - `get_busy_shadow(start, end)` (optional)
  - `get_booking_info()` — stubbed in phase 2, populated in phase 3

### Caching

- Key: `(account_id, start_ymd, end_ymd)`
- TTL: 5 minutes (safe since no booking in phase 1)
- Backing: Django cache framework → Redis if present, else locmem
- Phase 4: switch to push-notification invalidation via Google Calendar watch

### Timezone handling

- Store everything in UTC
- The page renders server-side in the **viewer's timezone**, named by the
  `tz` query parameter (`/availability/?tz=Europe/Lisbon`)
- First visit: the page script reads the browser's timezone
  (`Intl.DateTimeFormat().resolvedOptions().timeZone`) and, when it differs
  from what was rendered, reloads with `tz` filled in
- Viewers can override it with the type-in field ("Times shown in"), for
  example to see slots in the timezone of an upcoming trip. The override
  lives only in the URL: no cookie, no storage, and the link is shareable.
  "Back to my timezone" returns to the browser's own
- `tz` accepts an IANA name in any letter case, the city part of one
  (`lisbon`) when only one zone has it, or a city alias such as `seattle` (`CITY_ALIASES` in `availability/services/timezones.py`, because
  IANA names leave out many cities). Unknown values fall back to Mariatta's
  timezone with a notice
- Without JavaScript the field is a plain text input with a Show button, and
  the page defaults to Mariatta's timezone
- **Day cards are the viewer's calendar days.** Slots, appointments and the
  day label are grouped by date in the viewer's timezone
  (`recommend_week(..., display_tz)`). A viewer's day can hold parts of two
  of Mariatta's working days, so a day's business minutes are measured over
  that day's actual 24 hours
- **Classify** slots (business / extended / sacred) in Mariatta's TZ. The
  viewer's timezone never changes which slots exist, only how they are
  grouped and displayed
- Always display a `Mariatta is in America/Vancouver` label, plus how far the
  viewer's timezone is from it ("9 hours ahead of Mariatta")
- The JSON and MCP endpoints are unchanged: they return ISO 8601 datetimes
  with offsets
- The page is rate limited per IP with `AVAILABILITY_API_RATE_LIMIT`, the
  same limit as the JSON endpoints, because each timezone offset fetches its
  own 14-day range from Google

### Day-level recommendations (summary view)

A second pure function alongside `compute_availability`:

```python
def score_day(day, slots_for_day, busy_for_day, profile, display_tz=None) -> DayRecommendation: ...
def recommend_week(result, busy_blocks, profile, start, end, display_tz=None) -> {"days": [...], "best": ...}
```

Each day gets a qualitative label from the business-hours free-ratio:

| free_ratio | internal label     | display headline    |
|------------|--------------------|---------------------|
| == 0       | `fully_booked`     | "Unavailable"       |
| 0 – 0.2    | `unlikely`         | "Unlikely"          |
| 0.2 – 0.5  | `tight`            | "Tight but possible"|
| 0.5 – 0.9  | `likely_available` | "Likely available"  |
| >= 0.9     | `wide_open`        | "Available"         |

Each card shows meeting count ("0 other meetings" / "3 other meetings")
rather than free-minute arithmetic — that's noise to an asker. Each day
also gets a `best_window` — the longest contiguous free stretch —
surfaced as "Best window: 10:00–12:30" on the card.

`recommend_week` picks a suggested day by `(label_rank, free_minutes)`, so
the UI can headline "Tuesday looks best".

The week grid supports `?view=summary` (day cards) and `?view=detail`
(30-min slot grid). Summary is the default once calendar data lands;
detail remains one click away. Pre-Stage-4, every day labels as
`wide_open` (no `busy_blocks` yet) — honest but uniform.

### Extended-hours UX (option 1: exhaustion-based)

When the visible week returns fewer than `extended_reveal_threshold` free
business slots, show a `Need a different time?` button. Clicking re-requests
`slots.json` with `include_extended=true`. Extended-band cells render with a
distinct style (lighter green + small glyph) so askers self-filter.

MCP mirrors this exactly: `list_free_slots(..., include_extended=False)` is
the default. Agents should only pass `True` when their user has a stated
reason (urgency, conflicting timezone, etc).

### OAuth scope

- Phase 1-2: `calendar.readonly`
- Phase 3: add `calendar.events` on a dedicated bookings calendar only
  (separate re-auth, narrower blast radius)

### Dependencies to add

```
google-auth
google-auth-oauthlib
google-api-python-client
mcp                       # Python MCP SDK
cryptography              # refresh-token encryption (likely already transitive)
```

Phase 3 adds `stripe`.

---

## Phasing

**Phase 1 — read-only MVP**
OAuth (one account) · calendar selection · profile admin · week grid · slot
endpoint · check-a-time · exhaustion-based extended reveal · caching.

**Phase 2 — multi-account + MCP**
N Google accounts · MCP server at `/mcp/` · tool definitions · (optional)
list on the MCP Registry.

**Phase 3 — paid booking**
Stripe Checkout · `BookingProduct`/`BookingPayment`/`Booking` · write-scope
OAuth on dedicated calendar · confirmation emails · comp codes.

**Phase 4 — polish**
Google push notifications → cache invalidation · webhook refreshes · booking
analytics · multiple availability profiles.

---

## Open questions — fill in before phase 1 coding

These shape data and UX from day one; everything else can default.

- [ ] URL: `<current-host>/availability/` or a subdomain?
- [ ] Fully public or unguessable-URL gated?
- [ ] **Business hours** per weekday (e.g. `Mon–Fri 9:00–17:00`)?
- [ ] **Extended hours** per weekday (e.g. `Mon–Fri 7:00–9:00, 17:00–20:00`)?
- [ ] **Sacred time** rules (weekends off entirely? any other carve-outs)?
- [ ] **Exhaustion threshold `N`**: how many business slots in visible week
      before the extended-hours affordance appears?
- [ ] **Min notice**: hours between "now" and the earliest bookable slot?
- [ ] **Max horizon**: how many days out can a visitor check?
- [ ] **Default slot duration**: 30 or 60 minutes?
- [ ] Initial Google accounts to connect (labels): ____
- [ ] Cache backend available in deployment: Redis? locmem?
- [ ] MCP transport public (anonymous) or token-gated?
- [ ] Phase 2 stretch: list on the [MCP Registry](https://github.com/mcp)?

---

## Sensible defaults (if not otherwise specified)

- Timezone: `America/Vancouver`
- Business hours: Mon–Fri 09:00–17:00
- Extended hours: Mon–Fri 08:00–09:00 + 17:00–19:00
- Sacred: Sat + Sun entirely
- Exhaustion threshold: 4 free business slots in visible week
- Min notice: 12 hours
- Max horizon: 21 days
- Default slot: 30 minutes
- Cache TTL: 5 minutes

---

## References

- [Google Calendar `freeBusy.query`](https://developers.google.com/calendar/api/v3/reference/freebusy/query)
- [Google API Python Client](https://github.com/googleapis/google-api-python-client)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP streamable HTTP transport](https://spec.modelcontextprotocol.io)
- [MCP Registry](https://github.com/mcp)
- [Stripe Checkout](https://stripe.com/docs/payments/checkout) — phase 3
