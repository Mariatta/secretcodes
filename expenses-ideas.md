# Expenses — running ideas / backlog

Things considered or noted in passing but deferred. The shipped design is in
`expenses-design.md`; this is the "come back to" pile.

---

## Phase 2 estimates (deferred)

The original Phase 2 had two halves: receipts (shipped) and estimates (not).

**What it would add**
- `Expense.estimated_amount` (nullable Decimal) — quote / forecast.
- "Three-state" expense rows: planned (estimate set, no payer/actual), quoted
  then paid (both set), paid only (no quote).
- Budget vs Actual view per event: list of every row with `estimated_amount IS
  NOT NULL`, showing quoted / paid / variance.

**Why we skipped it**
Friends-and-family scope. Most expenses are logged after they happen; quotes
are rare. Estimate was the most speculative piece in the brainstorm; revisit
if we feel the lack on a real trip.

**Sketch already in `expenses-design.md`**
The model section, the view, and the row shape are all already specced.

---

## Settle-up history / payment audit log

Currently the bulk-settle action flips `ExpenseShare.reimbursed` to True with
no audit row. You can't later answer "when did Bob pay Alice?" without the
modified_date on each share, which is fragile.

**Sketch**: a `Settlement(event, debtor, creditor, amount, settled_at, note)`
model. The settle-up view writes one row per bulk action and updates the
shares. A "Payment history" tab on the event overview lists them.

Low priority for now since the flag is enough day-to-day.

---

## Orphan receipt cleanup

The receipt storage at `MEDIA_ROOT/encrypted/receipts/<event_id>/<uuid>.<ext>`
can accumulate files no `Expense.receipt` references — caused by:
- Earlier bug where files were saved but the FileField didn't persist (fixed,
  but old debris remains)
- An expense being deleted before file cascades caught up (shouldn't happen
  with current cascade, but worth a sweep)

**Sketch**: a one-shot management command:
```
./manage.py clean_orphan_receipts [--dry-run]
```
List every file under `MEDIA_ROOT/encrypted/receipts/`, check if any
`Expense.receipt.name` matches, delete the unreferenced ones.

---

## HEIC inline preview for non-Safari browsers

iPhone receipts default to HEIC. The receipt-download view streams the right
content type (`image/heic`), but Chrome and Firefox can't render HEIC inline
and force a download. Safari can.

**Options**:
- Server-side convert HEIC → JPEG on upload (requires `pillow-heif`). Store
  both, serve JPEG inline, keep original encrypted.
- Client-side only — accept that non-Safari users download.

For friends/family scope, "you have to download it" is fine. Reconsider if it
becomes annoying.

---

## Multi-payer expenses / cash kitty

Both explicitly deferred during the brainstorm.

- **Multi-payer**: hotel charge of $400 split between two cards. Currently
  modeled as two separate expenses. Adding a second payer FK + amount-per-payer
  table is a bigger schema change.
- **Cash kitty**: everyone throws in $50 to a virtual pot, expenses paid from
  the pot. Useful for trips where one person handles cash. Modeling: a
  `Kitty` participant per event, contributions track who's paid in.

Neither is needed for the current use case.

---

## Quote in original currency

`estimated_amount` (when we build it) is currently specced as base-currency
only. Edge case: "the tour was quoted at €2000 but we paid in USD." Two ways
to capture:
- Add `estimated_currency` + `estimated_base_amount` (denormalized) — same
  shape as the actual amount fields. More schema, more honest data.
- Just enter the quote in base currency and accept the conversion is
  approximate at quote-time.

Probably not worth the complexity unless someone's quoted in a different
currency than they paid in.

---

## Email-verified signup-via-invite

The current accept-invite signup creates the user immediately on form submit
(no email verification). For friends/family this is fine — the invite link
itself proves email ownership. For broader use, we'd want allauth's
email-verification flow:
- User clicks invite → username + password
- Allauth sends a verification email
- User clicks verify → account active

Requires deeper allauth integration. Currently `is_open_for_signup` returns
`False` and we bypass allauth entirely; switching means flipping that behavior
without breaking the rest of the site.

---

## Smaller follow-ups (one-line each)

- **Expense detail page** — currently you click Edit to see all the info. A
  read-only detail view would let non-creators see receipt, full split, etc.
- **Event-level "settle everyone up" button** — flips every unreimbursed
  share in the event. Useful at the end of a trip.
- **Per-participant ledger view** — "show me only the expenses I paid for"
  or "expenses where I owe Alice."
- **Event archive UX** — currently `is_archived` is admin-only. An "Archive
  this event" button on the overview page would let owners self-serve.
- **Recurring expenses** — for monthly shared rent / utilities. Low priority
  for trip use case.
- **Notifications** — email / Signal poke when someone logs a new expense
  in your event. Probably noisy.
- **Multi-language** — copy is English-only. Django's i18n machinery is
  already loaded. Easy path if needed.
- **PWA / mobile install** — manifest + service worker so the site can be
  added to a phone's home screen. Nice for trip use.
- **Better thousands-separator on totals** — `humanize.intcomma` in
  templates would render `12,207.95` instead of `12207.95`. Requires adding
  `django.contrib.humanize` to `INSTALLED_APPS`.
