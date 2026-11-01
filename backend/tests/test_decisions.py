from typing import Any

from fastapi.testclient import TestClient

from backend import db, runs
from backend.main import app

client = TestClient(app)


def lease(claim_id: str) -> str:
    """Return the live claim run on a claim, starting one if there is none."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE claim_id = ? AND status = 'running'",
            (claim_id,),
        ).fetchone()
    return row["run_id"] if row else runs.begin(claim_id)


def read(claim_id: str, source: str = "wording", number: int = 5) -> None:
    """Read a section on the claim's live run."""
    params = {"run_id": lease(claim_id)}
    client.get(f"/api/documents/{source}/sections/{number}", params=params)


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
    body = {"run_id": lease(claim_id), "lines": lines(claim_id), "paid_by_others": 0}
    return client.post(f"/api/claims/{claim_id}/calculate", json=body)


def decide(
    claim_id: str, decision: str, payout: float, sections: list[str] | None = None
) -> Any:
    read(claim_id)
    body = {
        "run_id": lease(claim_id),
        "decision": decision,
        "payout": payout,
        "reason": "Reason.",
        "sections": ["wording-5"] if sections is None else sections,
        "model": "stub",
    }
    return client.post(f"/api/claims/{claim_id}/decision", json=body)


def pay(claim_id: str, amount: float) -> Any:
    body = {"run_id": lease(claim_id), "amount": amount}
    return client.post(f"/api/claims/{claim_id}/pay", json=body)


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
    assert state("CLM-1001") == "in_progress"


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
    decision = client.get("/api/claims/CLM-1002").json()["decisions"][0]
    assert decision["wording_version"] == "2026.1"
    assert decision["sections"] == [
        {"id": "wording-5", "title": "Section 5. Baggage and Personal Effects"}
    ]
    assert decision["section"] == "Section 5. Baggage and Personal Effects"
    assert decision["run_id"] == lease("CLM-1002")


def test_a_claim_is_decided_once():
    assert decide("CLM-1002", "refer", 0).status_code == 200
    response = decide("CLM-1002", "decline", 0)
    assert response.status_code == 409
    assert response.json()["detail"] == "Claim CLM-1002 is already decided."


def test_writes_need_the_claims_own_live_run():
    other = lease("CLM-1003")
    body = {"run_id": other, "lines": lines("CLM-1001"), "paid_by_others": 0}
    assert client.post("/api/claims/CLM-1001/calculate", json=body).status_code == 409
    for run_id in ("", "nope", other):
        decision = {
            "run_id": run_id,
            "decision": "refer",
            "payout": 0,
            "reason": "Reason.",
            "sections": ["wording-5"],
            "model": "stub",
        }
        response = client.post("/api/claims/CLM-1001/decision", json=decision)
        assert response.status_code == 409
        payment = {"run_id": run_id, "amount": 1.0}
        assert client.post("/api/claims/CLM-1001/pay", json=payment).status_code == 409
    finished = lease("CLM-1004")
    runs.finish(finished, "CLM-1004", "Stopped.")
    decision |= {"run_id": finished}
    assert (
        client.post("/api/claims/CLM-1004/decision", json=decision).status_code == 409
    )


def test_a_decision_must_cite_what_it_read():
    response = decide("CLM-1002", "refer", 0, ["manual-9"])
    assert response.status_code == 409
    assert "manual-9" in response.json()["detail"]
    assert decide("CLM-1002", "refer", 0, []).status_code == 409
    read("CLM-1002", "manual", 9)
    assert decide("CLM-1002", "refer", 0, ["wording-5", "manual-9"]).status_code == 200


def test_a_decision_needs_a_reason():
    read("CLM-1002")
    body = {
        "run_id": lease("CLM-1002"),
        "decision": "refer",
        "payout": 0,
        "reason": "  ",
        "sections": ["wording-5"],
        "model": "stub",
    }
    response = client.post("/api/claims/CLM-1002/decision", json=body)
    assert response.json()["detail"] == "The reason is missing."
