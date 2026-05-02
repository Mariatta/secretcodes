"""Pure-math tests for the settlement service."""

from decimal import Decimal

import pytest

from expenses.services.settlement import (
    compute_net_balances,
    suggest_settlements,
)


def test_compute_net_balances_simple():
    """Alice paid 30 dinner shared 3 ways with Bob and Carol."""
    rows = [
        (1, 1, Decimal("10")),
        (2, 1, Decimal("10")),
        (3, 1, Decimal("10")),
    ]
    balances = compute_net_balances(rows)
    assert balances == {1: Decimal("20"), 2: Decimal("-10"), 3: Decimal("-10")}


def test_compute_net_balances_omits_zero():
    """Participants who net to zero are filtered out."""
    rows = [
        (1, 1, Decimal("5")),
        (2, 1, Decimal("5")),
        (1, 2, Decimal("5")),
        (2, 2, Decimal("5")),
    ]
    balances = compute_net_balances(rows)
    assert balances == {}


def test_suggest_settlements_pairs_largest_first():
    """Two debtors split one creditor."""
    balances = {1: Decimal("30"), 2: Decimal("-20"), 3: Decimal("-10")}
    transfers = suggest_settlements(balances)
    amounts = sorted(((t.debtor_id, t.creditor_id, t.amount) for t in transfers))
    assert amounts == [(2, 1, Decimal("20")), (3, 1, Decimal("10"))]


def test_suggest_settlements_minimizes_transactions():
    """Three-way swap collapses to two transfers, not three."""
    balances = {
        1: Decimal("50"),
        2: Decimal("-30"),
        3: Decimal("-20"),
    }
    transfers = suggest_settlements(balances)
    assert len(transfers) == 2
    assert sum(t.amount for t in transfers) == Decimal("50")


def test_suggest_settlements_empty():
    assert suggest_settlements({}) == []
