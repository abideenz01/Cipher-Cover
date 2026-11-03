# PROJECT: CIPHER COVER — PRODUCTION UPGRADE
You are working inside an existing travel insurance claims platform built with Python 3.12, FastAPI, SQLite, LangChain, React 19 and TypeScript.

# Read the README and existing documentation before making changes.

# EXISTING FUNCTIONALITY — DO NOT REBUILD
The product already has:

Queue and claim agents.

Scoped backend API tools.

Deterministic payout calculations in backend/payout.py.

$1,000 autonomous payment restriction.

Human sign-off and send-back.

Evidence-section citation validation.

Agent budgets, retries, leases and recovery.

Idempotent decisions and payments.

Run and claim audit traces.

PII filtering at API boundaries.

Basic SLA tracking.

Held-out evaluation answer keys in data/evals/.

Automated Python, TypeScript and Playwright tests.

Preserve all existing functionality.

# REMAINING FEATURES
Implement these five production capabilities:

# 1. MULTI-TENANT SECURITY
Authentication and secure session management.

Tenant-scoped authorization and data access.

Roles: tenant admin, claims handler, senior handler, SIU investigator and auditor.

Isolation of claims, policies, customers, documents, traces, runs and configurations.

Tenant-aware background jobs and agent tool permissions.

Security audit events.

Cross-tenant access tests.

Evaluate migration from SQLite to PostgreSQL for production deployment.

# 2. SLA, APPEALS AND COMPLAINTS
Extend existing SLA implementation.

Business calendars, holidays, time zones and configurable thresholds.

Escalation and breach notifications.

Complaint registration and lifecycle.

Claim reconsideration and appeals.

Independent human review.

Preserve original decisions and complete decision history.

Customer communication records.

# 3. EXTERNAL VERIFICATION
Build provider-independent API adapters.

Start with flight status, delay and cancellation verification.

Add baggage/PIR and medical-provider verification interfaces.

Introduce typed responses, provenance and timestamps.

Implement timeouts, retries, circuit breakers and caching.

Provide mock adapters for deterministic tests.

Missing external data must produce UNVERIFIED, not an invented negative result.

# 4. FRAUD INTELLIGENCE AND SIU
No sufficiently representative labelled fraud dataset is currently available.

Build rule-based, explainable intelligence first:

Duplicate document detection.

Invoice similarity and duplicate references.

Identity and date inconsistencies.

Repeated incident detection.

Suspicious payment-destination changes.

Provider anomalies where reliable benchmarks exist.

Evidence-backed risk indicators.

SIU case lifecycle and assignment.

Investigation notes and evidence provenance.

Final dispositions: CLEARED, SUBSTANTIATED, INCONCLUSIVE.

Never interpret a referral, decline or unusual claim as confirmed fraud.
Do not train a supervised fraud model on the available 35 claims.

# 5. EVALUATION AND OPERATIONAL ANALYTICS
Extend existing evaluation infrastructure.

Versioned evaluation datasets.

Coverage decision accuracy.

Payout calculation exact-match.

Evidence extraction accuracy.

Referral quality.

Fraud signal evaluation where verified labels exist.

Human override and appeal reversal metrics.

SLA performance.

Claims throughput and handling time.

External integration reliability.

Tenant-level reporting.

Separate actual, synthetic and independently verified data.
Do not fabricate metrics or claim statistical validity from insufficient samples.

# DEVELOPMENT RULES
Inspect actual code before modifying it.

Identify existing partial implementations.

Reuse existing services and components.

Implement one complete vertical slice at a time.

Include migrations, API contracts, UI, authorization, tests and documentation.

Maintain backward compatibility.

Never expose patient information in logs or external model prompts without appropriate authorization.

No fake integrations or production-readiness claims.

Report actual test execution and failures.

# FIRST TASK: AUDIT ONLY
Do not write code yet.

Inspect:

README.md

docs/SPEC.md

docs/ARCHITECTURE.md

docs/HARNESS.md

docs/STATUS.md

backend/

agent/

dashboard/

data/

data/evals/

Return a feature-by-feature gap analysis showing:

Existing implementation and exact files.

Missing functionality.

Database changes required.

Dependencies and architectural risks.

Acceptance criteria.

Implementation sequence.

Also inspect the available claims dataset without printing patient-identifiable information. Assess label quality and distinguish real data from fictional demo data.

Recommend the smallest safe production upgrade path. Do not propose a complete rewrite.