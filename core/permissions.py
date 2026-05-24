"""App-level access gating.

Django best practice: check capability with ``user.has_perm()``, manage
assignment with Groups. ``has_perm`` automatically traverses direct
user permissions, group-inherited permissions, and superuser status —
one call, one truth.

Convention this module enforces:

* **Permission**: each app declares ``access_<app_label>`` on one of
  its models' ``Meta.permissions`` (e.g. ``surveys.access_surveys``,
  ``expenses.access_expenses``). This is what every gate checks.

* **Group**: a per-app group named ``<app_label>_users`` carries that
  permission. Adding a user to the group is the standard way to grant
  access; ``has_perm`` sees it through the group.

The permission must already exist (declared via ``Meta.permissions`` +
``migrate``). ``grant_app_access`` looks it up and will raise
``Permission.DoesNotExist`` if the calling app forgot to declare it —
better a loud failure at setup time than a silent group with no perm.
"""

from django.contrib.auth.models import Group, Permission


def _group_name(app_label: str) -> str:
    return f"{app_label}_users"


def _permission_codename(app_label: str) -> str:
    return f"access_{app_label}"


def _permission_string(app_label: str) -> str:
    # Once we're on Django 6.0, replace this manual construction with
    # `perm.user_perm_str` (new in 6.0) for the call sites that already
    # have a Permission instance in hand.
    return f"{app_label}.{_permission_codename(app_label)}"


def has_app_access(user, app_label: str) -> bool:
    """True if ``user`` may use the named app.

    Delegates to ``user.has_perm()`` — superusers short-circuit to True,
    anonymous users to False, group-inherited permissions are honored
    transparently. The permission checked is ``<app_label>.access_<app_label>``.
    """
    return user.has_perm(_permission_string(app_label))


def grant_app_access(user, app_label: str) -> None:
    """Add ``user`` to ``<app_label>_users``; ensure it carries the access perm.

    The permission must be declared on one of the app's models'
    ``Meta.permissions`` — otherwise ``Permission.DoesNotExist``
    surfaces, which is the right error: the app's setup is incomplete.
    """
    perm = Permission.objects.get(
        codename=_permission_codename(app_label),
        content_type__app_label=app_label,
    )
    group, _ = Group.objects.get_or_create(name=_group_name(app_label))
    group.permissions.add(perm)
    user.groups.add(group)


def revoke_app_access(user, app_label: str) -> None:
    """Remove ``user`` from ``<app_label>_users``. No-op if not a member."""
    group = Group.objects.filter(name=_group_name(app_label)).first()
    if group:
        user.groups.remove(group)
