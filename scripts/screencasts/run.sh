#!/bin/bash
# Record walkthrough videos of Secret Codes with Playwright.
#
#   scripts/screencasts/run.sh --setup        build the throwaway database (empty, migrated, seeded)
#   scripts/screencasts/run.sh                record every take
#   scripts/screencasts/run.sh restaurant     record one take
#
# See scripts/screencasts/README.md. Django runs in the compose `web` container
# (the checkout this script is in is mounted as /code); Playwright and ffmpeg run
# on the host. Settings come from the environment: PORT, SCREENCAST_DATABASE_URL,
# SIZES, PLAYWRIGHT_CHROME, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, SAMPLE_USERNAME,
# SAMPLE_PASSWORD, SAMPLE_FIRST_NAME.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$HERE/out"
VIDEOS="$OUT/videos"
PORT="${PORT:-8004}"
SERVER="secretcodes-screencast"

# Deliberately not DATABASE_URL: every take drops and recreates the database this
# points at, so only SCREENCAST_DATABASE_URL can steer it, and db.py refuses any
# name that does not end in _screencasts. The host is the compose service name.
SCREENCAST_DATABASE_URL="${SCREENCAST_DATABASE_URL:-postgresql://secretcodes:secretcodes@postgres:5432/secretcodes_screencasts}"
export BASE_URL="http://127.0.0.1:$PORT"
export SAMPLE_USERNAME="${SAMPLE_USERNAME:-maya}"
export SAMPLE_PASSWORD="${SAMPLE_PASSWORD:-screencast123}"
export SAMPLE_FIRST_NAME="${SAMPLE_FIRST_NAME:-Maya}"
# desktop, mobile, or both (space separated).
SIZES="${SIZES:-desktop}"

# Every Django command runs in a one-off web container on the screencast database.
# --no-deps: the compose Postgres must already be up (docker compose up -d postgres).
web() {
  (cd "$ROOT" && docker compose -p secretcodes run --rm --no-deps \
    -e DATABASE_URL="$SCREENCAST_DATABASE_URL" \
    -e DJANGO_SETTINGS_MODULE=screencast_settings \
    -e PYTHONPATH=/code/scripts/screencasts \
    -e SAMPLE_USERNAME -e SAMPLE_PASSWORD -e SAMPLE_FIRST_NAME \
    "$@" 2> >(grep -v 'level=warning' >&2))
}
db() { web web python scripts/screencasts/db.py "$@"; }

mkdir -p "$OUT" "$VIDEOS"
[ -d "$HERE/node_modules" ] || (cd "$HERE" && npm install)

if [ "${1:-}" = "--setup" ]; then
  shift
  db create
  web web python manage.py migrate -v0
  web -T web python manage.py shell < "$HERE/seed.py"
  db snapshot
  [ $# -eq 0 ] && exit 0
fi

stop_server() { docker rm -f "$SERVER" > /dev/null 2>&1 || true; }
trap stop_server EXIT

fresh_server() {
  stop_server
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t > /dev/null; then
    echo "port $PORT is already in use (an earlier recording server?); stop it or set PORT" >&2
    exit 1
  fi
  db restore
  web -d --name "$SERVER" -p "127.0.0.1:$PORT:$PORT" \
    web python manage.py runserver "0.0.0.0:$PORT" --noreload > /dev/null
  until curl -s -o /dev/null "$BASE_URL/accounts/login/"; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$SERVER" 2>/dev/null)" != "true" ]; then
      docker logs "$SERVER" >&2 || true
      exit 1
    fi
    sleep 1
  done
}

encode() { # <recording dir> <name>
  # A script may note where the interesting part starts (trim.txt); the video starts there.
  local start=0
  [ -f "$OUT/$1/trim.txt" ] && start="$(cat "$OUT/$1/trim.txt")"
  ffmpeg -v error -y -ss "$start" -i "$OUT/$1"/*.webm -c:v libx264 -crf 28 -preset slow -pix_fmt yuv420p \
    -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -movflags +faststart -an "$VIDEOS/$2.mp4"
  echo "wrote scripts/screencasts/out/videos/$2.mp4"
}

take() { # <script> <name> <size>
  local name="$2-$3"
  rm -rf "${OUT:?}/${name:?}"
  fresh_server
  if [ "$3" = "mobile" ]; then
    MOBILE=1 VIEWPORT_WIDTH="${MOBILE_WIDTH:-390}" VIEWPORT_HEIGHT="${MOBILE_HEIGHT:-760}" \
      node "$HERE/$1" "$OUT/$name"
  else
    node "$HERE/$1" "$OUT/$name"
  fi
  docker logs "$SERVER" > "$OUT/$name.server.log" 2>&1 || true
  encode "$name" "$name"
}

record() {
  case "$1" in
    restaurant)
      for size in $SIZES; do take rec-restaurant-bill.js expenses-restaurant-bill "$size"; done
      ;;
    script)
      # Debugging: run any script from this folder on a fresh database and server.
      fresh_server
      node "$HERE/${SCRIPT:?set SCRIPT to a file in scripts/screencasts}"
      ;;
    *) echo "unknown take: $1" >&2; exit 1 ;;
  esac
}

if [ $# -eq 0 ]; then set -- restaurant; fi
for t in "$@"; do record "$t"; done
