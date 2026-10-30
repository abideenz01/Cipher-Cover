from typing import Any

from backend.payout import Line, calculate

ELECTRONICS_PLUS = {"add_on": "electronics_plus", "electronics_per_item_limit": 1200.0}


def policy(add_ons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a made-up Premium policy."""
    return {
        "limits": {
            "per_item_limit": 300.0,
            "deductible": 50.0,
            "baggage_max": 1500.0,
            "trip_delay_max": 800.0,
            "trip_cancellation_max": 5000.0,
            "emergency_medical_max": 100000.0,
        },
        "add_on_details": add_ons or [],
        "deductible_applies_to": ["baggage", "emergency_medical"],
        "trip": {"trip_cost": 2000.0},
    }


def line(amount: float, electronic: bool = False) -> Line:
    return Line(description="Item", amount=amount, electronic=electronic)


def test_item_over_the_limit_is_capped():
    payout, steps = calculate(policy(), "baggage", [line(400)], 0)
    assert payout == 25000
    assert "capped" in steps[0]["label"]


def test_electronics_plus_raises_the_limit_for_electronics_only():
    lines = [line(900, electronic=True), line(900)]
    payout, _ = calculate(policy([ELECTRONICS_PLUS]), "baggage", lines, 0)
    assert payout == (900 + 300 - 50) * 100


def test_electronics_without_the_add_on_use_the_item_limit():
    payout, _ = calculate(policy(), "baggage", [line(900, electronic=True)], 0)
    assert payout == 25000


def test_others_payments_come_off_before_the_deductible():
    payout, steps = calculate(policy(), "baggage", [line(200), line(200)], 120)
    assert payout == (400 - 120 - 50) * 100
    assert [s["label"] for s in steps[-3:]] == [
        "Less paid by others",
        "Less the deductible",
        "Payout",
    ]


def test_no_deductible_on_trip_delay():
    payout, _ = calculate(policy(), "trip_delay", [line(245), line(95), line(80)], 0)
    assert payout == 42000


def test_deductible_on_emergency_medical():
    payout, _ = calculate(policy(), "emergency_medical", [line(425)], 0)
    assert payout == 37500


def test_maximum_applies_last():
    payout, steps = calculate(policy(), "baggage", [line(300)] * 6, 0)
    assert payout == 150000
    assert steps[-2]["label"] == "Capped at the benefit maximum"


def test_cancellation_is_capped_at_the_trip_cost():
    payout, _ = calculate(policy(), "trip_cancellation", [line(3000)], 0)
    assert payout == 200000


def test_never_below_zero():
    payout, _ = calculate(policy(), "baggage", [line(30)], 0)
    assert payout == 0
