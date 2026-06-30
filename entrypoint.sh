#!/usr/bin/env sh
set -e

echo "==> Running migrations"
python manage.py migrate --noinput

echo "==> Collecting static files"
python manage.py collectstatic --noinput

# App Service injects PORT (set WEBSITES_PORT=8000 in app settings so the
# platform routes correctly). Falls back to 8000 locally.
PORT="${PORT:-8000}"

echo "==> Starting gunicorn on :${PORT}"
exec gunicorn secretcodes.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers 3 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -