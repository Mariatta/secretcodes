"""Itemized split math, and the rounding that makes shares add up."""

from decimal import Decimal

from expenses.services.splitting import allocate, itemized_amounts

D = Decimal


def test_items_only_returns_items():
    assert itemized_amounts({1: D("20"), 2: D("30")}) == {1: D("20"), 2: D("30")}


def test_tip_is_on_the_total_after_tax():
    """$100 meal, 10% tax, 20% tip: 100 * 1.10 * 1.20 = 132."""
    amounts = itemized_amounts({1: D("100")}, tax_percent=D("10"), tip_percent=D("20"))
    assert amounts[1] == D("132")


def test_surcharge_is_on_food_and_taxed():
    """$100 food + 4% surcharge = 104, + 10% tax = 114.4."""
    amounts = itemized_amounts(
        {1: D("100")}, surcharge_percent=D("4"), tax_percent=D("10")
    )
    assert amounts[1] == D("114.4")


def test_shared_and_table_charge_split_equally_table_not_surcharged():
    """Each: 10 own + 5 shared = 15 food, +10% surcharge = 16.5, + 2 table = 18.5."""
    amounts = itemized_amounts(
        {1: D("10"), 2: D("10")},
        shared_amount=D("10"),
        table_charge=D("4"),
        surcharge_percent=D("10"),
    )
    assert amounts == {1: D("18.5"), 2: D("18.5")}


def test_person_with_no_items_still_pays_their_part_of_shared():
    amounts = itemized_amounts({1: D("12"), 2: None}, shared_amount=D("8"))
    assert amounts == {1: D("16"), 2: D("4")}


def test_allocate_gives_leftover_cent_to_absorber():
    exact = {1: D("10") / 3, 2: D("10") / 3, 3: D("10") / 3}
    assert allocate(D("10.00"), exact, absorber_id=2) == {
        1: D("3.33"),
        2: D("3.34"),
        3: D("3.33"),
    }
