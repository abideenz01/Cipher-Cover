"""Section 10 of the policy wording: how we work out a payment."""

from typing import Any

from pydantic import BaseModel

from backend.db import cents

MAXIMA = {
    "baggage": "baggage_max",
    "baggage_delay": "baggage_delay_max",
    "trip_delay": "trip_delay_max",
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


class Line(BaseModel):
    """One item or expense claimed."""

    description: str
    amount: float
    electronic: bool


def item_limit(policy: dict[str, Any], line: Line) -> int:
    """Return the per-item limit for one belonging, in cents."""
    for add_on in policy["add_on_details"]:
        if line.electronic and "electronics_per_item_limit" in add_on:
            return cents(add_on["electronics_per_item_limit"])
    return cents(policy["limits"]["per_item_limit"])


def calculate(
    policy: dict[str, Any], benefit: str, lines: list[Line], paid_by_others: float
) -> tuple[int, list[dict[str, Any]]]:
    """Return the payout in cents and the steps that reach it."""
    steps: list[dict[str, Any]] = []
    total = 0
    for line in lines:
        amount = cents(line.amount)
        label = line.description
        if benefit == "baggage" and amount > (limit := item_limit(policy, line)):
            amount = limit
            label += f" (capped at the ${limit / 100:,.2f} per-item limit)"
        steps.append({"label": label, "amount": amount / 100})
        total += amount
    steps.append({"label": "Eligible total", "amount": total / 100})
    if paid_by_others:
        total -= cents(paid_by_others)
        steps.append({"label": "Less paid by others", "amount": -paid_by_others})
    if benefit in policy["deductible_applies_to"]:
        deductible = cents(policy["limits"]["deductible"])
        total -= deductible
        steps.append({"label": "Less the deductible", "amount": -deductible / 100})
    total = max(total, 0)
    maximum = cents(policy["limits"][MAXIMA[benefit]])
    if benefit in ("trip_cancellation", "trip_interruption"):
        maximum = min(maximum, cents(policy["trip"]["trip_cost"]))
    if total > maximum:
        total = maximum
        steps.append({"label": "Capped at the benefit maximum", "amount": total / 100})
    steps.append({"label": "Payout", "amount": total / 100})
    return total, steps
