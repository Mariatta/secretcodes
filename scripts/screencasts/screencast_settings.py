"""Settings for the screencast server: the dev settings, with mail kept local.

Invitations print to the server log instead of going anywhere.
"""

from secretcodes.settings import *  # noqa: F401,F403

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
