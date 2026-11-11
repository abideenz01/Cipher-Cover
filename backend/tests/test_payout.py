import json
from pathlib import Path
from typing import Any

from backend.payout import Line, calculate

DATA = Path(__file__).parents[2] / "data"
PLANS = json.loads((DATA / "plans.json").read_text(encoding="utf-8"))
COMPANY = json.loads((DATA / "company.json").read_text(encoding="utf-8"))
ELECTRONICS_PLUS = next(
    a for a in PLANS["add_ons"] if a["add_on"] == "electronics_plus"
)


def policy(
    plan: str = "premium",
    travelers: int = 1,
    add_ons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a made-up policy on one of the real plans, shaped like policy_view."""
    return {
        "limits": next(p for p in PLANS["plans"] if p["plan"] == plan),
        "add_on_details": add_ons or [],
        "deductible_applies_to": PLANS["deductible_applies_to"],
        "trip": {"trip_cost": 2000.0},
        "travelers": [f"Traveler {n}" for n in range(travelers)],
    }


def line(  # noqa: PLR0913, PLR0917 - one argument per field
    amount: float,
    kind: str = "item",
    quantity: int = 1,
    nights: int = 0,
    hours: float = 0,
    description: str = "Item",
) -> Line:
    return Line.model_validate(
        {
            "description": description,
            "amount": amount,
            "kind": kind,
            "quantity": quantity,
            "nights": nights,
            "hours": hours,
        }
    )


def pay(policy_: dict[str, Any], benefit: str, lines: list[Line], others=0.0) -> int:
    return calculate(policy_, COMPANY, benefit, lines, others)[0]


def test_worked_example_1_belongings_on_economy():
    lines = [line(220, description="Jacket"), line(140), line(25)]
    total, steps = calculate(policy("economy"), COMPANY, "baggage", lines, 0)
    assert total == 21500
    assert steps[0]["label"] == "Jacket (limited to $150.00)"
    assert steps[0]["amount"] == 150


def test_worked_example_2_trip_delay_on_first_is_capped():
    assert pay(policy("first"), "trip_delay", [line(1720, "expense")]) == 150000


def test_worked_example_3_electronics_plus_on_premium():
    lines = [line(1450, "electronics")]
    assert (
        pay(policy("premium", add_ons=[ELECTRONICS_PLUS]), "baggage", lines) == 115000
    )


def test_electronics_without_the_add_on_use_the_item_limit():
    assert pay(policy("economy"), "baggage", [line(900, "electronics")]) == 5000


def test_quantity_multiplies_the_per_item_limit():
    three_shirts = line(600, quantity=3)
    assert pay(policy("economy"), "baggage", [three_shirts]) == (450 - 100) * 100


def test_a_room_for_every_two_travelers_at_350_a_night():
    hotel = line(2400, "hotel", nights=2)
    assert pay(policy("first", travelers=3), "trip_delay", [hotel]) == 140000
    assert pay(policy("first", travelers=2), "trip_delay", [hotel]) == 70000


def test_meals_without_receipts_per_traveler_per_started_day():
    meals = [line(500, "meals_without_receipts", hours=11)]
    assert pay(policy("first", travelers=2), "trip_delay", meals) == 7000
    meals = [line(500, "meals_without_receipts", hours=30)]
    assert pay(policy("first", travelers=2), "trip_delay", meals) == 14000


def test_meals_without_receipts_never_more_than_claimed():
    meals = [line(20, "meals_without_receipts", hours=30)]
    assert pay(policy("first"), "trip_delay", meals) == 2000


def test_cash_counts_up_to_100_in_all():
    lines = [line(80, "cash"), line(70, "cash"), line(40)]
    total, steps = calculate(policy("first"), COMPANY, "baggage", lines, 0)
    assert "Cash (up to $100.00 in all)" in [s["label"] for s in steps]
    assert total == 14000


def test_expenses_have_no_limit_of_their_own():
    assert pay(policy("economy"), "trip_delay", [line(245, "expense")]) == 24500


def test_others_payments_come_off_before_the_deductible():
    total, steps = calculate(policy(), COMPANY, "baggage", [line(200)], 120)
    assert total == (200 - 120 - 50) * 100
    assert [s["label"] for s in steps[-3:]] == [
        "Less paid by others",
        "Less the deductible",
        "Payout",
    ]


def test_the_deductible_is_never_more_than_what_is_left():
    total, steps = calculate(policy("economy"), COMPANY, "baggage", [line(30)], 0)
    assert total == 0
    assert {"label": "Less the deductible", "amount": -30.0} in steps


def test_no_deductible_once_others_have_paid_it_all():
    total, steps = calculate(policy(), COMPANY, "baggage", [line(100)], 100)
    assert total == 0
    assert "Less the deductible" not in [s["label"] for s in steps]


def test_deductible_on_emergency_medical():
    assert pay(policy(), "emergency_medical", [line(425, "expense")]) == 37500


def test_maximum_applies_last():
    lines = [line(300)] * 8
    total, steps = calculate(policy(), COMPANY, "baggage", lines, 0)
    assert total == round(policy()["limits"]["baggage_max"] * 100)
    assert steps[-2]["label"] == "Capped at the benefit maximum"


def test_cancellation_is_capped_at_the_trip_cost():
    assert pay(policy("first"), "trip_cancellation", [line(3000, "expense")]) == 200000
