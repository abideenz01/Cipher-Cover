"""Load UnderCover's records from data/ into the database."""

import json
import os
import sys
from pathlib import Path
from typing import Any

from backend import clock, db, migrations

DATA = Path(__file__).parent.parent / "data"


def data_dir() -> Path:
    """Return the data folder, from DATA_DIR or data/ at the repo root."""
    return Path(os.getenv("DATA_DIR") or DATA)


def load(name: str) -> Any:
    """Read one JSON file from the data folder."""
    return json.loads((data_dir() / name).read_text(encoding="utf-8"))


def seed(reset: bool = False) -> None:
    """Bring the schema up to date and load the records into an empty database."""
    if reset:
        Path(db.path()).unlink(missing_ok=True)
    with db.connect() as conn:
        migrations.apply(conn)
        if conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]:
            return
        for name in ("company", "plans"):
            conn.execute(
                "INSERT INTO reference VALUES (?, ?)",
                (name, json.dumps(load(f"{name}.json"))),
            )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [
                (c["customer_id"], c["name"], json.dumps(c))
                for c in load("customers.json")
            ],
        )
        conn.executemany(
            "INSERT INTO policies VALUES (?, ?, ?)",
            [
                (p["policy_id"], p["customer_id"], json.dumps(p))
                for p in load("policies.json")
            ],
        )
        conn.executemany(
            "INSERT INTO handlers VALUES (?, ?, ?, ?)",
            [
                (h["handler_id"], h["name"], h["role"], h["can_approve_over_limit"])
                for h in load("handlers.json")
            ],
        )
        now = clock.stamp()
        conn.executemany(
            "INSERT INTO claims (claim_id, policy_id, customer_id, data, state,"
            " state_since) VALUES (?, ?, ?, ?, 'waiting', ?)",
            [
                (c["claim_id"], c["policy_id"], c["customer_id"], json.dumps(c), now)
                for c in load("claims.json")
            ],
        )


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
    print(f"Seeded {db.path()}")
