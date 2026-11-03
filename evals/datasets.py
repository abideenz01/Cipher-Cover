"""The evaluation sets, their versions and where their labels come from.

data/evals/MANIFEST.json records each set's files with a SHA-256 of their
text, its version, n and provenance. A set whose files no longer match the
manifest is refused, so a score is always tied to the exact labels it used.
Rebuild the manifest with `uv run -m evals.datasets --write`, and bump the
version, whenever a set changes.
"""

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent.parent / "data"
MANIFEST = DATA / "evals" / "MANIFEST.json"
VERSION = "2026.11"
PROVENANCE = "synthetic"
LABELLER = (
    "One handler's decision per claim (HND-01, HND-02 or HND-03); no second"
    " rater, no adjudication. Written as a benchmark, not taken from"
    " production claims."
)

# Each set: the claims, policies, customers and decisions files, under data/.
SETS: dict[str, dict[str, str]] = {
    "queue": {
        "claims": "claims.json",
        "policies": "policies.json",
        "customers": "customers.json",
        "decisions": "evals/decisions.json",
    },
    "held_out": {
        "claims": "evals/held_out_claims.json",
        "policies": "policies.json",
        "customers": "customers.json",
        "decisions": "evals/held_out_decisions.json",
    },
    "harder": {
        "claims": "evals/harder/claims.json",
        "policies": "evals/harder/policies.json",
        "customers": "evals/harder/customers.json",
        "decisions": "evals/harder/decisions.json",
    },
    "even_harder": {
        "claims": "evals/even_harder/claims.json",
        "policies": "evals/even_harder/policies.json",
        "customers": "evals/even_harder/customers.json",
        "decisions": "evals/even_harder/decisions.json",
    },
    "security": {
        "claims": "security/claims.json",
        "policies": "security/policies.json",
        "customers": "security/customers.json",
        "decisions": "security/decisions.json",
    },
}

SOURCES = {"policy wording": "wording", "claims manual": "manual"}
MEDICAL = ("medical_record", "medical_bill")


class DatasetChanged(Exception):
    """A set's files no longer match the manifest."""


@dataclass(frozen=True)
class Label:
    """One handler decision, in the same shape for every set."""

    claim_id: str
    decision: str
    payout_cents: int
    sections: tuple[str, ...]
    over_limit: bool
    difficulty: str
    tiny: bool
    claim_type: str
    medical: bool
    reason: str


@dataclass(frozen=True)
class Dataset:
    """A set's records for seeding, and its labels for scoring only."""

    name: str
    version: str
    sha256: str
    provenance: str
    claims: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    customers: list[dict[str, Any]]
    labels: dict[str, Label]


def digest(path: Path) -> str:
    """Hash a file's text with Windows line endings made Unix ones."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read(relative: str) -> Any:
    """Read one JSON file under data/."""
    return json.loads((DATA / relative).read_text(encoding="utf-8"))


def section_ids(reference: str) -> tuple[str, ...]:
    """Turn 'Policy wording, sections 5 and 10' into ('wording-5', 'wording-10')."""
    found: list[str] = []
    for part in re.split(r";|\. ", reference):
        source = next((v for k, v in SOURCES.items() if k in part.lower()), "")
        if source:
            found += [f"{source}-{n}" for n in re.findall(r"\d+", part)]
    return tuple(dict.fromkeys(found))


def manifest_entry(name: str) -> dict[str, Any]:
    """Describe a set as the manifest records it."""
    files = SETS[name]
    return {
        "version": VERSION,
        "provenance": PROVENANCE,
        "labeller": LABELLER,
        "n": len(read(files["decisions"])),
        "files": {f: digest(DATA / f) for f in sorted(set(files.values()))},
    }


def write_manifest() -> None:
    """Record every set's files, n and provenance in MANIFEST.json."""
    entries = {name: manifest_entry(name) for name in SETS}
    MANIFEST.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def set_digest(entry: dict[str, Any]) -> str:
    """Return one hash for all of a set's files."""
    joined = "".join(f"{f}:{h};" for f, h in sorted(entry["files"].items()))
    return hashlib.sha256(joined.encode()).hexdigest()


def load(name: str) -> Dataset:
    """Load a set, refusing it if its files differ from the manifest."""
    if name not in SETS:
        raise KeyError(f"There is no set {name}. Choose from {', '.join(SETS)}.")
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))[name]
    current = manifest_entry(name)
    if current["files"] != recorded["files"]:
        changed = [
            f
            for f in current["files"]
            if current["files"][f] != recorded["files"].get(f)
        ]
        raise DatasetChanged(
            f"Set {name} changed since the manifest: {', '.join(changed)}."
            " Bump VERSION and run `uv run -m evals.datasets --write`."
        )
    files = SETS[name]
    claims = read(files["claims"])
    by_id = {c["claim_id"]: c for c in claims}
    labels = {}
    for raw in read(files["decisions"]):
        claim = by_id[raw["claim_id"]]
        labels[raw["claim_id"]] = Label(
            claim_id=raw["claim_id"],
            decision=raw["decision"],
            payout_cents=round(raw["payout"] * 100),
            sections=section_ids(raw["reference"]),
            over_limit=bool(raw["over_approval_limit"]),
            difficulty=raw["difficulty"],
            tiny=bool(raw["tiny"]),
            claim_type=claim["claim_type"],
            medical=any(d["type"] in MEDICAL for d in claim["documents"]),
            reason=raw["reason"],
        )
    wanted = {c["policy_id"] for c in claims}
    people = {c["customer_id"] for c in claims}
    return Dataset(
        name=name,
        version=recorded["version"],
        sha256=set_digest(recorded),
        provenance=recorded["provenance"],
        claims=[c for c in claims if c["claim_id"] in labels],
        policies=[p for p in read(files["policies"]) if p["policy_id"] in wanted],
        customers=[c for c in read(files["customers"]) if c["customer_id"] in people],
        labels=labels,
    )


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_manifest()
        print(f"Wrote {MANIFEST}")
    else:
        for set_name in SETS:
            data = load(set_name)
            print(f"{set_name}: n={len(data.labels)} {data.provenance} v{data.version}")
