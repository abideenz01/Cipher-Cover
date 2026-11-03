"""Looking up the policy wording and the claims manual one section at a time."""

from typing import Any

from fastapi import APIRouter, HTTPException

from backend import auth, clock, db, store
from backend.sections import sections

router = APIRouter(prefix="/api")


@router.get("/documents/{source}/sections", operation_id="list_sections")
def list_sections(source: str) -> list[dict[str, Any]]:
    """List the sections of the wording or the manual, with their sizes."""
    return [
        {
            "id": s["id"],
            "number": s["number"],
            "title": s["title"],
            "characters": len(s["text"]),
        }
        for s in sections(source)
    ]


@router.get("/documents/{source}/sections/{number}", operation_id="read_section")
def read_section(
    source: str, number: int, run_id: str, who: auth.Who
) -> dict[str, Any]:
    """Read one section, recorded on the claim run that read it."""
    found = [s for s in sections(source) if s["number"] == number]
    if not found:
        raise HTTPException(404, f"There is no section {number} in the {source}.")
    with db.connect() as conn:
        store.live_run(conn, run_id, who.tenant_id)
        conn.execute(
            "INSERT INTO section_reads (run_id, section_id, created_at, tenant_id)"
            " VALUES (?, ?, ?, ?)",
            (run_id, found[0]["id"], clock.stamp(), who.tenant_id),
        )
    return {"id": found[0]["id"], "title": found[0]["title"], "text": found[0]["text"]}
