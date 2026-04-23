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
from .services.google import fetch_busy_blocks_for_all
from .services.mcp import dispatch as mcp_dispatch
from .services.oauth import build_flow, fetch_user_email

superuser_required = user_passes_test(lambda u: u.is_superuser)


def _display_range(profile):
    now = timezone.now().astimezone(profile.timezone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=14)
    return start, end


@require_GET
def week_grid(request):
    profile = AvailabilityProfile.get_solo()
    include_extended = request.GET.get("include_extended") == "true"
    view_mode = request.GET.get("view", "summary")
    range_start, range_end = _display_range(profile)
    busy_blocks = fetch_busy_blocks_for_all(range_start, range_end)
    result = compute_availability(
        range_start,
        range_end,
        busy_blocks,
        profile,
        include_extended=include_extended,
    )
    week_summary = recommend_week(result, busy_blocks, profile, range_start, range_end)
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
    busy_blocks = fetch_busy_blocks_for_all(range_start, range_end)
    result = compute_availability(
        range_start,
        range_end,
        busy_blocks,
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
    busy_blocks = fetch_busy_blocks_for_all(candidate_start, candidate_end)
    free, band, reason = classify_candidate(
        profile, candidate_start, candidate_end, busy_blocks
    )
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


@csrf_exempt
@require_POST
def mcp_endpoint(request):
    """MCP server entry point — JSON-RPC 2.0 over HTTP POST.

    The heavy lifting lives in availability.services.mcp; this view just
    parses the JSON body and hands it off.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
            status=400,
        )
    return JsonResponse(mcp_dispatch(payload))
