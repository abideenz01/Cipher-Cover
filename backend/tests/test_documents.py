from fastapi.testclient import TestClient

from backend import db, runs
from backend.main import app

client = TestClient(app)


def test_list_sections():
    wording = client.get("/api/documents/wording/sections").json()
    manual = client.get("/api/documents/manual/sections").json()
    assert len(wording) == 12
    assert len(manual) == 14
    assert wording[4]["id"] == "wording-5"
    assert wording[4]["title"] == "Baggage and Personal Effects"
    assert all(s["characters"] > 0 for s in wording + manual)
    assert client.get("/api/documents/evals/sections").status_code == 404


def test_read_one_section_records_the_read():
    run_id = runs.begin("CLM-1001")
    response = client.get(
        "/api/documents/manual/sections/9", params={"run_id": run_id}
    ).json()
    assert response["id"] == "manual-9"
    assert response["text"].startswith("## 9. Repeat claims")
    assert "## 10." not in response["text"]
    with db.connect() as conn:
        reads = conn.execute("SELECT section_id FROM section_reads").fetchall()
    assert [r["section_id"] for r in reads] == ["manual-9"]


def test_read_needs_a_live_claim_run():
    params = {"run_id": "nope"}
    assert (
        client.get("/api/documents/manual/sections/9", params=params).status_code == 409
    )
    run_id = runs.begin("CLM-1001")
    runs.finish(run_id, "CLM-1001", "Stopped.")
    params = {"run_id": run_id}
    assert (
        client.get("/api/documents/manual/sections/9", params=params).status_code == 409
    )
    assert (
        client.get("/api/documents/manual/sections/15", params=params).status_code
        == 404
    )
