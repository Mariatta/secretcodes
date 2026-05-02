"""Two-layer access checks for the expenses app.

App-level: user must be in the `expenses_users` group.
Event-level: user must have a Participant row for the event.
Both must pass for any per-event view; only app-level for the index.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404

from .models import Event

EXPENSES_GROUP = "expenses_users"


def is_expenses_user(user):
    """True if `user` is authenticated and in the expenses group."""
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=EXPENSES_GROUP).exists()
    )


def expenses_user_required(view_func):
    """Gate any expenses view behind the `expenses_users` group."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_expenses_user(request.user):
            return HttpResponseForbidden("You don't have access to the expenses app.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def event_participant_required(view_func):
    """Gate per-event views: caller must be a Participant for that event.

    Stacks on top of `expenses_user_required`. The event is loaded once
    here and passed through to the view as a kwarg.
    """

    @wraps(view_func)
    @expenses_user_required
    def _wrapped(request, event_id, *args, **kwargs):
        event = get_object_or_404(Event, pk=event_id)
        if request.user.is_superuser:
            return view_func(request, event=event, *args, **kwargs)
        is_participant = event.participants.filter(user=request.user).exists()
        if not is_participant:
            raise Http404("Event not found")
        return view_func(request, event=event, *args, **kwargs)

    return _wrapped
