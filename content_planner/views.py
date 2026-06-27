from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .billing import check_quota
from .forms import AssetForm, BoardForm, CampaignForm, PostCreateForm, PostForm
from .models import Asset, Campaign, ContentBoard, Post
from .permissions import can_access_board, is_content_user
from .selectors import daily_sections, month_schedule, pending_summary


def _accessible_boards(user):
    """Boards the user owns or collaborates on, de-duplicated."""
    owned = ContentBoard.objects.filter(owner=user)
    collab = ContentBoard.objects.filter(collaborators__user=user)
    return (owned | collab).distinct()


def _asset_picker_context(form):
    """Pickable assets + currently-selected ids, for the thumbnail picker."""
    selected = {str(value) for value in (form["assets"].value() or [])}
    return {
        "pickable_assets": form.fields["assets"].queryset,
        "selected_asset_ids": selected,
    }


def board_required(view):
    """Resolve ``board_slug`` to a board, gate access, and activate its tz.

    Stacks the app-level ``is_content_user`` gate with a per-board access
    check, then runs the view under the board's timezone so naive datetimes in
    forms are interpreted and rendered in the board's local time.
    """

    @wraps(view)
    @user_passes_test(is_content_user)
    def _wrapped(request, board_slug, *args, **kwargs):
        board = get_object_or_404(ContentBoard, slug=board_slug)
        if not can_access_board(request.user, board):
            raise Http404("Board not found.")
        with timezone.override(board.timezone):
            return view(request, board, *args, **kwargs)

    return _wrapped


def index(request):
    """Board picker. Public landing for non-users; single-board shortcut."""
    if not is_content_user(request.user):
        return render(request, "content_planner/landing.html", {})
    boards = list(_accessible_boards(request.user).order_by("name"))
    if len(boards) == 1:
        return redirect("content_planner:board_home", board_slug=boards[0].slug)
    rows = [
        {
            "board": board,
            "is_owner": board.owner_id == request.user.id,
            "summary": pending_summary(board),
        }
        for board in boards
    ]
    return render(request, "content_planner/index.html", {"rows": rows})


@user_passes_test(is_content_user)
@require_http_methods(["GET", "POST"])
def board_create(request):
    """Create a new board owned by the current user."""
    if request.method == "POST":
        form = BoardForm(request.POST)
        if form.is_valid():
            board = form.save(commit=False)
            board.owner = request.user
            board.assign_slug()
            board.save()
            messages.success(request, f"Created board '{board.name}'.")
            return redirect("content_planner:board_home", board_slug=board.slug)
    else:
        form = BoardForm()
    return render(request, "content_planner/board_form.html", {"form": form})


@board_required
def board_home(request, board):
    """Daily overview: the landing page of a board."""
    return render(
        request,
        "content_planner/board_home.html",
        {"board": board, "sections": daily_sections(board)},
    )


@board_required
def schedule(request, board):
    """Month calendar grid of scheduled posts, navigable by month."""
    today = timezone.localdate()  # board-local: board_required activated the tz
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        grid = month_schedule(board, year, month)
    except (ValueError, TypeError):
        grid = month_schedule(board, today.year, today.month)
    return render(
        request,
        "content_planner/schedule.html",
        {"board": board, "grid": grid, "today": today},
    )


@board_required
def campaign_list(request, board):
    campaigns = board.campaigns.all()
    return render(
        request,
        "content_planner/campaign_list.html",
        {"board": board, "campaigns": campaigns},
    )


@board_required
@require_http_methods(["GET", "POST"])
def campaign_create(request, board):
    if request.method == "POST":
        form = CampaignForm(request.POST, board=board)
        if form.is_valid():
            campaign = form.save()
            messages.success(request, f"Created campaign '{campaign.name}'.")
            return redirect(
                "content_planner:campaign_detail",
                board_slug=board.slug,
                slug=campaign.slug,
            )
    else:
        form = CampaignForm(board=board)
    return render(
        request,
        "content_planner/campaign_form.html",
        {"board": board, "form": form, "is_create": True},
    )


@board_required
@require_http_methods(["GET", "POST"])
def campaign_edit(request, board, slug):
    campaign = get_object_or_404(Campaign, board=board, slug=slug)
    if request.method == "POST":
        form = CampaignForm(request.POST, board=board, instance=campaign)
        if form.is_valid():
            campaign = form.save()
            messages.success(request, "Campaign updated.")
            return redirect(
                "content_planner:campaign_detail",
                board_slug=board.slug,
                slug=campaign.slug,
            )
    else:
        form = CampaignForm(board=board, instance=campaign)
    return render(
        request,
        "content_planner/campaign_form.html",
        {"board": board, "form": form, "campaign": campaign, "is_create": False},
    )


@board_required
def campaign_detail(request, board, slug):
    campaign = get_object_or_404(Campaign, board=board, slug=slug)
    posts = campaign.posts.select_related("campaign__board").prefetch_related("assets")
    return render(
        request,
        "content_planner/campaign_detail.html",
        {"board": board, "campaign": campaign, "posts": posts},
    )


@board_required
@require_http_methods(["GET", "POST"])
def post_create(request, board, slug):
    campaign = get_object_or_404(Campaign, board=board, slug=slug)
    if request.method == "POST":
        form = PostCreateForm(request.POST, request.FILES, campaign=campaign)
        if form.is_valid():
            posts = form.create_posts(request.user)
            messages.success(
                request, f"Added {len(posts)} post{pluralize(len(posts))}."
            )
            return redirect(
                "content_planner:campaign_detail",
                board_slug=board.slug,
                slug=campaign.slug,
            )
    else:
        form = PostCreateForm(campaign=campaign)
    return render(
        request,
        "content_planner/post_form.html",
        {
            "board": board,
            "campaign": campaign,
            "form": form,
            "is_create": True,
            **_asset_picker_context(form),
        },
    )


@board_required
@require_http_methods(["GET", "POST"])
def post_edit(request, board, slug, post_slug):
    campaign = get_object_or_404(Campaign, board=board, slug=slug)
    post = get_object_or_404(Post, campaign=campaign, slug=post_slug)
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, campaign=campaign, instance=post)
        if form.is_valid():
            post = form.save()
            messages.success(request, "Post updated.")
            return redirect(
                "content_planner:post_detail",
                board_slug=board.slug,
                slug=campaign.slug,
                post_slug=post.slug,
            )
    else:
        form = PostForm(campaign=campaign, instance=post)
    return render(
        request,
        "content_planner/post_form.html",
        {
            "board": board,
            "campaign": campaign,
            "post": post,
            "form": form,
            "is_create": False,
            **_asset_picker_context(form),
        },
    )


@board_required
def post_detail(request, board, slug, post_slug):
    campaign = get_object_or_404(Campaign, board=board, slug=slug)
    post = get_object_or_404(Post, campaign=campaign, slug=post_slug)
    return render(
        request,
        "content_planner/post_detail.html",
        {"board": board, "campaign": campaign, "post": post},
    )


@board_required
def asset_list(request, board):
    """The board's asset library — active assets and an archived section."""
    return render(
        request,
        "content_planner/asset_list.html",
        {
            "board": board,
            "active_assets": board.assets.exclude(status=Asset.Status.ARCHIVED),
            "archived_assets": board.assets.filter(status=Asset.Status.ARCHIVED),
        },
    )


@board_required
@require_http_methods(["GET", "POST"])
def asset_create(request, board):
    if request.method == "POST":
        form = AssetForm(request.POST, request.FILES)
        if form.is_valid():
            check_quota(request.user, "assets", board.assets.count())
            asset = form.save(commit=False)
            asset.board = board
            asset.save()
            messages.success(request, f"Added asset '{asset.name}'.")
            return redirect("content_planner:asset_list", board_slug=board.slug)
    else:
        form = AssetForm()
    return render(
        request,
        "content_planner/asset_form.html",
        {"board": board, "form": form, "is_create": True},
    )


@board_required
@require_http_methods(["GET", "POST"])
def asset_edit(request, board, pk):
    asset = get_object_or_404(Asset, board=board, pk=pk)
    if request.method == "POST":
        form = AssetForm(request.POST, request.FILES, instance=asset)
        if form.is_valid():
            form.save()
            messages.success(request, "Asset updated.")
            return redirect("content_planner:asset_list", board_slug=board.slug)
    else:
        form = AssetForm(instance=asset)
    return render(
        request,
        "content_planner/asset_form.html",
        {"board": board, "form": form, "asset": asset, "is_create": False},
    )


@board_required
@require_http_methods(["POST"])
def asset_archive(request, board, pk):
    asset = get_object_or_404(Asset, board=board, pk=pk)
    asset.status = Asset.Status.ARCHIVED
    asset.save()
    messages.success(request, f"Archived '{asset.name}'.")
    return redirect("content_planner:asset_list", board_slug=board.slug)
