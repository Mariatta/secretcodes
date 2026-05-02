"""Two-layer access checks for the expenses app.

App-level: user must hold the `expenses.access_expenses` permission
(custom Meta permission on `Event`). Gated via Django's
`user_passes_test` against `is_expenses_user`.

Event-level: user must have a `Participant` row for the event. The
`event_participant_required` decorator stacks the app-level check on
top of the row-level one and 404s for non-participants.

Templates can use `{% if perms.expenses.access_expenses %}` directly —
the `auth` context processor exposes `perms` automatically.
"""

from functools import wraps

from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Event

ACCESS_EXPENSES_PERM = "expenses.access_expenses"


def is_expenses_user(user):
    """True if `user` is authenticated and may use the expenses app."""
    return user.is_authenticated and user.has_perm(ACCESS_EXPENSES_PERM)


def event_participant_required(view_func):
    """Gate per-event views: caller must be a Participant for that event.

    Stacks `user_passes_test(is_expenses_user)` (app-level access) with
    a row-level participant check. The event is loaded once here and
    passed through to the view as a kwarg.
    """

    @wraps(view_func)
    @user_passes_test(is_expenses_user)
    def _wrapped(request, event_id, *args, **kwargs):
        event = get_object_or_404(Event, pk=event_id)
        if request.user.is_superuser:
            return view_func(request, event=event, *args, **kwargs)
        is_participant = event.participants.filter(user=request.user).exists()
        if not is_participant:
            raise Http404("Event not found")
        return view_func(request, event=event, *args, **kwargs)

    return _wrapped
