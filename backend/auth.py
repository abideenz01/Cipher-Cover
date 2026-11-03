"""Sign-in, sessions, agent service tokens and the check on every operation.

Every route runs guard, which is set on the whole app, so a new route is
refused until permissions.py says who may call it. Only health, login and the
public config are open.

A person signs in with an email and password and gets a session: an HttpOnly
cookie for the dashboard, which must send the CSRF token on every write, or a
bearer token for scripts. Agents get a service token bound to one run: a claim
agent to its claim, a queue agent to its queue run, a voice agent to the person
it acts for. Tokens are stored only as hashes.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend import clock, db, permissions, security_events

router = APIRouter(prefix="/api")

SESSION_COOKIE = "cc_session"
CSRF_COOKIE = "cc_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
LOGIN_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
WRONG = "The email or password is wrong."


@dataclass(frozen=True)
class Principal:
    """Who is calling: a signed-in person or an agent acting under a token."""

    kind: str  # user, claim, queue or voice
    tenant_id: str
    operations: frozenset[str]
    user_id: str = ""
    handler_id: str = ""
    name: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    run_id: str = ""
    claim_id: str = ""

    @property
    def agent(self) -> bool:
        """Whether a model is behind this call."""
        return self.kind != "user"

    @property
    def actor(self) -> str:
        """Name the caller in the security log."""
        if self.kind == "user":
            return self.user_id
        if self.kind == "voice":
            return f"voice:{self.user_id}"
        return f"{self.kind}:{self.run_id}"


def digest(token: str) -> str:
    """Return the hash a token is stored under."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    """Return an scrypt hash with its cost and salt."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against its stored hash in constant time."""
    try:
        scheme, n, r, p, salt, key = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    found = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
    )
    return hmac.compare_digest(found.hex(), key)


def setting(name: str, default: int) -> int:
    """Return a whole-number setting from the environment."""
    return int(os.getenv(name) or default)


def secure_cookies() -> bool:
    """Send cookies over HTTPS only, unless COOKIE_SECURE=0 for local http."""
    return os.getenv("COOKIE_SECURE") != "0"


def later(seconds: float) -> str:
    """Return a time this many seconds from now, as an ISO string."""
    return (clock.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def past(stamp: str) -> bool:
    """Return whether an ISO time has passed."""
    return datetime.fromisoformat(stamp) <= clock.now()


def roles_of(conn: sqlite3.Connection, user_id: str) -> frozenset[str]:
    """Return a user's roles."""
    rows = conn.execute("SELECT role FROM user_roles WHERE user_id = ?", (user_id,))
    return frozenset(r["role"] for r in rows.fetchall())


def person(conn: sqlite3.Connection, user: sqlite3.Row) -> Principal:
    """Return the principal for a signed-in user."""
    roles = roles_of(conn, user["user_id"])
    return Principal(
        kind="user",
        tenant_id=user["tenant_id"],
        operations=permissions.for_roles(roles),
        user_id=user["user_id"],
        handler_id=user["handler_id"],
        name=user["name"],
        roles=roles,
    )


def active_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    """Return an active user's row, or None."""
    return conn.execute(
        "SELECT * FROM users WHERE user_id = ? AND status = 'active'", (user_id,)
    ).fetchone()


def create_session(conn: sqlite3.Connection, user: sqlite3.Row) -> tuple[str, str]:
    """Start a session and return its token and CSRF token."""
    token = "cs_" + secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = clock.stamp()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, tenant_id, csrf_hash, created_at,"
        " last_seen, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
        (
            digest(token),
            user["user_id"],
            user["tenant_id"],
            digest(csrf),
            now,
            now,
            later(setting("SESSION_HOURS", 12) * 3600),
        ),
    )
    return token, csrf


def session_principal(
    conn: sqlite3.Connection, token: str, request: Request, cookie: bool
) -> Principal | None:
    """Return the principal for a live session, refreshing when it was seen."""
    row = conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ? AND revoked_at = ''",
        (digest(token),),
    ).fetchone()
    if row is None or past(row["expires_at"]):
        return None
    idle = timedelta(minutes=setting("SESSION_IDLE_MINUTES", 30))
    if datetime.fromisoformat(row["last_seen"]) + idle <= clock.now():
        return None
    user = active_user(conn, row["user_id"])
    if user is None or user["tenant_id"] != row["tenant_id"]:
        return None
    if cookie and request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(digest(sent), row["csrf_hash"]):
            security_events.record(
                conn,
                row["tenant_id"],
                row["user_id"],
                "csrf",
                request.url.path,
                "denied",
                ip(request),
            )
            raise HTTPException(403, "The request is missing its CSRF token.")
    conn.execute(
        "UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
        (clock.stamp(), row["token_hash"]),
    )
    return person(conn, user)


def issue(  # noqa: PLR0913, PLR0917 - a token's binding, one argument each
    conn: sqlite3.Connection,
    tenant_id: str,
    kind: str,
    seconds: float,
    run_id: str = "",
    claim_id: str = "",
    user_id: str = "",
) -> str:
    """Issue a service token for one agent run and return it. Only its hash is kept."""
    token = "ct_" + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO service_tokens (token_hash, tenant_id, kind, user_id, run_id,"
        " claim_id, created_at, expires_at, revoked_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')",
        (
            digest(token),
            tenant_id,
            kind,
            user_id,
            run_id,
            claim_id,
            clock.stamp(),
            later(seconds),
        ),
    )
    security_events.record(
        conn,
        tenant_id,
        f"voice:{user_id}" if kind == "voice" else "backend",
        "token_issued",
        claim_id or run_id or user_id,
        "ok",
        detail={"kind": kind},
    )
    return token


def revoke(conn: sqlite3.Connection, run_id: str) -> None:
    """Revoke every service token issued for a run."""
    conn.execute(
        "UPDATE service_tokens SET revoked_at = ? WHERE run_id = ? AND revoked_at = ''",
        (clock.stamp(), run_id),
    )


def revoke_token(conn: sqlite3.Connection, token: str) -> None:
    """Revoke one service token."""
    conn.execute(
        "UPDATE service_tokens SET revoked_at = ? WHERE token_hash = ?",
        (clock.stamp(), digest(token)),
    )


def service_principal(conn: sqlite3.Connection, token: str) -> Principal | None:
    """Return the principal for a live service token."""
    row = conn.execute(
        "SELECT * FROM service_tokens WHERE token_hash = ? AND revoked_at = ''",
        (digest(token),),
    ).fetchone()
    if row is None or past(row["expires_at"]):
        return None
    if row["kind"] == "voice":
        user = active_user(conn, row["user_id"])
        if user is None or user["tenant_id"] != row["tenant_id"]:
            return None
        acting = person(conn, user)
        return Principal(
            kind="voice",
            tenant_id=acting.tenant_id,
            operations=acting.operations & permissions.VOICE_AGENT,
            user_id=acting.user_id,
            handler_id=acting.handler_id,
            name=acting.name,
            roles=acting.roles,
        )
    return Principal(
        kind=row["kind"],
        tenant_id=row["tenant_id"],
        operations=permissions.AGENTS[row["kind"]],
        run_id=row["run_id"],
        claim_id=row["claim_id"],
    )


def ip(request: Request) -> str:
    """Return the caller's address."""
    return request.client.host if request.client else ""


def authenticate(conn: sqlite3.Connection, request: Request) -> Principal | None:
    """Return the caller, from a bearer token or the session cookie, or None."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token.startswith("ct_"):
            return service_principal(conn, token)
        return session_principal(conn, token, request, cookie=False)
    cookie = request.cookies.get(SESSION_COOKIE, "")
    return session_principal(conn, cookie, request, cookie=True) if cookie else None


def bound(conn: sqlite3.Connection, who: Principal, request: Request) -> str:
    """Return why an agent's token does not reach this request, or '' if it does."""
    params = dict(request.path_params)
    if "run_id" in request.query_params:
        params.setdefault("run_id", request.query_params["run_id"])
    if who.kind == "claim":
        claim = conn.execute(
            "SELECT policy_id, customer_id FROM claims"
            " WHERE claim_id = ? AND tenant_id = ?",
            (who.claim_id, who.tenant_id),
        ).fetchone()
        if claim is None:
            return "This run's claim is gone."
        allowed = {
            "claim_id": who.claim_id,
            "policy_id": claim["policy_id"],
            "customer_id": claim["customer_id"],
            "run_id": who.run_id,
        }
        for key, value in params.items():
            if key in allowed and value != allowed[key]:
                return f"This run may only work claim {who.claim_id}."
    if who.kind == "queue" and "run_id" in params and params["run_id"] != who.run_id:
        own = conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ? AND queue_run_id = ?"
            " AND tenant_id = ?",
            (params["run_id"], who.run_id, who.tenant_id),
        ).fetchone()
        if own is None:
            return f"This token may only work queue run {who.run_id}."
    return ""


def guard(request: Request) -> Principal | None:
    """Check the caller may call this operation. Set on every route of the app."""
    route = request.scope.get("route")
    operation = getattr(route, "operation_id", None) or ""
    if operation in permissions.PUBLIC:
        return None
    with db.connect() as conn:
        presented = bool(
            request.headers.get("authorization") or request.cookies.get(SESSION_COOKIE)
        )
        try:
            who = authenticate(conn, request)
        except HTTPException:
            conn.commit()
            raise
        if who is None:
            if presented:
                security_events.record(
                    conn, "", "", "authentication", operation, "denied", ip(request)
                )
            conn.commit()
            raise HTTPException(401, "Sign in first.")
        allowed = operation in who.operations
        reason = "" if allowed else permissions.denied(operation)
        reason = reason or bound(conn, who, request)
        if reason:
            security_events.record(
                conn,
                who.tenant_id,
                who.actor,
                "authorization",
                f"{operation} {request.url.path}",
                "denied",
                ip(request),
            )
            conn.commit()
            raise HTTPException(403, reason)
    request.state.principal = who
    return who


def current(found: Annotated[Principal | None, Depends(guard)]) -> Principal:
    """Return the caller of a route that is not public."""
    if found is None:
        raise HTTPException(401, "Sign in first.")
    return found


Who = Annotated[Principal, Depends(current)]


def tenant_config(conn: sqlite3.Connection, tenant_id: str) -> dict[str, Any]:
    """Return a tenant's settings."""
    row = conn.execute(
        "SELECT config FROM tenants WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()
    return json.loads(row["config"]) if row else {}


class Login(BaseModel):
    """An email and password."""

    email: str
    password: str


def throttled(conn: sqlite3.Connection, *keys: str) -> bool:
    """Return whether any key has failed too often lately.

    Failures are kept in the database, so a restart or a second backend
    process does not reset the count.
    """
    since = later(-LOGIN_WINDOW_SECONDS)
    for key in keys:
        failed = conn.execute(
            "SELECT COUNT(*) FROM login_failures WHERE key = ? AND created_at > ?",
            (key, since),
        ).fetchone()[0]
        if failed >= LOGIN_FAILURES:
            return True
    return False


def failed(conn: sqlite3.Connection, *keys: str) -> None:
    """Count a failed sign-in against each key, and forget old failures."""
    conn.execute(
        "DELETE FROM login_failures WHERE created_at <= ?",
        (later(-LOGIN_WINDOW_SECONDS),),
    )
    conn.executemany(
        "INSERT INTO login_failures (key, created_at) VALUES (?, ?)",
        [(key, clock.stamp()) for key in keys],
    )


def me(conn: sqlite3.Connection, who: Principal) -> dict[str, Any]:
    """Describe the signed-in person to the dashboard."""
    tenant = conn.execute(
        "SELECT name FROM tenants WHERE tenant_id = ?", (who.tenant_id,)
    ).fetchone()
    return {
        "user_id": who.user_id,
        "name": who.name,
        "handler_id": who.handler_id,
        "tenant_id": who.tenant_id,
        "tenant_name": tenant["name"] if tenant else "",
        "roles": sorted(who.roles),
        "can_sign_off": "sign_off_claim" in who.operations,
        "can_run": "start_run" in who.operations,
    }


@router.post("/auth/login", operation_id="login")
def login(body: Login, request: Request, response: Response) -> dict[str, Any]:
    """Sign in with an email and password and start a session."""
    email = body.email.strip().lower()
    address = ip(request)
    keys = (f"email:{email}", f"ip:{address}")
    with db.connect() as conn:
        if throttled(conn, *keys):
            raise HTTPException(429, "Too many failed sign-ins. Wait and try again.")
        user = conn.execute(
            "SELECT * FROM users WHERE lower(email) = ? AND status = 'active'",
            (email,),
        ).fetchone()
        stored = user["password_hash"] if user else hash_password(secrets.token_hex())
        if not verify_password(body.password, stored) or user is None:
            failed(conn, *keys)
            security_events.record(
                conn,
                user["tenant_id"] if user else "",
                user["user_id"] if user else "",
                "login",
                email,
                "denied",
                address,
            )
            conn.commit()
            raise HTTPException(401, WRONG)
        token, csrf = create_session(conn, user)
        security_events.record(
            conn, user["tenant_id"], user["user_id"], "login", email, "ok", address
        )
        described = me(conn, person(conn, user))
    hours = setting("SESSION_HOURS", 12) * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=hours,
        httponly=True,
        secure=secure_cookies(),
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=hours, secure=secure_cookies(), samesite="strict"
    )
    return described | {"csrf_token": csrf}


@router.post("/auth/logout", operation_id="logout")
def logout(who: Who, request: Request, response: Response) -> dict[str, str]:
    """End the session."""
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or request.cookies.get(SESSION_COOKIE, "")
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
            (clock.stamp(), digest(token)),
        )
        security_events.record(
            conn, who.tenant_id, who.actor, "logout", who.user_id, "ok", ip(request)
        )
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"status": "signed_out"}


@router.get("/auth/me", operation_id="get_me")
def get_me(who: Who) -> dict[str, Any]:
    """Return the signed-in person, their tenant and what they may do."""
    with db.connect() as conn:
        return me(conn, who)


@router.get("/public-config", operation_id="get_public_config")
def get_public_config() -> dict[str, str]:
    """Return the product name and how to sign in. Holds no tenant data."""
    return {"product": "Cipher Cover", "sign_in": "password"}


@router.get("/security-events", operation_id="list_security_events")
def list_security_events(who: Who) -> list[dict[str, Any]]:
    """Return the tenant's latest security events, newest first."""
    with db.connect() as conn:
        return security_events.latest(conn, who.tenant_id)
