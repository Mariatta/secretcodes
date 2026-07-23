"""Celery application.

Delivery *state* lives in Postgres (``Publication.state`` /
``scheduled_for`` / ``next_attempt_at``), not in the broker. Celery is only
the fan-out: beat ticks every minute, the dispatcher claims due rows, and one
task per claimed row does the HTTP call. Nothing is queued days ahead, so a
broker flush loses at most one minute of work.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "secretcodes.settings")

app = Celery("secretcodes")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
