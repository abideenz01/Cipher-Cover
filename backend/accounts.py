"""A tenant admin manages the tenant's sign-ins and settings.

Everything here stays inside the admin's own tenant. An admin cannot give
anyone an agent's powers, cannot lock themselves out, and gains no right to
sign off or pay by managing users.
"""

import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import auth, clock, db, permissions, security_events, store

router = APIRouter(prefix="/api")
SHORTEST_PASSWORD = 12


class NewUser(BaseModel):
    """A sign-in to add: '' for handler_id if the person is not a handler."""

    email: str
    name: str
    handler_id: str
    roles: list[str]
    password: str


class Roles(BaseModel):
    """The roles a sign-in should have."""

    roles: list[str]


class Settings(BaseModel):
    """The tenant settings an admin may change."""

    external_model_medical: bool


def checked_roles(roles: list[str]) -> list[str]:
    """Return the roles sorted, or refuse one that is not a person's role."""
    unknown = sorted(set(roles) - set(permissions.ROLES))
    if unknown:
        raise HTTPException(422, f"There is no role {', '.join(unknown)}.")
    if not roles:
        raise HTTPException(422, "Give the sign-in at least one role.")
    return sorted(set(roles))


def user_row(conn: sqlite3.Connection, user_id: str, tenant_id: str) -> sqlite3.Row:
    """Return one of the tenant's users, or raise 404."""
    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ? AND tenant_id = ?", (user_id, tenant_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no user {user_id}.")
    return row


def user_view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Return a user for the API, without the password hash."""
    return {
        "user_id": row["user_id"],
        "email": row["email"],
        "name": row["name"],
        "handler_id": row["handler_id"],
        "roles": sorted(auth.roles_of(conn, row["user_id"])),
        "status": row["status"],
    }


def logged(
    conn: sqlite3.Connection,
    who: auth.Principal,
    kind: str,
    target: str,
    request: Request,
) -> None:
    """Record an admin's change in the security log."""
    security_events.record(
        conn, who.tenant_id, who.actor, kind, target, "ok", auth.ip(request)
    )


@router.get("/users", operation_id="list_users")
def list_users(who: auth.Who) -> list[dict[str, Any]]:
    """List the tenant's sign-ins with their roles and status."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE tenant_id = ? ORDER BY user_id", (who.tenant_id,)
        ).fetchall()
        return [user_view(conn, r) for r in rows]


@router.post("/users", operation_id="create_user")
def create_user(body: NewUser, who: auth.Who, request: Request) -> dict[str, Any]:
    """Add a sign-in to the tenant."""
    roles = checked_roles(body.roles)
    email = body.email.strip().lower()
    if "@" not in email or not body.name.strip():
        raise HTTPException(422, "Give a name and an email address.")
    if len(body.password) < SHORTEST_PASSWORD:
        raise HTTPException(422, "The password must be at least 12 characters.")
    user_id = "USR-" + uuid.uuid4().hex[:8].upper()
    with db.connect() as conn:
        if body.handler_id:
            store.handler_row(conn, body.handler_id, who.tenant_id)
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(email) = ?", (email,)
        ).fetchone():
            raise HTTPException(409, "That email already has a sign-in.")
        conn.execute(
            "INSERT INTO users (user_id, tenant_id, handler_id, email, name,"
            " password_hash, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
            (
                user_id,
                who.tenant_id,
                body.handler_id,
                email,
                body.name.strip(),
                auth.hash_password(body.password),
                clock.stamp(),
            ),
        )
        conn.executemany(
            "INSERT INTO user_roles (user_id, role) VALUES (?, ?)",
            [(user_id, role) for role in roles],
        )
        logged(conn, who, "user_created", user_id, request)
        return user_view(conn, user_row(conn, user_id, who.tenant_id))


@router.put("/users/{user_id}/roles", operation_id="set_user_roles")
def set_user_roles(
    user_id: str, body: Roles, who: auth.Who, request: Request
) -> dict[str, Any]:
    """Replace a sign-in's roles."""
    roles = checked_roles(body.roles)
    if user_id == who.user_id and "tenant_admin" not in roles:
        raise HTTPException(409, "You cannot remove your own admin role.")
    with db.connect() as conn:
        user_row(conn, user_id, who.tenant_id)
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_roles (user_id, role) VALUES (?, ?)",
            [(user_id, role) for role in roles],
        )
        logged(conn, who, "roles_changed", f"{user_id} {','.join(roles)}", request)
        return user_view(conn, user_row(conn, user_id, who.tenant_id))


def set_status(user_id: str, status: str, who: auth.Principal, request: Request) -> Any:
    """Turn a sign-in on or off. Turning it off ends its sessions."""
    if user_id == who.user_id:
        raise HTTPException(409, "You cannot disable your own sign-in.")
    with db.connect() as conn:
        user_row(conn, user_id, who.tenant_id)
        conn.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
        if status == "disabled":
            conn.execute(
                "UPDATE sessions SET revoked_at = ?"
                " WHERE user_id = ? AND revoked_at = ''",
                (clock.stamp(), user_id),
            )
        logged(conn, who, f"user_{status}", user_id, request)
        return user_view(conn, user_row(conn, user_id, who.tenant_id))


@router.post("/users/{user_id}/disable", operation_id="disable_user")
def disable_user(user_id: str, who: auth.Who, request: Request) -> dict[str, Any]:
    """Turn a sign-in off and end its sessions."""
    return set_status(user_id, "disabled", who, request)


@router.post("/users/{user_id}/enable", operation_id="enable_user")
def enable_user(user_id: str, who: auth.Who, request: Request) -> dict[str, Any]:
    """Turn a sign-in back on."""
    return set_status(user_id, "active", who, request)


def settings_view(conn: sqlite3.Connection, tenant_id: str) -> dict[str, Any]:
    """Return a tenant's name, time zone and settings."""
    row = conn.execute(
        "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()
    config = json.loads(row["config"])
    company = db.reference(conn, "company", tenant_id)
    return {
        "name": row["name"],
        "timezone": row["timezone"],
        "external_model_medical": bool(config.get("external_model_medical")),
        "payout_approval_limit": company["payout_approval_limit"],
        "sign_off_sla_hours": company["sign_off_sla_hours"],
    }


@router.get("/tenant/settings", operation_id="get_tenant_settings")
def get_tenant_settings(who: auth.Who) -> dict[str, Any]:
    """Return the tenant's settings."""
    with db.connect() as conn:
        return settings_view(conn, who.tenant_id)


@router.put("/tenant/settings", operation_id="update_tenant_settings")
def update_tenant_settings(
    body: Settings, who: auth.Who, request: Request
) -> dict[str, Any]:
    """Change whether medical documents may be sent to the model."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT config FROM tenants WHERE tenant_id = ?", (who.tenant_id,)
        ).fetchone()
        config = json.loads(row["config"]) | {
            "external_model_medical": body.external_model_medical
        }
        conn.execute(
            "UPDATE tenants SET config = ? WHERE tenant_id = ?",
            (json.dumps(config), who.tenant_id),
        )
        logged(
            conn,
            who,
            "settings_changed",
            f"external_model_medical={body.external_model_medical}",
            request,
        )
        return settings_view(conn, who.tenant_id)
