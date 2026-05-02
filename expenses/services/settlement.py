"""Net-balance and settlement computation for an event.

The math layer is pure: `compute_net_balances` takes raw share rows and
returns balances; `suggest_settlements` greedily pairs creditors with
debtors. The Django-touching helper `event_balances` queries the DB once
and feeds the pure layer.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from expenses.models import Event, ExpenseShare


@dataclass(frozen=True)
class Settlement:
    """A suggested transfer from one participant to another."""

    debtor_id: int
    creditor_id: int
    amount: Decimal


def compute_net_balances(rows):
    """Compute net balance per participant from share rows.

    Each row is a tuple `(participant_id, payer_id, share_amount)`.
    A positive balance means the participant is owed money; negative
    means they owe.

    Reimbursed shares should be filtered out by the caller before
    passing rows in.
    """
    balances = defaultdict(lambda: Decimal("0"))
    for participant_id, payer_id, share_amount in rows:
        amount = Decimal(share_amount)
        balances[payer_id] += amount
        balances[participant_id] -= amount
    return {pid: bal for pid, bal in balances.items() if bal != 0}


def suggest_settlements(balances):
    """Greedy minimum-transactions settlement.

    Repeatedly pair the largest creditor with the largest debtor and
    transfer the smaller of the two absolute amounts. Returns a list of
    `Settlement` records. Stable to within a cent.
    """
    creditors = sorted(
        ((pid, amt) for pid, amt in balances.items() if amt > 0),
        key=lambda x: -x[1],
    )
    debtors = sorted(
        ((pid, -amt) for pid, amt in balances.items() if amt < 0),
        key=lambda x: -x[1],
    )

    settlements = []
    i = j = 0
    while i < len(creditors) and j < len(debtors):
        creditor_id, credit = creditors[i]
        debtor_id, debt = debtors[j]
        transfer = min(credit, debt)
        settlements.append(
            Settlement(debtor_id=debtor_id, creditor_id=creditor_id, amount=transfer)
        )
        credit -= transfer
        debt -= transfer
        creditors[i] = (creditor_id, credit)
        debtors[j] = (debtor_id, debt)
        if credit == 0:
            i += 1
        if debt == 0:
            j += 1
    return settlements


def event_balances(event: Event):
    """Aggregate unreimbursed shares for an event into net balances.

    Returns `dict[participant_id -> Decimal]`. Positive = owed money.
    """
    rows = ExpenseShare.objects.filter(
        expense__event=event, reimbursed=False
    ).values_list("participant_id", "expense__payer_id", "share_amount")
    return compute_net_balances(rows)


def event_totals(event: Event):
    """Return per-participant `(paid_total, share_total)` in base currency.

    Used by the overview page for the "you paid X, your share is Y"
    breakdown. Includes reimbursed shares so users see lifetime totals.
    """
    paid = dict(
        event.expenses.values_list("payer_id")
        .annotate(total=Sum("base_amount"))
        .values_list("payer_id", "total")
    )
    shared = dict(
        ExpenseShare.objects.filter(expense__event=event)
        .values_list("participant_id")
        .annotate(total=Sum("share_amount"))
        .values_list("participant_id", "total")
    )
    participant_ids = set(paid) | set(shared)
    return {
        pid: (paid.get(pid, Decimal("0")), shared.get(pid, Decimal("0")))
        for pid in participant_ids
    }
