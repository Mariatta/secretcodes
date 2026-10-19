"""How an expense's cost is divided between participants.

Pure functions over `Decimal`: no database access, so the order of the
charges and the rounding rule can be tested on their own. The expense form
uses them, and `brand/expenses-split.js` mirrors `itemized_amounts` for the
live preview (the server result is the one that is saved).
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def _pct(value):
    """A percent (None meaning 0) as a fraction."""
    return (value or Decimal("0")) / HUNDRED


def itemized_amounts(
    items,
    *,
    shared_amount=None,
    table_charge=None,
    surcharge_percent=None,
    tax_percent=None,
    tip_percent=None,
):
    """Exact amount per participant for a bill split by item.

    `items` maps participant id to what that person had. Per person, in
    the order a US restaurant bill works:

    1. food = their items + an equal part of `shared_amount`
    2. + `surcharge_percent` of their food (a kitchen or service surcharge)
    3. + an equal part of the flat `table_charge`
    4. + `tax_percent` of steps 1 to 3
    5. + `tip_percent` of everything so far, so the tip is after tax

    Returns unrounded `Decimal`s; round with `allocate`.
    """
    count = len(items)
    shared_each = (shared_amount or Decimal("0")) / count
    table_each = (table_charge or Decimal("0")) / count
    amounts = {}
    for participant_id, item in items.items():
        food = (item or Decimal("0")) + shared_each
        pre_tax = food + food * _pct(surcharge_percent) + table_each
        after_tax = pre_tax + pre_tax * _pct(tax_percent)
        amounts[participant_id] = after_tax + after_tax * _pct(tip_percent)
    return amounts


def allocate(total, exact, absorber_id):
    """Round each exact amount to the cent so they add up to `total`.

    Every amount rounds half up (away from zero, so refunds round the same
    way as costs); whatever cent is left over goes to `absorber_id`, which
    is the payer when they are in the split.
    """
    rounded = {
        pid: amount.quantize(CENT, rounding=ROUND_HALF_UP)
        for pid, amount in exact.items()
    }
    rounded[absorber_id] += total - sum(rounded.values(), Decimal("0"))
    return rounded
