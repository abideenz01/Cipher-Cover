import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend import seed
from backend.main import app

client = TestClient(app)
PERSONAL = {"email", "phone", "date_of_birth", "address"}


def keys(value: Any) -> set[str]:
    """Return every key in a JSON value, however deep."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def test_queue():
    claims = client.get("/api/claims").json()
    assert len(claims) == 35
    assert claims[0]["claim_id"] == "CLM-1001"
    assert claims[-1]["claim_id"] == "CLM-1410"
    assert {c["state"] for c in claims} == {"waiting"}
    assert claims[1]["customer"] == "Tom B."


def test_claim():
    claim = client.get("/api/claims/CLM-1002").json()
    assert len(claim["items"]) == 6
    assert len(claim["documents"]) == 3
    assert claim["amount_claimed"] == 1150.0
    assert claim["decisions"] == []


def test_policy():
    policy = client.get("/api/policies/POL-2002").json()
    assert policy["plan"] == "premium"
    assert policy["limits"]["deductible"] == 50.0
    assert policy["limits"]["per_item_limit"] == 300.0
    assert policy["limits"]["baggage_max"] == 1500.0


def test_history():
    history = client.get("/api/customers/CUS-3001/history").json()
    assert history["name"] == "Maya Patel"
    assert [c["claim_id"] for c in history["previous_claims"]] == ["CLM-0412"]


def test_no_personal_data_anywhere():
    responses = [
        client.get("/api/claims").json(),
        client.get("/api/handlers").json(),
        client.get("/api/customers/CUS-3001/history").json(),
        client.get("/api/policies/POL-2001").json(),
    ]
    responses += [
        client.get(f"/api/claims/{c['claim_id']}").json() for c in responses[0]
    ]
    assert not keys(responses) & PERSONAL


def test_wording_and_instructions():
    wording = client.get("/api/wording").json()
    assert wording["version"] == "2026.1"
    assert wording["text"] == (seed.DATA / "policy_wording.md").read_text(
        encoding="utf-8"
    )
    instructions = client.get("/api/instructions").json()
    assert instructions["queue"].startswith("# The UnderCover Agent: running the queue")
    assert instructions["claim"].startswith("# The UnderCover Agent: working a claim")
    assert len(instructions["fingerprint"]) == 12
    assert "evals" not in instructions["queue"] + instructions["claim"]


def test_nothing_opens_the_answer_key():
    for path in [*Path("agent").rglob("*.py"), *Path("backend").rglob("*.py")]:
        if "tests" not in path.parts:
            assert "evals" not in path.read_text(encoding="utf-8"), path


def test_handlers():
    handlers = client.get("/api/handlers").json()
    assert [h["can_approve_over_limit"] for h in handlers] == [
        True,
        True,
        True,
        False,
        False,
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/claims/CLM-9999",
        "/api/policies/POL-9999",
        "/api/customers/CUS-9999/history",
    ],
)
def test_missing(path):
    assert client.get(path).status_code == 404


def test_seed_reads_only_the_records(tmp_path, monkeypatch):
    data = tmp_path / "data"
    shutil.copytree(seed.DATA, data)
    for name in ("evals", "security"):
        shutil.rmtree(data / name)
    for name in ("knowledge.json", "followups.json", "claims_manual.md"):
        (data / name).unlink()
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "copy.db"))
    seed.seed(reset=True)
    assert len(client.get("/api/claims").json()) == 35


def test_seed_keeps_existing_data():
    seed.seed()
    assert len(client.get("/api/claims").json()) == 35


def test_every_operation_is_well_formed():
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            assert operation["operationId"], (method, path)
            description = operation.get("description", "")
            assert description, (method, path)
            assert "\n" not in description.strip(), (method, path)
            for parameter in operation.get("parameters", []):
                assert parameter["required"], (method, path, parameter["name"])
            body = operation.get("requestBody")
            if body:
                ref = body["content"]["application/json"]["schema"]["$ref"]
                model = schema["components"]["schemas"][ref.split("/")[-1]]
                assert set(model["properties"]) == set(model.get("required", []))
