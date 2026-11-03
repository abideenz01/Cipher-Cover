from backend import db, runs
from backend.tests import sessions

client = sessions.client()


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
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    response = client.get(
        "/api/documents/manual/sections/9",
        params={"run_id": run_id},
        headers=sessions.claim_agent(run_id),
    ).json()
    assert response["id"] == "manual-9"
    assert response["text"].startswith("## 9. Repeat claims")
    assert "## 10." not in response["text"]
    with db.connect() as conn:
        reads = conn.execute("SELECT section_id FROM section_reads").fetchall()
    assert [r["section_id"] for r in reads] == ["manual-9"]


def test_read_needs_a_live_claim_run():
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    runs.finish(run_id, "CLM-1001", "Stopped.")
    agent = sessions.claim_agent(run_id)
    params = {"run_id": run_id}
    path = "/api/documents/manual/sections/9"
    assert client.get(path, params=params, headers=agent).status_code == 409
    missing = "/api/documents/manual/sections/15"
    assert client.get(missing, params=params, headers=agent).status_code == 404


def test_a_person_cannot_read_on_a_run():
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    path = "/api/documents/manual/sections/9"
    assert client.get(path, params={"run_id": run_id}).status_code == 403
