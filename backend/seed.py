"""Load each tenant's records from data/ into the database.

UnderCover's records are at the top of data/. Acme Travel Cover, a second
fictional insurer, is in data/tenants/acme/, with its own company settings.
Neither reads the answer keys or the security claims.
"""

import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any

from backend import auth, clock, db, migrations

DATA = Path(__file__).parent.parent / "data"

# Each tenant: its id, its folder under data/, and its staff sign-ins that are
# not handlers (user id, email, name, roles).
TENANTS: tuple[
    tuple[str, str, tuple[tuple[str, str, str, tuple[str, ...]], ...]], ...
] = (
    (
        "T-UNDERCOVER",
        "",
        (
            ("USR-ADMIN", "admin@undercover.example", "Avery Admin", ("tenant_admin",)),
            ("USR-AUDIT", "auditor@undercover.example", "Rowan Auditor", ("auditor",)),
        ),
    ),
    (
        "T-ACME",
        "tenants/acme",
        (("USR-ACME-ADMIN", "admin@acme.example", "Priya Admin", ("tenant_admin",)),),
    ),
)


def data_dir() -> Path:
    """Return the data folder, from DATA_DIR or data/ at the repo root."""
    return Path(os.getenv("DATA_DIR") or DATA)


def load(name: str, folder: str = "") -> Any:
    """Read one JSON file from the data folder, or a tenant's folder in it."""
    return json.loads((data_dir() / folder / name).read_text(encoding="utf-8"))


def roles_for(handler: dict[str, Any]) -> tuple[str, ...]:
    """Return the roles a handler's sign-in gets, from their record."""
    if "Special Investigations" in handler["role"]:
        return ("siu_investigator",)
    if handler["can_approve_over_limit"]:
        return ("claims_handler", "senior_handler")
    return ("claims_handler",)


def add_user(  # noqa: PLR0913, PLR0917 - one argument per column
    conn: sqlite3.Connection,
    tenant_id: str,
    user_id: str,
    handler_id: str,
    email: str,
    name: str,
    roles: tuple[str, ...],
    password: str,
) -> None:
    """Add one active sign-in with its roles."""
    conn.execute(
        "INSERT INTO users (user_id, tenant_id, handler_id, email, name,"
        " password_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
        (
            user_id,
            tenant_id,
            handler_id,
            email,
            name,
            auth.hash_password(password),
            clock.stamp(),
        ),
    )
    conn.executemany(
        "INSERT INTO user_roles (user_id, role) VALUES (?, ?)",
        [(user_id, role) for role in roles],
    )


def seed_users(
    conn: sqlite3.Connection,
    tenant_id: str,
    folder: str,
    staff: tuple[tuple[str, str, str, tuple[str, ...]], ...],
) -> None:
    """Add a tenant's demo sign-ins once: one per handler, then its staff.

    They share DEMO_PASSWORD when it is set. Otherwise each gets a random
    password, printed once here and stored only as a hash.
    """
    taken = conn.execute(
        "SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()[0]
    if taken:
        return
    users = [
        (
            "USR-" + h["handler_id"].removeprefix("HND-"),
            h["handler_id"],
            h["email"],
            h["name"],
            roles_for(h),
        )
        for h in load("handlers.json", folder)
    ]
    users += [(u, "", email, name, roles) for u, email, name, roles in staff]
    shared = os.getenv("DEMO_PASSWORD")
    for user_id, handler_id, email, name, roles in users:
        password = shared or secrets.token_urlsafe(12)
        add_user(conn, tenant_id, user_id, handler_id, email, name, roles, password)
        if not shared:
            print(f"Demo sign-in {email} password {password}")


def add_tenant(conn: sqlite3.Connection, tenant_id: str, folder: str) -> None:
    """Add a tenant and its own settings, unless it is already there."""
    if not folder:
        return
    tenant = load("tenant.json", folder)
    conn.execute(
        "INSERT OR IGNORE INTO tenants (tenant_id, name, timezone, config)"
        " VALUES (?, ?, ?, ?)",
        (tenant_id, tenant["name"], tenant["timezone"], json.dumps(tenant["config"])),
    )
    conn.execute(
        "INSERT OR IGNORE INTO tenant_reference (tenant_id, name, data)"
        " VALUES (?, 'company', ?)",
        (tenant_id, json.dumps(load("company.json", folder))),
    )


def seed_records(conn: sqlite3.Connection, tenant_id: str, folder: str) -> None:
    """Load a tenant's customers, policies, handlers and claims, if it has none."""
    held = conn.execute(
        "SELECT COUNT(*) FROM claims WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()[0]
    if held:
        return
    conn.executemany(
        "INSERT INTO customers (customer_id, name, data, tenant_id)"
        " VALUES (?, ?, ?, ?)",
        [
            (c["customer_id"], c["name"], json.dumps(c), tenant_id)
            for c in load("customers.json", folder)
        ],
    )
    conn.executemany(
        "INSERT INTO policies (policy_id, customer_id, data, tenant_id)"
        " VALUES (?, ?, ?, ?)",
        [
            (p["policy_id"], p["customer_id"], json.dumps(p), tenant_id)
            for p in load("policies.json", folder)
        ],
    )
    conn.executemany(
        "INSERT INTO handlers (handler_id, name, role, can_approve_over_limit,"
        " tenant_id) VALUES (?, ?, ?, ?, ?)",
        [
            (
                h["handler_id"],
                h["name"],
                h["role"],
                h["can_approve_over_limit"],
                tenant_id,
            )
            for h in load("handlers.json", folder)
        ],
    )
    now = clock.stamp()
    conn.executemany(
        "INSERT INTO claims (claim_id, policy_id, customer_id, data, state,"
        " state_since, tenant_id) VALUES (?, ?, ?, ?, 'waiting', ?, ?)",
        [
            (
                c["claim_id"],
                c["policy_id"],
                c["customer_id"],
                json.dumps(c),
                now,
                tenant_id,
            )
            for c in load("claims.json", folder)
        ],
    )


def seed(reset: bool = False) -> None:
    """Bring the schema up to date and load any tenant that has no records yet."""
    if reset:
        for suffix in ("", "-wal", "-shm"):
            Path(db.path() + suffix).unlink(missing_ok=True)
    with db.connect() as conn:
        migrations.apply(conn)
        for name in ("company", "plans"):
            conn.execute(
                "INSERT OR IGNORE INTO reference VALUES (?, ?)",
                (name, json.dumps(load(f"{name}.json"))),
            )
        for tenant_id, folder, staff in TENANTS:
            add_tenant(conn, tenant_id, folder)
            seed_records(conn, tenant_id, folder)
            seed_users(conn, tenant_id, folder, staff)


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
    print(f"Seeded {db.path()}")
