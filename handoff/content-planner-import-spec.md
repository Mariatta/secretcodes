# Content planner — create-from-chat JSON spec

Paste this into your AI assistant's chat so it produces JSON the **Import JSON**
form (`/content/<board>/campaigns/new-from-chat/`) accepts.

## Instruction to give the AI assistant

> Output the campaign as a single JSON object with this shape. Only use the
> fields listed. Use `anchor_offset_days` when the campaign has an `event_date`,
> otherwise use `scheduled_at`. Don't include ids or statuses — every post is
> imported as a draft.

## Schema

```jsonc
{
  "campaign": {
    "name": "string",                 // required
    "event_date": "YYYY-MM-DD",        // optional; set ⇒ event-anchored campaign
    "tags": ["string", ...],           // optional; created on the board if new
    "narrative_notes": "string",       // optional
    "source_url": "https://...",       // optional; link to the planning chat/doc
    "hashtags": "#PyLadiesCon #Python" // optional; default hashtags for social posts
  },
  "posts": [
    {
      "title": "string",               // required — internal label
      "channel": "blog",               // required — see channels below

      // Scheduling — choose ONE style per post:
      // (a) event-anchored (only when campaign.event_date is set):
      "anchor_offset_days": -90,       // days relative to event_date (negative = before)
      "time_of_day": "HH:MM",          // optional, 24h; defaults to 09:00
      // (b) absolute date/time:
      "scheduled_at": "YYYY-MM-DDTHH:MM:SS",  // no offset ⇒ interpreted in the board's timezone

      "is_all_day": true,              // optional; default true for blog/newsletter, else false
      "body_snippet": "string",        // optional; full text for socials, subject+preview for blog/newsletter
      "expected_asset": "hero image\nsquare graphic",  // optional; one expected asset per line
      "hashtags": "#extra",            // optional; added to the campaign's, used on social posts
      "notes": "string"                // optional
    }
  ]
}
```

## Channels

`blog`, `mastodon`, `linkedin`, `x`, `instagram`, `newsletter`, `podcast`,
`talk`, `other`.

## What the importer ignores

`id`, `slug`, `status`, `published_url`, `created_by`, timestamps, and asset
file contents. Statuses are not honored — **every imported post starts as a
draft**. Asset files must be uploaded in the app afterwards.

## Example — event-anchored newsletter series

```json
{
  "campaign": {
    "name": "PyCon 2026 attendee comms",
    "event_date": "2026-05-15",
    "tags": ["pycon", "attendee-comms"],
    "narrative_notes": "Attendee email series anchored to the conference dates."
  },
  "posts": [
    {
      "title": "Save the date",
      "channel": "newsletter",
      "anchor_offset_days": -90,
      "time_of_day": "09:00",
      "body_snippet": "Subject: Save the date for PyCon US 2026!\n\nHi everyone..."
    },
    {
      "title": "Travel reminders",
      "channel": "newsletter",
      "anchor_offset_days": -14,
      "expected_asset": "venue map"
    }
  ]
}
```

## Example — non-event blog series with absolute dates

```json
{
  "campaign": {
    "name": "Conference-organizing confession series",
    "tags": ["advocacy", "two-part series"]
  },
  "posts": [
    {
      "title": "Confession part 1 — blog",
      "channel": "blog",
      "scheduled_at": "2026-05-30T00:00:00",
      "is_all_day": true,
      "expected_asset": "hero image\nquote card"
    },
    {
      "title": "Confession part 1 — announce",
      "channel": "mastodon",
      "scheduled_at": "2026-05-30T09:00:00",
      "is_all_day": false
    }
  ]
}
```
