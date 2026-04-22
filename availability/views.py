import json
from datetime import timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import AvailabilityProfile
from .services.availability import (
    classify_candidate,
    compute_availability,
    recommend_week,
)


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
