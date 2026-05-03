import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import redirect_to_login
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import AcceptInviteSignupForm, ExpenseForm, InvitationForm
from .models import (
    Category,
    Event,
    Expense,
    ExpenseInvitation,
    ExpenseShare,
    Participant,
)
from .permissions import (
    ACCESS_EXPENSES_CODENAME,
    EXPENSES_USER_GROUP,
    event_participant_required,
    is_expenses_user,
)
from .services.invitations import send_invitation_email
from .services.settlement import (
    event_balances,
    event_totals,
    suggest_settlements,
)

User = get_user_model()


def event_list(request):
    """Public landing for the expenses app, or event list for authorized users.

    Anonymous visitors and authenticated users without the
    `expenses_users` group see a marketing hero. Authorized users see
    their own events.
    """
    if not is_expenses_user(request.user):
        return render(request, "expenses/landing.html", {})
    if request.user.is_superuser:
        events = Event.objects.all()
    else:
        events = Event.objects.filter(participants__user=request.user).distinct()
    show_archived = request.GET.get("archived") == "1"
    if not show_archived:
        events = events.filter(is_archived=False)
    events = list(events)
    for event in events:
        event.participant_count = event.participants.count()
        event.total_spent = event.expenses.aggregate(total=Sum("base_amount"))[
            "total"
        ] or Decimal("0")
    return render(
        request,
        "expenses/event_list.html",
        {"events": events, "show_archived": show_archived},
    )


@event_participant_required
def event_overview(request, event):
    """Net balances + suggested settlements + event/personal totals."""
    participants = list(event.participants.all())
    by_id = {p.pk: p for p in participants}

    balances = event_balances(event)
    settlements = suggest_settlements(balances)
    totals = event_totals(event)
    summary = _summary_for_viewer(event, request.user, totals, balances)

    rows = [
        {
            "participant": by_id.get(pid),
            "paid": paid,
            "shared": shared,
            "balance": balances.get(pid, 0),
        }
        for pid, (paid, shared) in totals.items()
        if pid in by_id
    ]
    rows.sort(key=lambda r: -r["balance"])

    transfers = [
        {
            "debtor": by_id.get(s.debtor_id),
            "creditor": by_id.get(s.creditor_id),
            "amount": s.amount,
        }
        for s in settlements
    ]

    return render(
        request,
        "expenses/event_overview.html",
        {
            "event": event,
            "rows": rows,
            "transfers": transfers,
            "summary": summary,
        },
    )


@event_participant_required
def event_ledger(request, event):
    """Chronological list of all expenses in the event."""
    category_filter = request.GET.get("category") or ""
    expenses = (
        event.expenses.select_related("payer", "category")
        .prefetch_related("shares__participant")
        .order_by("-paid_at", "-creation_date")
    )
    if category_filter:
        expenses = expenses.filter(category_id=category_filter)
    categories_in_event = (
        Category.objects.filter(expenses__event=event).distinct().order_by("name")
    )
    me = _viewer_participant(request.user, event)
    summary = _summary_for_viewer(
        event, request.user, event_totals(event), event_balances(event)
    )
    enriched = []
    for expense in expenses:
        my_share = None
        all_reimbursed = True
        for share in expense.shares.all():
            if me and share.participant_id == me.pk:
                my_share = share.share_amount
            if not share.reimbursed:
                all_reimbursed = False
        enriched.append(
            {
                "expense": expense,
                "my_share": my_share,
                "all_reimbursed": all_reimbursed,
                "shared_by": [s.participant for s in expense.shares.all()],
                "can_modify": _can_modify(request.user, expense),
            }
        )
    return render(
        request,
        "expenses/event_ledger.html",
        {
            "event": event,
            "rows": enriched,
            "summary": summary,
            "categories": categories_in_event,
            "selected_category": category_filter,
        },
    )


@event_participant_required
def expense_create(request, event):
    """Create a new expense with equal-split among selected participants."""
    if request.method == "POST":
        form = ExpenseForm(request.POST, request.FILES, event=event, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense logged.")
            return redirect("expenses:event_ledger", event_id=event.pk)
    else:
        form = ExpenseForm(event=event, user=request.user)
    return render(
        request,
        "expenses/expense_form.html",
        {"event": event, "form": form, "mode": "create"},
    )


@event_participant_required
def expense_edit(request, event, expense_id):
    """Edit an existing expense. Only creator or superuser may modify."""
    expense = get_object_or_404(Expense, pk=expense_id, event=event)
    if not _can_modify(request.user, expense):
        return HttpResponseForbidden(
            "Only the person who logged this expense can edit it."
        )
    if request.method == "POST":
        form = ExpenseForm(request.POST, request.FILES, instance=expense, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense updated.")
            return redirect("expenses:event_ledger", event_id=event.pk)
    else:
        form = ExpenseForm(instance=expense, event=event)
    return render(
        request,
        "expenses/expense_form.html",
        {
            "event": event,
            "form": form,
            "mode": "edit",
            "expense": expense,
            "can_delete": _can_modify(request.user, expense),
        },
    )


@event_participant_required
def expense_delete(request, event, expense_id):
    """Delete an expense and its shares. Only the creator (or superuser) may."""
    expense = get_object_or_404(Expense, pk=expense_id, event=event)
    if not _can_modify(request.user, expense):
        return HttpResponseForbidden(
            "Only the person who logged this expense can delete it."
        )
    if request.method == "POST":
        expense.delete()
        messages.success(request, "Expense deleted.")
        return redirect("expenses:event_ledger", event_id=event.pk)
    return render(
        request,
        "expenses/expense_delete.html",
        {"event": event, "expense": expense},
    )


def _can_modify(user, expense) -> bool:
    """Creator-or-superuser gate for editing or deleting an expense."""
    return user.is_superuser or expense.created_by_id == user.id


@event_participant_required
def event_export_csv(request, event):
    """Stream a CSV of every expense + each share row, one share per line."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    safe_name = "".join(c if c.isalnum() else "_" for c in event.name).strip("_")
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_name or "event"}-expenses.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "expense_id",
            "date",
            "description",
            "category",
            "payer",
            "original_amount",
            "original_currency",
            "base_amount",
            "base_currency",
            "share_participant",
            "share_amount",
            "reimbursed",
        ]
    )
    rows = (
        ExpenseShare.objects.filter(expense__event=event)
        .select_related("expense", "expense__payer", "expense__category", "participant")
        .order_by("expense__paid_at", "expense_id", "participant__display_name")
    )
    for share in rows:
        expense = share.expense
        writer.writerow(
            [
                expense.pk,
                expense.paid_at.isoformat(),
                expense.description,
                expense.category.name,
                expense.payer.display_name or expense.payer_id,
                expense.original_amount,
                expense.original_currency,
                expense.base_amount,
                event.base_currency,
                share.participant.display_name or share.participant_id,
                share.share_amount,
                "yes" if share.reimbursed else "no",
            ]
        )
    return response


@event_participant_required
def settle_up(request, event, debtor_id, creditor_id):
    """Mark every unreimbursed share from `debtor` to `creditor` as paid.

    GET renders a confirmation page showing the shares about to be
    flipped and the total. POST flips them.
    """
    debtor = get_object_or_404(Participant, pk=debtor_id, event=event)
    creditor = get_object_or_404(Participant, pk=creditor_id, event=event)
    shares = ExpenseShare.objects.filter(
        expense__event=event,
        expense__payer=creditor,
        participant=debtor,
        reimbursed=False,
    ).select_related("expense")
    total = sum((s.share_amount for s in shares), Decimal("0"))

    if request.method == "POST":
        count = shares.update(reimbursed=True)
        messages.success(
            request,
            f"Marked {count} share{'s' if count != 1 else ''} reimbursed "
            f"({total} {event.base_currency}).",
        )
        return redirect("expenses:event_overview", event_id=event.pk)
    return render(
        request,
        "expenses/settle_up.html",
        {
            "event": event,
            "debtor": debtor,
            "creditor": creditor,
            "shares": shares,
            "total": total,
        },
    )


@event_participant_required
def receipt_download(request, event, expense_id):
    """Decrypt and stream a receipt back to the requester.

    Storage encrypts on disk; the FileField's `_open` decrypts when read.
    `FileResponse` reads from the returned `ContentFile` and serves it
    inline with the originally-uploaded content type, so browsers preview
    images/PDFs directly.
    """
    expense = get_object_or_404(Expense, pk=expense_id, event=event)
    if not expense.receipt:
        raise Http404("No receipt on this expense.")
    decrypted = expense.receipt.open("rb")
    response = FileResponse(
        decrypted,
        content_type=expense.receipt_content_type or "application/octet-stream",
    )
    filename = expense.receipt_original_filename or "receipt"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _viewer_participant(user, event) -> Participant | None:
    """Return the viewer's Participant row for an event, or None."""
    if not user.is_authenticated:
        return None
    return event.participants.filter(user=user).first()


def _summary_for_viewer(event, user, totals, balances):
    """Build the per-event + per-viewer summary for the page header.

    `totals[pid] = (paid, shared)` and `balances[pid] = net` are passed
    in so the caller can reuse them — avoids re-querying.
    """
    event_total = sum((paid for paid, _ in totals.values()), Decimal("0"))
    viewer = _viewer_participant(user, event)
    my_paid = my_shared = my_balance = None
    if viewer is not None:
        my_paid, my_shared = totals.get(viewer.pk, (Decimal("0"), Decimal("0")))
        my_balance = balances.get(viewer.pk, Decimal("0"))
    return {
        "event_total": event_total,
        "viewer": viewer,
        "my_paid": my_paid,
        "my_shared": my_shared,
        "my_balance": my_balance,
    }


@event_participant_required
def invite_create(request, event):
    """Owner-only form to invite someone to the event by email."""
    if request.user != event.owner and not request.user.is_superuser:
        return HttpResponseForbidden("Only the event owner can send invitations.")
    if request.method == "POST":
        form = InvitationForm(request.POST, event=event, inviter=request.user)
        if form.is_valid():
            invitation = form.save()
            send_invitation_email(invitation, request)
            messages.success(request, f"Invitation sent to {invitation.email}.")
            return redirect("expenses:event_overview", event_id=event.pk)
    else:
        form = InvitationForm(event=event, inviter=request.user)
    pending = event.invitations.filter(accepted_at__isnull=True).order_by(
        "-creation_date"
    )
    return render(
        request,
        "expenses/invite_create.html",
        {"event": event, "form": form, "pending": pending},
    )


def accept_invite(request, key):
    """Accept-invite landing page.

    Three paths based on whether a User already exists for the invited
    email:
      - User exists & is logged in as them: confirm-and-accept.
      - User exists, anonymous: redirect to login (then back here).
      - No user yet: render a signup form; on submit, create the user,
        log them in, and accept.
    """
    invitation = get_object_or_404(ExpenseInvitation, key=key)
    if invitation.is_accepted:
        messages.info(request, "This invitation has already been accepted.")
        return redirect("expenses:event_overview", event_id=invitation.event_id)
    if invitation.is_expired():
        messages.error(request, "This invitation has expired.")
        return redirect("expenses:event_list")

    user_exists = User.objects.filter(email__iexact=invitation.email).exists()

    if not user_exists:
        return _accept_with_signup(request, invitation)

    if not request.user.is_authenticated:
        messages.info(
            request,
            f"An account already exists for {invitation.email}. "
            "Please log in to accept this invitation.",
        )
        return redirect_to_login(request.get_full_path())
    if request.user.email.lower() != invitation.email.lower():
        return HttpResponseForbidden(
            "This invitation was sent to a different email address. "
            "Please log in as the invited account."
        )
    if request.method == "POST":
        _accept_invitation(invitation, request.user)
        messages.success(request, f"Welcome to {invitation.event.name}!")
        return redirect("expenses:event_overview", event_id=invitation.event_id)
    return render(request, "expenses/accept_invite.html", {"invitation": invitation})


def _accept_with_signup(request, invitation):
    """Render and process the signup form for a brand-new invitee."""
    if request.user.is_authenticated:
        return HttpResponseForbidden(
            "You're already logged in. Sign out before accepting an invite "
            "for a different email address."
        )
    if request.method == "POST":
        form = AcceptInviteSignupForm(request.POST, email=invitation.email)
        if form.is_valid():
            user = form.save()
            user.backend = "django.contrib.auth.backends.ModelBackend"
            login(request, user)
            _accept_invitation(invitation, user)
            messages.success(request, f"Welcome to {invitation.event.name}!")
            return redirect("expenses:event_overview", event_id=invitation.event_id)
    else:
        form = AcceptInviteSignupForm(email=invitation.email)
    return render(
        request,
        "expenses/accept_invite_signup.html",
        {"invitation": invitation, "form": form},
    )


def _accept_invitation(invitation: ExpenseInvitation, user) -> None:
    """Mark accepted, add user to the Expenses User group, link Participant.

    Group membership grants `expenses.access_expenses`. The migration
    (0005) sets this up at deploy time; the view re-asserts the
    group→perm link on every accept so the flow works even in test
    environments where data migrations are skipped.
    """
    perm = Permission.objects.get(
        codename=ACCESS_EXPENSES_CODENAME, content_type__app_label="expenses"
    )
    group, _ = Group.objects.get_or_create(name=EXPENSES_USER_GROUP)
    group.permissions.add(perm)
    user.groups.add(group)
    participant, _ = Participant.objects.get_or_create(
        event=invitation.event,
        invited_email=invitation.email,
        defaults={
            "display_name": invitation.display_name,
            "role": Participant.MEMBER,
        },
    )
    if participant.user_id is None:
        participant.user = user
        participant.joined_at = timezone.now()
        if not participant.display_name:
            participant.display_name = (
                invitation.display_name or user.first_name or user.get_username()
            )
        participant.save()
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "modified_date"])
