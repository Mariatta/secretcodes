#!/usr/bin/env sh
set -e

# One image, three roles. CONTAINER_ROLE selects what this container does, so
# the web app, the Celery worker, and beat all run the same image and differ
# only by an env var. Defaults to "web", so any host that doesn't set it (incl.
# prod today) behaves exactly as before.
ROLE="${CONTAINER_ROLE:-web}"

# Only the web role migrates: three containers racing `migrate` on deploy is
# asking for trouble, and worker/beat come up green once web has run it. If
# beat starts first it crash-loops on the missing django_celery_beat tables
# and App Service restarts it until web finishes — noisy but self-healing.
run_web() {
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
}

# App Service pings the container's port on startup and restarts it if nothing
# answers. A Celery process binds no port, so a tiny 200-responder runs beside
# it purely to satisfy that probe (see secretcodes/healthping.py). Harmless
# off-Azure, where nothing pings.
run_celery() {
    python /code/secretcodes/healthping.py &
    exec "$@"
}

case "$ROLE" in
    web)
        run_web
        ;;
    worker)
        echo "==> Starting Celery worker"
        run_celery celery -A secretcodes worker -l info
        ;;
    beat)
        echo "==> Starting Celery beat"
        run_celery celery -A secretcodes beat -l info
        ;;
    *)
        echo "Unknown CONTAINER_ROLE '${ROLE}' (expected web, worker, or beat)" >&2
        exit 1
        ;;
esac
