"""Short, spoken facts about claims. No story, document text or personal data."""

import json
import sqlite3
from typing import Any

from backend import db, store

ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = [
    "_",
    "_",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]
DIGITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]
STATES = {
    "waiting": "waiting",
    "in_progress": "in progress",
    "waiting_for_signoff": "waiting for sign-off",
    "decided": "decided",
}


def money(amount: float) -> str:
    """Write an amount as $1,250.00."""
    return f"${amount:,.2f}"


HUNDRED = 100


def words(number: int) -> str:
    """Write a whole number in words, such as one thousand one hundred fifty."""
    if number < len(ONES):
        return ONES[number]
    if number < HUNDRED:
        tens, ones = divmod(number, 10)
        return TENS[tens] + (f"-{ONES[ones]}" if ones else "")
    for size, name in ((1_000_000, "million"), (1000, "thousand"), (100, "hundred")):
        if number >= size:
            high, rest = divmod(number, size)
            return f"{words(high)} {name}" + (f" {words(rest)}" if rest else "")
    return ""


def speak_money(amount: float) -> str:
    """Write an amount in words, such as one thousand fifty dollars and ten cents."""
    whole, cents = divmod(db.cents(amount), 100)
    text = f"{words(whole)} dollar{'' if whole == 1 else 's'}"
    return text + (
        f" and {words(cents)} cent{'' if cents == 1 else 's'}" if cents else ""
    )


def speak_claim_id(claim_id: str) -> str:
    """Read a claim id digit by digit, such as claim one zero one one."""
    return "claim " + " ".join(DIGITS[int(d)] for d in claim_id if d.isdigit())


def claim_brief(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any]:
    """Return the facts of one claim."""
    row = store.claim_row(conn, claim_id)
    data = json.loads(row["data"])
    customer = store.short_name(store.customer_name(conn, row["customer_id"]))
    kind = data["claim_type"].replace("_", " ")
    state = STATES[row["state"]]
    amount = data["amount_claimed"]
    return {
        "claim_id": claim_id,
        "state": row["state"],
        "customer": customer,
        "claim_type": data["claim_type"],
        "amount_claimed": amount,
        "reply": (
            f"{claim_id} is {state}. {customer} claimed {money(amount)} for {kind}."
        ),
        "speech": (
            f"{speak_claim_id(claim_id).capitalize()} is {state}. "
            f"{customer} claimed {speak_money(amount)} for {kind}."
        ),
    }


def decision_brief(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any]:
    """Return a claim's latest decision."""
    row = store.claim_row(conn, claim_id)
    latest = store.latest_decision(conn, claim_id)
    spoken = speak_claim_id(claim_id).capitalize()
    if latest is None:
        return {
            "claim_id": claim_id,
            "state": row["state"],
            "decision": "",
            "payout": 0.0,
            "reply": f"{claim_id} has no decision yet.",
            "speech": f"{spoken} has no decision yet.",
        }
    payout = db.dollars(latest["payout_cents"])
    verb = {"approve": "approved", "decline": "declined", "refer": "referred"}
    decided = verb[latest["decision"]]
    paying = f" for {money(payout)}" if latest["decision"] == "approve" else ""
    spoken_paying = (
        f" for {speak_money(payout)}" if latest["decision"] == "approve" else ""
    )
    return {
        "claim_id": claim_id,
        "state": row["state"],
        "decision": latest["decision"],
        "payout": payout,
        "section": latest["section"],
        "reason": latest["reason"],
        "reply": f"{claim_id} was {decided}{paying} under {latest['section']}.",
        "speech": f"{spoken} was {decided}{spoken_paying} under {latest['section']}.",
    }


def run_status_brief(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any]:
    """Return the outcome of a claim's latest run."""
    row = store.claim_row(conn, claim_id)
    run = conn.execute(
        "SELECT * FROM runs WHERE claim_id = ? ORDER BY started_at DESC LIMIT 1",
        (claim_id,),
    ).fetchone()
    spoken = speak_claim_id(claim_id).capitalize()
    if run is None:
        status, reply = "", "has not been run yet"
    else:
        status = run["status"]
        reply = {
            "running": "is being decided now",
            "succeeded": "was run and decided",
            "failed": "was run and the run failed",
        }[status]
    return {
        "claim_id": claim_id,
        "state": row["state"],
        "status": status,
        "reply": f"{claim_id} {reply}.",
        "speech": f"{spoken} {reply}.",
    }


def analytics_brief(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the number of claims in each state and the total paid."""
    counts = dict.fromkeys(STATES, 0)
    for row in conn.execute("SELECT state, COUNT(*) AS n FROM claims GROUP BY state"):
        counts[row["state"]] = row["n"]
    paid = db.dollars(
        conn.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM payments").fetchone()[
            0
        ]
    )
    parts = [f"{counts[s]} {STATES[s]}" for s in STATES]
    return {
        "counts": counts,
        "paid": paid,
        "reply": f"{', '.join(parts)}. {money(paid)} paid so far.",
        "speech": f"{', '.join(parts)}. {speak_money(paid)} paid so far.",
    }
