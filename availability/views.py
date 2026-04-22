import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import AvailabilityProfile, GoogleAccount, TrackedCalendar
from .services.availability import (
    classify_candidate,
    compute_availability,
    recommend_week,
)
from .services.oauth import build_flow, fetch_user_email

superuser_required = user_passes_test(lambda u: u.is_superuser)


def _week_bounds(profile):
    now = timezone.now().astimezone(profile.timezone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    end = start + timedelta(days=7)
    return start, end


@require_GET
def week_grid(request):
    profile = AvailabilityProfile.get_solo()
    include_extended = request.GET.get("include_extended") == "true"
    view_mode = request.GET.get("view", "summary")
    range_start, range_end = _week_bounds(profile)
    result = compute_availability(
        range_start,
        range_end,
        [],
        profile,
        include_extended=include_extended,
    )
    week_summary = recommend_week(result, [], profile, range_start, range_end)
    context = {
        "profile": profile,
        "range_start": range_start,
        "range_end": range_end,
        "result": result,
        "include_extended": include_extended,
        "exhausted": result.business_slot_count < profile.extended_reveal_threshold,
        "view_mode": view_mode,
        "week_summary": week_summary,
    }
    return render(request, "availability/week_grid.html", context)


@require_GET
def slots_json(request):
    profile = AvailabilityProfile.get_solo()
    range_start = parse_datetime(request.GET["start"])
    range_end = parse_datetime(request.GET["end"])
    duration_minutes = int(request.GET.get("duration", profile.default_slot_minutes))
    include_extended = request.GET.get("include_extended") == "true"
    result = compute_availability(
        range_start,
        range_end,
        [],
        profile,
        duration=timedelta(minutes=duration_minutes),
        include_extended=include_extended,
    )
    return JsonResponse(
        {
            "slots": [
                {
                    "start": slot.start.isoformat(),
                    "end": slot.end.isoformat(),
                    "band": slot.band,
                }
                for slot in result.free_slots
            ],
            "business_slot_count": result.business_slot_count,
        }
    )


@csrf_exempt
@require_POST
def check(request):
    payload = json.loads(request.body)
    candidate_start = parse_datetime(payload["datetime"])
    duration_minutes = int(payload.get("duration", 30))
    candidate_end = candidate_start + timedelta(minutes=duration_minutes)

    profile = AvailabilityProfile.get_solo()
    free, band, reason = classify_candidate(profile, candidate_start, candidate_end, [])
    return JsonResponse({"free": free, "band": band, "reason": reason})


@login_required
@superuser_required
@require_GET
def admin_page(request):
    return render(
        request,
        "availability/admin.html",
        {"accounts": GoogleAccount.objects.all()},
    )


@login_required
@superuser_required
@require_GET
def oauth_start(request):
    flow = build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["availability_oauth_state"] = state
    request.session["availability_code_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@login_required
@superuser_required
@require_GET
def oauth_callback(request):
    expected_state = request.session.pop("availability_oauth_state", None)
    code_verifier = request.session.pop("availability_code_verifier", None)
    if not expected_state or request.GET.get("state") != expected_state:
        return HttpResponseBadRequest("Invalid OAuth state")

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing authorization code")

    flow = build_flow()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    credentials = flow.credentials

    email = fetch_user_email(credentials)
    account, _ = GoogleAccount.objects.update_or_create(
        email=email,
        defaults={
            "label": email.split("@")[0],
            "refresh_token": credentials.refresh_token or "",
            "scopes_granted": list(credentials.scopes or []),
        },
    )
    TrackedCalendar.objects.get_or_create(
        account=account,
        google_calendar_id="primary",
        defaults={"display_label": "Primary calendar", "is_active": True},
    )

    messages.success(request, f"Connected {email}")
    return redirect(reverse("availability:admin"))
