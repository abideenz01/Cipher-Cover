"""The policy wording and the claims manual, split into numbered sections."""

import re
from typing import Any

from fastapi import HTTPException

from backend import seed

FILES = {"wording": "policy_wording.md", "manual": "claims_manual.md"}
NAMES = {"wording": "Section", "manual": "Manual"}
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
    """Return a section's title, such as Manual 9. Repeat claims, or ''."""
    source, _, number = section_id.partition("-")
    if source not in FILES:
        return ""
    found = [s for s in sections(source) if str(s["number"]) == number]
    return f"{NAMES[source]} {number}. {found[0]['title']}" if found else ""
