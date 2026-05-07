"""Access control for the surveys app — mirrors expenses.permissions.

Two app-level permissions:

- ``surveys.access_surveys`` — required for any creator-side surface.
  Held by both owners and invited collaborators.
- ``surveys.create_surveys`` — required to start a brand-new survey.
  Held only by owners; invited collaborators can edit the surveys
  they were invited to but cannot create their own.

Per-survey access is the union of (owner) ∪ (collaborator). Use
``can_access_survey`` for survey-scoped views.

Public surfaces (the respondent form and thank-you page) intentionally
do **not** require any permission — anonymous respondents are the
target audience.
"""

ACCESS_SURVEYS_CODENAME = "access_surveys"
ACCESS_SURVEYS_PERM = f"surveys.{ACCESS_SURVEYS_CODENAME}"
CREATE_SURVEYS_CODENAME = "create_surveys"
CREATE_SURVEYS_PERM = f"surveys.{CREATE_SURVEYS_CODENAME}"

SURVEYS_USER_GROUP = "Surveys User"
SURVEY_COLLABORATOR_GROUP = "Survey Collaborator"


def is_surveys_user(user):
    """True if ``user`` is authenticated and may use the surveys creator side."""
    return user.is_authenticated and user.has_perm(ACCESS_SURVEYS_PERM)


def can_create_surveys(user):
    """True if ``user`` may start a brand-new survey (vs. only edit invited ones)."""
    return user.is_authenticated and user.has_perm(CREATE_SURVEYS_PERM)


def can_access_survey(user, survey) -> bool:
    """True if ``user`` is the survey's owner OR a collaborator on it.

    Superusers always pass. Caller is responsible for also checking
    ``is_surveys_user`` if they want to gate at the app level.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if survey.owner_id == user.id:
        return True
    return survey.collaborators.filter(user=user).exists()
