# Screencasts

Records walkthrough videos of Secret Codes, adapted from the pyladiescon-portal
and Platform1902 screencast scripts.

| Video | What it shows | Script |
|---|---|---|
| `expenses-restaurant-bill-desktop.mp4` | Six friends split a restaurant bill: starting on the newly created event (sign-in and creating it are cut), add five people by name, log the dinner split by item with shared appetizers, tax and a tip after tax, then the ledger and who owes the payer | `rec-restaurant-bill.js` |

The scripts drive the real site in a headless browser (Playwright) against a
throwaway database, and draw a cursor, click ripples and a caption for each
step into the video. The MP4s are written to `scripts/screencasts/out/videos/`.

## What you need

- Docker with the compose Postgres running: `docker compose up -d postgres`.
  Django runs in a one-off `web` container, with the checkout these scripts
  are in mounted as `/code`, so a worktree records its own code.
- Node.js and `ffmpeg` on the host.
- A Chromium for Playwright: `npx playwright install chromium` in this folder,
  or point `PLAYWRIGHT_CHROME` at an existing Chrome binary.

## Run it

From the repository root:

```
scripts/screencasts/run.sh --setup        # once: create, migrate and seed the throwaway database
scripts/screencasts/run.sh                # record every take
scripts/screencasts/run.sh restaurant     # or one take
SIZES="desktop mobile" scripts/screencasts/run.sh restaurant   # also at phone width
```

`--setup` creates an empty `secretcodes_screencasts` database (it does not copy
your development data), migrates it, runs `seed.py`, then snapshots it. Every
take restores that snapshot and starts a server on port 8004 in a container
named `secretcodes-screencast`, so a take can be re-run. Because every take
drops and recreates its database, the scripts read `SCREENCAST_DATABASE_URL`,
never `DATABASE_URL`, and `db.py` refuses any database whose name does not end
in `_screencasts`. Nothing touches your development database or dev server.

`seed.py` creates the account the scripts sign in with (`maya`), in the
Expenses User and Expense Manager groups, and deletes any events an earlier
take left on it.

Settings, all optional environment variables:

| Variable | Default | |
|---|---|---|
| `PORT` | `8004` | Port for the recording server. |
| `SCREENCAST_DATABASE_URL` | compose Postgres, `secretcodes_screencasts` | The throwaway database, as seen from the container. The name must end in `_screencasts`. |
| `SIZES` | `desktop` | Which sizes to record: `desktop`, `mobile`, or both. |
| `PLAYWRIGHT_CHROME` | Playwright's own | Path to a Chrome binary. |
| `VIEWPORT_WIDTH`, `VIEWPORT_HEIGHT` | `1024`, `720` | Desktop viewport. The video is the viewport's size. |
| `MOBILE_WIDTH`, `MOBILE_HEIGHT` | `390`, `760` | Phone viewport. |
| `SAMPLE_USERNAME`, `SAMPLE_PASSWORD`, `SAMPLE_FIRST_NAME` | `maya`, `screencast123`, `Maya` | The seeded account. |

## Adding a take

Copy `rec-restaurant-bill.js`. `lib.js` gives you `login`, `click`, `type`,
`choose` (a select by option label), `scrollToTop`, `caption` and `finish`.
Add the take name to the `case` in `run.sh`. A script that writes a number of
seconds to `<out dir>/trim.txt` has the video start there.

## When a script fails

Each step waits for its element and stops with the selector it could not find.
Open the page in a browser, find what the label or field is called now, and
update that line. The server log of each take is `out/<take>.server.log`.
To debug any script on a fresh database and server:
`SCRIPT=rec-restaurant-bill.js scripts/screencasts/run.sh script`.
`out/` holds the raw recordings and can be deleted freely.
