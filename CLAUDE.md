# Cipher Cover — Project Instructions

## Project Context
Read README.md for the product overview.
Read docs/ARCHITECTURE.md for system architecture.
Read docs/SPEC.md for business requirements.
Read docs/STATUS.md for implemented functionality.

## Engineering Rules
- Preserve existing functionality.
- Never rewrite working modules unnecessarily.
- FastAPI backend owns business rules and authorization.
- Agents must not bypass backend controls.
- Financial calculations remain deterministic.
- Protect patient information and tenant data.
- Every feature requires automated tests.
- Reuse existing dependencies where possible.
- Never claim an integration is live unless verified.

## Production Upgrade
The remaining implementation requirements are documented in:
docs/PRODUCTION_UPGRADE_BRIEF.md

Always inspect the existing implementation before proposing changes.
