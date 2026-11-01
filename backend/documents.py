"""The policy wording and the claims manual, looked up one section at a time."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException

from backend import clock, db, seed, store

router = APIRouter(prefix="/api")
FILES = {"wording": "policy_wording.md", "manual": "claims_manual.md"}
HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


def sections(source: str) -> list[dict[str, Any]]:
    """Split a document on its numbered headings, or raise 404."""
    if source not in FILES:
        raise HTTPException(404, f"There is no document {source}.")
    text = (seed.data_dir() / FILES[source]).read_text(encoding="utf-8")
    found = list(HEADING.finditer(text))
    ends = [m.start() for m in found[1:]] + [len(text)]
    return [
        {
            "id": f"{source}-{m.group(1)}",
            "number": int(m.group(1)),
            "title": m.group(2).strip(),
            "text": text[m.start() : end].strip(),
        }
        for m, end in zip(found, ends, strict=True)
    ]


def title(section_id: str) -> str:
    """Return a section's title, such as 9. Repeat claims, or '' if unknown."""
    source, _, number = section_id.partition("-")
    if source not in FILES:
        return ""
    found = [s for s in sections(source) if str(s["number"]) == number]
    return f"{number}. {found[0]['title']}" if found else ""


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
def read_section(source: str, number: int, run_id: str) -> dict[str, Any]:
    """Read one section, recorded on the claim run that read it."""
    found = [s for s in sections(source) if s["number"] == number]
    if not found:
        raise HTTPException(404, f"There is no section {number} in the {source}.")
    with db.connect() as conn:
        store.live_run(conn, run_id)
        conn.execute(
            "INSERT INTO section_reads (run_id, section_id, created_at)"
            " VALUES (?, ?, ?)",
            (run_id, found[0]["id"], clock.stamp()),
        )
    return {"id": found[0]["id"], "title": found[0]["title"], "text": found[0]["text"]}
