"""Who may call which operation, by role and by agent kind.

Every route is named by its operation_id. A person's operations are the union
of their roles' operations. An agent's operations are fixed by its kind, and a
voice agent gets only what the person it acts for may also do.
"""

PUBLIC = frozenset({"health", "login", "get_public_config"})

READ = frozenset(
    {
        "get_me",
        "logout",
        "list_claims",
        "get_claim",
        "get_policy",
        "get_customer_history",
        "get_policy_wording",
        "get_instructions",
        "list_handlers",
        "list_signoffs",
        "list_sections",
        "get_run",
        "list_run_events",
        "list_queue_runs",
        "get_queue_run",
        "list_queue_run_events",
        "get_voice_config",
    }
)

VOICE = frozenset(
    {
        "voice_turn",
        "list_voice_turns",
        "get_voice_instructions",
        "search_claims",
        "get_claim_brief",
        "get_decision_brief",
        "get_run_status_brief",
        "get_analytics_brief",
    }
)

HANDLING = frozenset(
    {"start_run", "start_queue_run", "stop_queue_run", "send_back_claim"}
)

SIGNING = frozenset({"sign_off_claim", "request_signoff"})

AUDIT = frozenset({"list_security_events", "list_users", "get_tenant_settings"})

ADMINISTERING = frozenset(
    {
        "create_user",
        "set_user_roles",
        "disable_user",
        "enable_user",
        "update_tenant_settings",
    }
)

ROLES: dict[str, frozenset[str]] = {
    "claims_handler": READ | VOICE | HANDLING,
    "senior_handler": READ | VOICE | HANDLING | SIGNING,
    "siu_investigator": READ,
    "auditor": READ | AUDIT,
    "tenant_admin": READ | AUDIT | ADMINISTERING,
}

CLAIM_AGENT = frozenset(
    {
        "get_instructions",
        "get_claim",
        "get_policy",
        "get_customer_history",
        "list_sections",
        "read_section",
        "calculate_payout",
        "record_decision",
        "pay_claim",
    }
)

QUEUE_AGENT = frozenset(
    {
        "get_instructions",
        "get_queue_run",
        "list_claims",
        "write_todos",
        "begin_attempt",
        "finish_attempt",
        "finish_queue_run",
    }
)

VOICE_AGENT = frozenset(
    {
        "get_voice_instructions",
        "search_claims",
        "get_claim_brief",
        "get_decision_brief",
        "list_signoffs",
        "get_run_status_brief",
        "get_analytics_brief",
        "start_run",
        "request_signoff",
    }
)

AGENTS = {"claim": CLAIM_AGENT, "queue": QUEUE_AGENT}

DENIED = {
    "sign_off_claim": "You are not allowed to sign off payouts.",
    "request_signoff": "You are not allowed to sign off payouts.",
}


def denied(operation: str) -> str:
    """Return the refusal for an operation the caller may not call."""
    return DENIED.get(operation, "You are not allowed to do that.")


def for_roles(roles: frozenset[str]) -> frozenset[str]:
    """Return every operation any of these roles may call."""
    allowed: frozenset[str] = frozenset()
    for role in roles:
        allowed |= ROLES.get(role, frozenset())
    return allowed
