from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import (
    QuestionFormSet,
    SurveyForm,
    SurveyImportForm,
    SurveyResponseForm,
    ThemeForm,
)
from .models import Question, Response, ResponseTheme, Survey, Theme
from .services.aggregations import aggregate_survey
from .services.exports import build_action_items_markdown, build_csv
from .services.import_md import (
    MarkdownImportError,
    import_survey,
    parse_markdown,
)
from .services.publishing import ensure_short_url
from .services.themes import co_occurring, merge as merge_themes
from .services.triage import (
    QUICK_ACTION_THEME_NAMES,
    apply_triage,
    auto_mark_whitespace_not_actionable,
    next_to_review,
    progress,
    queue_neighbors,
    toggle_flag,
)


@require_http_methods(["GET", "POST"])
def respond(request, slug):
    """Render the public respondent form, or accept a submission.

    Drafts return 404 — they shouldn't exist publicly.
    Closed surveys render a friendly "this survey is closed" page at
    200 (not 404) so a respondent who follows an old link learns it's
    closed rather than that they have the wrong URL.
    """
    survey = get_object_or_404(Survey, slug=slug)
    if survey.status == Survey.Status.DRAFT:
        raise Http404("Survey is not published.")
    if survey.status == Survey.Status.CLOSED:
        return render(request, "surveys/closed.html", {"survey": survey})
    if request.method == "POST":
        form = SurveyResponseForm(request.POST, survey=survey)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(
                reverse("surveys:done", kwargs={"slug": survey.slug})
            )
    else:
        form = SurveyResponseForm(survey=survey)
    pairs = [(q, form[f"q{q.id}"]) for q in form.questions]
    return render(
        request,
        "surveys/respond.html",
        {"survey": survey, "form": form, "pairs": pairs},
    )


def done(request, slug):
    """Thank-you page shown after a successful submission."""
    survey = get_object_or_404(Survey, slug=slug, status=Survey.Status.PUBLISHED)
    return render(request, "surveys/done.html", {"survey": survey})


def dashboard(request):
    """Public landing for the surveys app, or list of own surveys for authenticated users."""
    if not request.user.is_authenticated:
        return render(request, "surveys/landing.html", {})
    surveys = Survey.objects.filter(owner=request.user).order_by("-creation_date")
    return render(request, "surveys/dashboard.html", {"surveys": surveys})


@login_required
@require_http_methods(["GET", "POST"])
def import_view(request):
    """Upload a markdown file → create a Survey + Questions in one shot."""
    if request.method == "POST":
        form = SurveyImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["markdown_file"]
            try:
                text = uploaded.read().decode("utf-8")
            except UnicodeDecodeError:
                form.add_error("markdown_file", "File must be UTF-8 encoded.")
            else:
                try:
                    parsed = parse_markdown(text)
                    survey = import_survey(parsed, owner=request.user)
                except MarkdownImportError as exc:
                    form.add_error("markdown_file", str(exc))
                else:
                    return HttpResponseRedirect(
                        reverse("surveys:edit", kwargs={"slug": survey.slug})
                    )
    else:
        form = SurveyImportForm()
    return render(request, "surveys/import.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    """Builder for a new survey."""
    if request.method == "POST":
        survey_form = SurveyForm(request.POST)
        formset = QuestionFormSet(request.POST, instance=Survey())
        if survey_form.is_valid():
            survey = survey_form.save(commit=False)
            survey.owner = request.user
            formset = QuestionFormSet(request.POST, instance=survey)
            if formset.is_valid():
                with transaction.atomic():
                    survey.save()
                    formset.save()
                ensure_short_url(survey)
                return HttpResponseRedirect(
                    reverse("surveys:edit", kwargs={"slug": survey.slug})
                )
    else:
        survey_form = SurveyForm()
        formset = QuestionFormSet(instance=Survey())
    return render(
        request,
        "surveys/builder.html",
        {"survey_form": survey_form, "formset": formset, "is_new": True},
    )


@login_required
@require_http_methods(["GET", "POST"])
def triage(request, slug):
    """One-response-at-a-time tagging for open-text responses.

    GET picks the next untriaged response (or the one after ``?after=<id>``
    when called from a Skip action). POST applies the chosen tags and
    redirects back to GET so the next response is shown.
    """
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    if request.method == "POST":
        action = request.POST.get("action", "next")
        response_id = int(request.POST.get("response_id", "0"))
        response = get_object_or_404(
            Response, id=response_id, question__survey=survey
        )
        if action == "skip":
            return HttpResponseRedirect(
                reverse("surveys:triage", kwargs={"slug": slug}) + f"?after={response.id}"
            )
        if action == "flag":
            """Flag is a status, not a theme — toggle and stay on the same response."""
            toggle_flag(response)
            return HttpResponseRedirect(
                reverse("surveys:triage", kwargs={"slug": slug}) + f"?response={response.id}"
            )
        theme_ids = [int(x) for x in request.POST.getlist("theme_ids") if x.isdigit()]
        new_theme_name = request.POST.get("new_theme_name", "").strip()
        quick_action = action if action in QUICK_ACTION_THEME_NAMES else None
        apply_triage(
            response=response,
            theme_ids=theme_ids,
            new_theme_name=new_theme_name,
            quick_action=quick_action,
            user=request.user,
        )
        return HttpResponseRedirect(reverse("surveys:triage", kwargs={"slug": slug}))

    response = None
    requested_id = request.GET.get("response")
    if requested_id:
        response = Response.objects.filter(
            id=requested_id, question__survey=survey
        ).first()
    if response is None:
        after_id = request.GET.get("after")
        response = next_to_review(survey, int(after_id) if after_id else None)
    if response is not None:
        """Whitespace-only responses get auto-marked Not actionable on
        first view — saves the organizer from clicking through obvious junk."""
        auto_mark_whitespace_not_actionable(response, request.user)
    reviewed, total = progress(survey)
    if response is None:
        return render(
            request,
            "surveys/triage_done.html",
            {"survey": survey, "reviewed": reviewed, "total": total},
        )
    themes = list(survey.themes.all().order_by("name"))
    tagged_theme_ids = set(
        ResponseTheme.objects.filter(response=response).values_list("theme_id", flat=True)
    )
    prev_id, next_id = queue_neighbors(survey, response.id)
    return render(
        request,
        "surveys/triage.html",
        {
            "survey": survey,
            "response": response,
            "themes": themes,
            "reviewed": reviewed,
            "total": total,
            "tagged_theme_ids": tagged_theme_ids,
            "prev_id": prev_id,
            "next_id": next_id,
        },
    )


@login_required
def export_csv(request, slug):
    """Owner-only CSV download of all raw responses."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    body = build_csv(survey)
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="secretcodes-{survey.slug}-responses.csv"'
    )
    return response


@login_required
def export_action_items(request, slug):
    """Owner-only markdown export of action items — paste-ready for a
    retro doc, GitHub issue, or Notion page."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    body = build_action_items_markdown(survey)
    response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="secretcodes-{survey.slug}-action-items.md"'
    )
    return response


@login_required
def results(request, slug):
    """Per-survey aggregated results. Owner-only."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    aggregation = aggregate_survey(survey)
    return render(
        request,
        "surveys/results.html",
        {"survey": survey, "agg": aggregation},
    )


_STATUS_RANK = {
    Theme.Status.OPEN: 0,
    Theme.Status.IN_PROGRESS: 1,
    Theme.Status.RESOLVED: 2,
}
_PRIORITY_RANK = {
    Theme.Priority.HIGH: 0,
    Theme.Priority.MEDIUM: 1,
    Theme.Priority.LOW: 2,
}


@login_required
def actions(request, slug):
    """List of action items + drafts (themes still missing an action_item)."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    themes = list(
        survey.themes.annotate(
            mention_count=Count("responses", distinct=True)
        ).prefetch_related("responsetheme_set__response")
    )
    items, drafts = [], []
    for theme in themes:
        theme.rep_response = next(
            (
                rt.response
                for rt in theme.responsetheme_set.all()
                if rt.is_representative
            ),
            None,
        )
        bucket = items if theme.action_item.strip() else drafts
        bucket.append(theme)
    items.sort(
        key=lambda t: (
            _STATUS_RANK.get(t.status, 99),
            _PRIORITY_RANK.get(t.priority, 99),
            t.name.lower(),
        )
    )
    drafts.sort(key=lambda t: -t.mention_count)
    open_count = sum(1 for t in items if t.status != Theme.Status.RESOLVED)
    resolved_count = sum(1 for t in items if t.status == Theme.Status.RESOLVED)
    return render(
        request,
        "surveys/actions.html",
        {
            "survey": survey,
            "items": items,
            "drafts": drafts,
            "open_count": open_count,
            "resolved_count": resolved_count,
        },
    )


@login_required
@require_http_methods(["POST"])
def theme_resolve(request, slug, theme_id):
    """Quick toggle status open ↔ resolved from the actions dashboard."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    theme = get_object_or_404(Theme, id=theme_id, survey=survey)
    if theme.status == Theme.Status.RESOLVED:
        theme.status = Theme.Status.OPEN
    else:
        theme.status = Theme.Status.RESOLVED
    theme.save(update_fields=["status", "modified_date"])
    next_url = request.POST.get("next") or reverse(
        "surveys:actions", kwargs={"slug": slug}
    )
    return HttpResponseRedirect(next_url)


@login_required
@require_http_methods(["GET", "POST"])
def theme_detail(request, slug, theme_id):
    """Read all responses for a theme, draft the action item."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    theme = get_object_or_404(Theme, id=theme_id, survey=survey)
    if request.method == "POST":
        form = ThemeForm(request.POST, instance=theme)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(
                reverse("surveys:theme_detail",
                        kwargs={"slug": slug, "theme_id": theme.id})
            )
    else:
        form = ThemeForm(instance=theme)
    response_themes = list(
        ResponseTheme.objects.filter(theme=theme)
        .select_related("response", "response__question")
        .order_by("-is_representative", "response__submitted_at")
    )
    other_themes = list(
        survey.themes.exclude(id=theme.id).order_by("name")
    )
    return render(
        request,
        "surveys/theme_detail.html",
        {
            "survey": survey,
            "theme": theme,
            "form": form,
            "response_themes": response_themes,
            "other_themes": other_themes,
            "co_occurring": co_occurring(theme),
        },
    )


@login_required
@require_http_methods(["POST"])
def theme_star(request, slug, theme_id, response_id):
    """Toggle the representative flag on a response within a theme.

    Only one representative is allowed per theme (DB constraint), so
    starring a new one un-stars the previous in the same transaction.
    """
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    theme = get_object_or_404(Theme, id=theme_id, survey=survey)
    rt = get_object_or_404(ResponseTheme, theme=theme, response_id=response_id)
    with transaction.atomic():
        if rt.is_representative:
            rt.is_representative = False
            rt.save(update_fields=["is_representative"])
        else:
            ResponseTheme.objects.filter(
                theme=theme, is_representative=True
            ).update(is_representative=False)
            rt.is_representative = True
            rt.save(update_fields=["is_representative"])
    return HttpResponseRedirect(
        reverse("surveys:theme_detail",
                kwargs={"slug": slug, "theme_id": theme_id})
    )


@login_required
@require_http_methods(["POST"])
def theme_untag(request, slug, theme_id, response_id):
    """Remove a response's tag on this theme."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    theme = get_object_or_404(Theme, id=theme_id, survey=survey)
    ResponseTheme.objects.filter(theme=theme, response_id=response_id).delete()
    return HttpResponseRedirect(
        reverse("surveys:theme_detail",
                kwargs={"slug": slug, "theme_id": theme_id})
    )


@login_required
@require_http_methods(["POST"])
def theme_merge(request, slug, theme_id):
    """Merge this theme into the chosen target; redirect to target."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    source = get_object_or_404(Theme, id=theme_id, survey=survey)
    target_id = request.POST.get("target_theme_id")
    target = get_object_or_404(Theme, id=target_id, survey=survey)
    merge_themes(source, target)
    return HttpResponseRedirect(
        reverse("surveys:theme_detail",
                kwargs={"slug": slug, "theme_id": target.id})
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, slug):
    """Builder for an existing survey. Owner-only."""
    survey = get_object_or_404(Survey, slug=slug, owner=request.user)
    if request.method == "POST":
        survey_form = SurveyForm(request.POST, instance=survey)
        formset = QuestionFormSet(request.POST, instance=survey)
        if survey_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                survey_form.save()
                """Shift existing orders out of the way so a swap of N↔M doesn't
                trip the (survey, order) unique constraint during per-row saves."""
                Question.objects.filter(survey=survey).update(
                    order=F("order") + 10000
                )
                formset.save()
            ensure_short_url(survey)
            return HttpResponseRedirect(
                reverse("surveys:edit", kwargs={"slug": survey.slug})
            )
    else:
        survey_form = SurveyForm(instance=survey)
        formset = QuestionFormSet(instance=survey)
    return render(
        request,
        "surveys/builder.html",
        {
            "survey": survey,
            "survey_form": survey_form,
            "formset": formset,
            "is_new": False,
        },
    )
