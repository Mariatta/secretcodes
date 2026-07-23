"""Project package.

Importing the Celery app here is what makes ``@shared_task`` bind to it when
Django starts, whether the entrypoint is gunicorn, a worker, or a test run.
"""

from .celery import app as celery_app

__all__ = ["celery_app"]
