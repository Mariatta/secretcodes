"""Access control for the surveys app — mirrors expenses.permissions.

App-level: user must hold the ``surveys.access_surveys`` permission
(custom Meta permission on ``Survey``). Gated via Django's
``user_passes_test`` against ``is_surveys_user``.

Public surfaces (the respondent form and thank-you page) intentionally
do **not** require this permission — anonymous respondents are the
target audience.
"""

ACCESS_SURVEYS_CODENAME = "access_surveys"
ACCESS_SURVEYS_PERM = f"surveys.{ACCESS_SURVEYS_CODENAME}"
SURVEYS_USER_GROUP = "Surveys User"


def is_surveys_user(user):
    """True if ``user`` is authenticated and may use the surveys creator side."""
    return user.is_authenticated and user.has_perm(ACCESS_SURVEYS_PERM)
