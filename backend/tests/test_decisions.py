from typing import Any

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def lines(claim_id: str) -> list[dict[str, Any]]:
    """Return every item on a claim as a line to pay."""
    items = client.get(f"/api/claims/{claim_id}").json()["items"]
    return [
        {
            "description": i["description"],
            "amount": i["amount"],
            "electronic": i["category"] == "electronics",
        }
        for i in items
    ]


def calculate(claim_id: str) -> Any:
    body = {"lines": lines(claim_id), "paid_by_others": 0}
    return client.post(f"/api/claims/{claim_id}/calculate", json=body)


def decide(claim_id: str, decision: str, payout: float) -> Any:
    body = {
        "decision": decision,
        "payout": payout,
        "reason": "Reason.",
        "section": "Section 5",
        "model": "stub",
    }
    return client.post(f"/api/claims/{claim_id}/decision", json=body)


def pay(claim_id: str, amount: float) -> Any:
    return client.post(f"/api/claims/{claim_id}/pay", json={"amount": amount})


def state(claim_id: str) -> str:
    return client.get(f"/api/claims/{claim_id}").json()["state"]


def test_calculate_clm_1011():
    result = calculate("CLM-1011").json()
    labels = [s["label"] for s in result["steps"]]
    amounts = [s["amount"] for s in result["steps"]]
    assert result["payout"] == 1500.0
    assert amounts[labels.index("Eligible total")] == 1910.0
    assert amounts[labels.index("Less the deductible")] == -50.0
    assert labels[-2] == "Capped at the benefit maximum"


def test_approve_must_match_the_calculation():
    assert decide("CLM-1001", "approve", 420.0).status_code == 409
    calculate("CLM-1001")
    assert decide("CLM-1001", "approve", 400.0).status_code == 409
    assert state("CLM-1001") == "waiting"


def test_decline_pays_nothing():
    assert decide("CLM-1001", "decline", 10.0).status_code == 409
    assert decide("CLM-1001", "decline", 0).json()["state"] == "decided"


def test_over_the_limit_waits_for_sign_off():
    calculate("CLM-1011")
    assert (
        decide("CLM-1011", "approve", 1500.0).json()["state"] == "waiting_for_signoff"
    )
    response = pay("CLM-1011", 1500.0)
    assert response.status_code == 409
    assert response.json()["detail"] == "Waiting for a handler's sign-off."
    assert client.get("/api/claims/CLM-1011").json()["paid"] == 0


def test_under_the_limit_is_paid_once():
    calculate("CLM-1001")
    assert decide("CLM-1001", "approve", 420.0).json()["state"] == "decided"
    assert pay("CLM-1001", 420.0).status_code == 200
    assert pay("CLM-1001", 420.0).status_code == 409
    assert client.get("/api/claims/CLM-1001").json()["paid"] == 420.0
    assert decide("CLM-1001", "refer", 0).status_code == 409


def test_pay_only_the_approved_amount():
    assert pay("CLM-1001", 420.0).status_code == 409
    calculate("CLM-1001")
    decide("CLM-1001", "approve", 420.0)
    assert pay("CLM-1001", 419.0).status_code == 409


def test_decisions_are_kept():
    decide("CLM-1002", "refer", 0)
    first = client.get("/api/claims/CLM-1002").json()["decisions"]
    decide("CLM-1002", "decline", 0)
    decisions = client.get("/api/claims/CLM-1002").json()["decisions"]
    assert len(decisions) == 2
    assert decisions[0] == first[0]
    assert decisions[0]["wording_version"] == "2026.1"
    assert decisions[1]["decision"] == "decline"
