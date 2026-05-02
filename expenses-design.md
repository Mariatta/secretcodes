# Expenses Portal — Design Brief

A new feature for [`secretcodes`](https://github.com/mariatta/secretcodes):
a shared expense tracker for trips and group events. Participants log what
they paid, who shared the cost, and the system tells everyone who's owed
what. Built for friends/family scope — convenience over accounting rigor.

## Goals

- Create an **event** (trip, gathering) and add participants
- Each participant logs expenses — amount, payer, who shared it, optional
  receipt and quote/estimate
- Per-share **reimbursement tracking** so partial settlements are visible
- **Net settlement** view — collapse N expenses into the minimum set of
  Venmo-style transfers
- **Ledger** view — chronological log of every expense in the event
- **Budget vs Actual** view — for the subset of expenses where a quote/estimate
  was recorded
- App-level **access restriction** so an expenses-only invitee never sees the
  rest of the site
- **Invitation flow** so the event owner can grant access by email without
  creating users by hand

## Non-goals

- Multi-currency settlement (all balances live in one base currency per event)
- Per-day or per-category budget rollups (single placeholder expense, not a
  separate budget-line model)
- Splitwise-grade splitting (equal-only in v1, no weighted/percentage/by-item)
- Multi-payer expenses (use two expenses instead)
- Real-time FX feeds, card-statement reconciliation, OCR receipt parsing
- A separate cash-kitty / pooled-fund model

---

## Architecture

### Django app layout

New app `expenses/` alongside `availability/` and `qrcode_manager/`.

```
secretcodes/
├── qrcode_manager/            # existing
├── availability/              # existing
├── expenses/                  # NEW
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   ├── urls.py
│   ├── admin.py
│   ├── permissions.py         # group + event-membership checks
│   ├── services/
│   │   ├── settlement.py      # net-balance computation, pure
│   │   └── invitations.py     # allauth + django-invitations glue
│   └── templates/expenses/
├── storage_backend/           # existing — receipts encrypted at rest
└── secretcodes/               # existing project settings
```

### Data model

**`Category`** — globally shared, admin-managed
- `name` (unique)
- (later: `icon`, `color`, `is_active`)

**`Event`** — a trip or gathering
- `name`
- `owner` → FK `User`
- `start_date`, `end_date` (nullable)
- `base_currency` (3-char code, e.g. `"USD"`) — locked at creation, admin
  override only
- `fx_rates` — JSON, e.g. `{"JPY": 0.0067, "EUR": 1.08}`. Base currency is
  implicit `1.0`. An expense in a currency not present in this dict is
  rejected at form level.
- `notes` (free text)
- `is_archived` — `bool`, default `False`. Event list filters to active by
  default, with a "Show archived" toggle. Soft-delete only — no hard
  deletion, so balances stay reconstructable.
- timestamps

**`Participant`** — a user's membership in an event
- `event` → FK `Event`
- `user` → FK `User` (nullable until invitation accepted)
- `invited_email` (used pre-acceptance)
- `display_name` — free-form. On save, defaults to `User.first_name` if
  blank and `user` is set. Same person can have different names across
  events ("Mom" in a family trip, "Mariatta" in a work trip).
- `role` (`owner` / `member`)
- `joined_at`

Used for both access checks (`event.participants.filter(user=...)`) and as
the "who's in the split" pool for expenses.

**`Expense`** — three-state row
- `event` → FK `Event`
- `description`
- `category` → FK `Category` (`on_delete=PROTECT`)
- `estimated_amount` — `Decimal`, nullable (in event's base currency — quotes
  are pre-conversion business and the user enters the base equivalent)
- `original_amount` — `Decimal`, nullable
- `original_currency` — 3-char, nullable
- `base_amount` — `Decimal`, nullable, computed at save:
  `original_amount * event.fx_rates[original_currency]`
- `payer` → FK `Participant`, nullable
- `paid_at` — `Date`, nullable
- `receipt` — encrypted file field (reuse `availability/encryption.py` pattern)
- timestamps

State table:

| State                    | `estimated_amount` | `paid_at`    |
|--------------------------|--------------------|--------------|
| Planned                  | set                | null         |
| Quoted then paid         | set                | set          |
| Paid only (no quote)     | null               | set          |

- Ledger filter: `paid_at IS NOT NULL`
- Budget vs Actual filter: `estimated_amount IS NOT NULL`
- `ExpenseShare` rows are not created until `paid_at` is set

**`ExpenseShare`** — one row per participant in the split
- `expense` → FK `Expense`
- `participant` → FK `Participant`
- `share_amount` — `Decimal`, in event base currency
- `reimbursed` — `bool`, default `False`
- timestamps

Created when an expense transitions out of "planned" state. Storage holds
*resolved* amounts only — split mode is a UI-side computation that is not
persisted.

### Splitting

Equal split only. The form lists all event participants as checkboxes,
default all-checked, and on save:

1. Compute `share = round(base_amount / N, 2)` where N is the number of
   checked participants.
2. Create `N` `ExpenseShare` rows.
3. **Rounding**: any cent-level difference between `sum(shares)` and
   `base_amount` is absorbed by the payer's share. Use `decimal.Decimal`
   with `ROUND_HALF_UP`. Never floats for money.

The payer can be unchecked from the share list (e.g. Mariatta paid for
Bob's birthday dinner — payer = Mariatta, shares = Bob).

### Settlement (net balances)

Pure function in `services/settlement.py`:

```python
def compute_net_balances(event: Event) -> dict[Participant, Decimal]:
    """Positive = owed money. Negative = owes money."""
    ...

def suggest_settlements(
    balances: dict[Participant, Decimal],
) -> list[Settlement]:
    """Greedy pairing: largest creditor ↔ largest debtor, transfer min, repeat."""
    ...
```

No I/O. Trivially unit-testable. Reads only `ExpenseShare` rows where
`reimbursed=False`. Settlement suggestions are a recommendation — the UI
provides a **bulk "settle up" action** that flips multiple `reimbursed` flags
in one transaction.

No `Settlement` / `Payment` model in v1. The flag plus the bulk action is
enough; payment receipts are out of band.

### Views

**Per-event**
- `GET  /expenses/events/<id>/`           — Overview: net balances + suggested settlements + key totals
- `GET  /expenses/events/<id>/ledger/`    — chronological list of all paid expenses
- `GET  /expenses/events/<id>/budget/`    — Budget vs Actual: rows where `estimated_amount IS NOT NULL`
- `GET  /expenses/events/<id>/expenses/<eid>/` — expense detail + receipt
- `POST /expenses/events/<id>/settle/`    — bulk-flip reimbursed flags for a payer/payee pair
- `POST /expenses/events/<id>/expenses/`  — new expense
- `POST /expenses/events/<id>/invite/`    — invite by email

**App-level**
- `GET  /expenses/`                       — list of events the user can see
- `GET  /accept/<token>/`                 — invitation acceptance (django-invitations)

**Admin** (Django admin, login-gated)
- `Event`, `Participant`, `Expense`, `ExpenseShare`, `Category` standard ModelAdmins
- Per-event admin action: "recompute base amounts" (after `fx_rates` edit)

### Ledger row shape

```
Date · Description · Paid by · Category · Amount (orig→base) · Shared by · Your share · Reimbursed
```

- "Your share" in base currency.
- Reimbursed rows: greyed via CSS opacity, still clickable.
- Receipt thumbnail only on detail click (reduces row weight + decryption cost).
- Filter default: show all expenses (not only the viewer's).

### Budget vs Actual row shape

```
Description     Quoted    Paid       Variance
─────────────────────────────────────────────
Tour            $2,000    $2,200     +$200
Hotel           $1,500    $1,500     $0
Meals (planned) $2,800    —          —
```

Variance = signed dollar amount (`paid − quoted`), green if under, red if over.
Planned rows show `—` for paid and variance until the expense is filled in.

### Access control

Two distinct layers — never conflated:

**App-level access** — Django group `expenses_users`. A `LoginRequiredMixin`
plus `PermissionRequiredMixin` (or simple decorator checking
`request.user.groups.filter(name='expenses_users').exists()`) gates every
view in the app. Users without the group see `403`.

**Event-level access** — row-level. Every event view checks
`event.participants.filter(user=request.user).exists()` before rendering.
Not expressed via Django permissions (it doesn't do row-level natively).

Combined effect:
- An "expenses-only" invitee has the `expenses_users` group and one
  `Participant` row. They can see exactly one event, and no other apps.
- The site's existing nav must hide the expenses link from users without
  the group, and vice-versa for other apps.

### Invitations (as built)

We **did not** end up using `django-invitations` — version 2.1.0 (last PyPI
release) breaks against `django-allauth 65.x` because the adapter API
changed. Instead we rolled a minimal in-app invitation flow:

**Model** — `ExpenseInvitation` in `expenses.models`: `event` FK, `email`,
`display_name`, `inviter`, random `key`, `sent_at`, `accepted_at`. Plain
`BaseModel`, no library inheritance.

**Email** — `expenses/services/invitations.py` renders a plain-text template
and dispatches via `django.core.mail.send_mail`. The compose stack already
runs a `maildev` container at port 1025 for local testing.

**Accept flow** — `/expenses/accept/<key>/`:
1. Look up invitation; reject if accepted or expired
   (`EXPENSES_INVITATION_EXPIRY_DAYS = 14`).
2. Branch on `User.objects.filter(email=invite.email).exists()`:
   - Existing user, anonymous → `redirect_to_login` with a flash message.
   - Existing user, logged in as them → confirm-and-accept page.
   - Existing user, logged in as someone else → 403.
   - No user yet → render an `AcceptInviteSignupForm` (username + password +
     optional first name); on submit, create the User, log in via
     `ModelBackend`, accept.
3. Acceptance: add user to `expenses_users` group, link the placeholder
   `Participant` row (matched on `invited_email`), stamp `accepted_at`.

Allauth's `is_open_for_signup` stays `False` — the invite signup path
bypasses allauth and uses `User.objects.create_user` directly.

### Receipts

- File field uses the existing storage backend.
- Encrypted at rest using the same `cryptography.Fernet`-style helper that
  `availability/encryption.py` uses for refresh tokens. Symmetric key in
  `settings.SECRET_KEY`-derived envelope, never logged.
- Decryption only at view-render for the participant who can see the event.
- File names randomized at upload — never trust user-supplied filename.

### Dependencies (as built)

No new third-party packages were added. The original plan to use
`django-invitations` and `py-moneyed` was abandoned:
- `django-invitations` is incompatible with the project's `django-allauth`
  version; we wrote our own minimal invitation flow instead (~80 lines).
- `py-moneyed` was never needed — `django.db.models.DecimalField` +
  `decimal.Decimal` handle money fine for our scope.

`cryptography` (already present via availability) powers the receipt
encryption.

---

## Phasing & build status

**Phase 1 — thin slice** · **✅ shipped**
`Event` CRUD · `Participant` (manual via admin) · `Category` admin · `Expense`
create/edit/delete with equal-split form · ledger view · overview with net
settlement · `expenses_users` group + view gating.

**Phase 2 — receipts** · **✅ shipped (estimates skipped)**
Encrypted receipt uploads via custom `EncryptedFileSystemStorage` (Fernet,
same key as `availability/encryption.py`) · decrypt-on-serve view ·
paperclip link in ledger · download link in admin.
**Estimates not built** — deferred (see `expenses-ideas.md`).

**Phase 3 — invitations** · **✅ shipped, custom implementation**
Invite-by-email form (event-owner only) · accept-invite flow that branches
on whether a User exists for the email: existing user logs in to accept,
new email gets a username + password signup form. On accept, user is added
to `expenses_users` and the placeholder `Participant` row is linked.

**Phase 4 — polish** · **✅ shipped**
Bulk settle-up (mark-as-paid for a payer/payee pair, with confirmation page) ·
category filter on ledger · CSV export (one row per share) ·
admin recompute-base-amounts action on `Event`.

---

## Settled defaults

- URL prefix: `/expenses/`
- `base_currency`: `"USD"`
- Categories seeded via data migration: `Food`, `Lodging`, `Transit`,
  `Activities`, `Shopping`, `Other`
- Rounding: `Decimal` with `ROUND_HALF_UP`, payer absorbs cent diff
- Ledger filter: show all expenses (not just viewer's)
- Receipt cap: 10 MB, types `image/jpeg`, `image/png`, `image/heic`,
  `application/pdf` (HEIC matters — iPhone receipts default to it)
- Archive: `Event.is_archived` flag, soft-delete only, no auto-archive
- Invitations: event owner only sends; participants without owner role
  don't see the invite UI
- Settlement view: net + suggested transfers, no payment-history table

---

## Test coverage

100% line coverage on the `expenses` app. The Makefile's `test` target
already enforces this via `--cov-fail-under=100`. Tests live in
`tests/test_expenses_*.py` (settlement, form, view, invitations, receipts,
settle-up, models, admin).

---

## Implementation deviations from the original spec

Things that ended up different from the early sections of this doc:

- **Custom invitation flow** instead of `django-invitations` (see "Invitations
  (as built)" above).
- **No `py-moneyed` dependency** — plain `DecimalField` + `Decimal` is enough.
- **Edit and delete are creator-only** (not in the original spec). Anyone in
  the event can log a new expense, but only the creator (or a superuser) can
  edit or delete it. Internal helper: `expenses.views._can_modify`.
- **Public landing page** at `/expenses/`. Anonymous and unauthorized users
  see a brand-styled hero ("Friends and family only, for now"); only group
  members see the event list. The Expenses link is in the main nav and
  footer for everyone.
- **Event cards with stats** — the event list renders cards (not a list-group),
  each showing participant count and total-spent prominently.
- **`created_by` field on Expense** — added to support creator-only edit/delete.
- **Estimates not implemented** — `estimated_amount`, planned-state expenses,
  and Budget vs Actual view are deferred. Tracked in `expenses-ideas.md`.

---

## References

- [django-allauth](https://docs.allauth.org/)
- [Splitwise debt-simplification overview](https://medium.com/@mithunmk93/algorithm-behind-splitwise-balancing-debts-787c6da9d553)
  — for the greedy net-settlement approach
- [Python `decimal` module](https://docs.python.org/3/library/decimal.html)
  — money math, never floats
- [`cryptography.Fernet`](https://cryptography.io/en/latest/fernet/)
  — receipt and refresh-token encryption