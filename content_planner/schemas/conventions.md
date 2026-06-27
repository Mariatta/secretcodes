# Content planner — JSON conventions

How to produce a campaign JSON for the **create-from-chat** import. The machine
contract is `create_from_chat.schema.json` (same dir); this is the *why* behind
it. Both are generated/kept in sync with the models — don't guess field names.

## Shape

```json
{
  "campaign": { "name": "..." },
  "posts": [ { "title": "...", "channel": "..." } ]
}
```

Top level needs `campaign` (object) and `posts` (array). A campaign needs a
`name`; each post needs a `title` and a `channel`. Everything else is optional.

## Channels

`channel` must be one of (read from the model, so this list is authoritative in
the schema's `enum`): `blog`, `mastodon`, `linkedin`, `x`, `instagram`,
`newsletter`, `podcast`, `talk`, `other`.

Social channels (`mastodon`, `linkedin`, `x`, `instagram`) are where hashtags
get appended when copying.

## Status lifecycle (and why you don't set it)

Posts move through `drafting → ready → uploaded → scheduled → published`, plus
`archived` / `cancelled`. **The import ignores any `status` you send — every
imported post starts in `drafting`.** Status is something the human moves the
post through in the UI, not something the plan declares.

## Scheduling: two mutually exclusive ways

1. **Event-anchored.** Set `campaign.event_date` (ISO `YYYY-MM-DD`), then give
   each post an `anchor_offset_days` integer (negative = before the event) and
   optionally a `time_of_day` (`HH:MM`). The server computes the real datetime
   in the board's timezone. Use this for conference / meetup comms.
2. **Absolute.** Leave `event_date` unset and give a post a `scheduled_at` ISO
   datetime. A naive value (no offset) is interpreted in the board's timezone.

If a campaign has an `event_date` but a post has neither field, the post is left
unscheduled. `anchor_offset_days` is only honored when `event_date` is set.

## All-day

`is_all_day` defaults to `true` for `blog` and `newsletter`, `false` otherwise.
Set it explicitly to override.

## Hashtags

`campaign.hashtags` is the default set for the campaign's social posts;
`post.hashtags` adds extras for one post. Both are a single string, space- or
comma-separated, with or without the leading `#` (e.g. `"#PyLadiesCon Python"`).

## Assets

`expected_asset` is a single string listing the assets a post expects, **one per
line**. It's a planning checklist; the actual files are attached later in the UI.

## Slugs and ids — leave them out

Slugs and ids are server-generated and board-scoped. Don't invent them; any
`id`/`slug` you include is ignored (so an exported campaign re-imports cleanly).

## Ignored vs honored on import

- **Honored:** campaign `name`, `event_date`, `narrative_notes`, `source_url`,
  `hashtags`, `tags`; post `title`, `channel`, `scheduled_at`,
  `anchor_offset_days`, `time_of_day`, `is_all_day`, `body_snippet`,
  `expected_asset`, `hashtags`, `notes`.
- **Ignored:** `id`, `slug`, `status`, `created_by`, and any server-computed
  dates (`creation_date`, `modified_date`). Sending them is harmless.

See `examples/` for two complete, valid payloads.
