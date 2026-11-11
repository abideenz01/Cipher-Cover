"""Section 10 of the policy wording: how we work out a payment.

The limits on a line come from the claims manual: the per-item limit and
Electronics Plus (sections 6 and 7), a room at up to $350 a night for every two
travelers (section 7), meals without receipts at a flat rate (section 10), and
cash up to $100 in all (the wording's baggage exclusions).
"""

from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, Field

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
HOTEL_NIGHT_CENTS = 35000
CASH_CENTS = 10000
TRAVELERS_PER_ROOM = 2
HOURS_PER_DAY = 24

Kind = Literal[
    "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
]


class Line(BaseModel):
    """One item or expense to pay. The agent's tool describes each field."""

    description: str
    amount: float
    kind: Kind
    quantity: int = Field(ge=1)
    nights: int = Field(ge=0)
    hours: float = Field(ge=0)


def item_limit(policy: dict[str, Any], line: Line) -> int:
    """Return the per-item limit for one belonging, in cents."""
    for add_on in policy["add_on_details"]:
        if line.kind == "electronics" and "electronics_per_item_limit" in add_on:
            return cents(add_on["electronics_per_item_limit"])
    return cents(policy["limits"]["per_item_limit"])


def limit(policy: dict[str, Any], company: dict[str, Any], line: Line) -> int | None:
    """Return the most a line can count for in cents, or None if it has no limit."""
    travelers = len(policy["travelers"])
    match line.kind:
        case "item" | "electronics":
            return item_limit(policy, line) * line.quantity
        case "hotel":
            rooms = ceil(travelers / TRAVELERS_PER_ROOM)
            return HOTEL_NIGHT_CENTS * rooms * line.nights
        case "meals_without_receipts":
            days = ceil(line.hours / HOURS_PER_DAY)
            meals = company["meal_allowance_without_receipts"]["amount"]
            return cents(meals) * travelers * days
        case _:
            return None


def eligible(
    policy: dict[str, Any], company: dict[str, Any], line: Line
) -> tuple[int, str]:
    """Return the eligible amount of a line in cents, and its label."""
    amount = cents(line.amount)
    most = limit(policy, company, line)
    if most is not None and amount > most:
        return most, f"{line.description} (limited to ${most / 100:,.2f})"
    return amount, line.description


def calculate(
    policy: dict[str, Any],
    company: dict[str, Any],
    benefit: str,
    lines: list[Line],
    paid_by_others: float,
) -> tuple[int, list[dict[str, Any]]]:
    """Return the payout in cents and the steps that reach it."""
    steps: list[dict[str, Any]] = []
    total = 0
    for line in lines:
        if line.kind == "cash":
            continue
        amount, label = eligible(policy, company, line)
        steps.append({"label": label, "amount": amount / 100})
        total += amount
    cash = sum(cents(line.amount) for line in lines if line.kind == "cash")
    if cash:
        counted = min(cash, CASH_CENTS)
        label = f"Cash (up to ${CASH_CENTS / 100:,.2f} in all)"
        steps.append({"label": label, "amount": counted / 100})
        total += counted
    steps.append({"label": "Eligible total", "amount": total / 100})
    if paid_by_others:
        total -= cents(paid_by_others)
        steps.append({"label": "Less paid by others", "amount": -paid_by_others})
    if benefit in policy["deductible_applies_to"] and total > 0:
        deductible = min(cents(policy["limits"]["deductible"]), total)
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
