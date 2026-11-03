# Cipher Cover: production upgrade audit and implementation plan

## Context

`docs/PRODUCTION_UPGRADE_BRIEF.md` asks for five production capabilities on top of the finished agent harness: multi-tenant security; SLA, appeals and complaints; external verification; fraud intelligence and SIU; and evaluation and operational analytics. This document audits the repository as it stands on branch `cipher` (commit 8832154) and gives a plan, vertical slice by vertical slice, with no rewrite. No files were changed during the audit.

Note: the brief and README call the dataset "35 claims", but it holds 117 labelled claims across six sets (see section A).

---

## A. What the audit found

### Platform facts that constrain everything

| Area | What exists | File |
|---|---|---|
| DB | Raw `sqlite3`. 16 tables are created with `CREATE TABLE IF NOT EXISTS` in one `SCHEMA` string. There are **no migrations**: a schema change means `seed --reset`. | `backend/db.py`, `backend/seed.py` |
| IDs | Global text primary keys (`claim_id`, `policy_id`, `customer_id`, `handler_id`), with no owner column on any table | `backend/db.py` |
| Identity | **None.** `handler_id` is sent in the request body and trusted (`SignOff`, `SendBack`, voice `Turn`, `SignOffRequest`). The dashboard lets anyone pick any handler from a dropdown. | `backend/signoff.py`, `backend/voice/routes.py`, `dashboard/src/views/SignOff.tsx` |
| Agent → API | The agents call `http://127.0.0.1:8000` with no credentials. The `run_id` works as a capability: `decisions.holds()` and `store.live_run()` check it. | `agent/main.py:call`, `backend/decisions.py:holds` |
| Background jobs | Threads through `runs.spawn` and `queue_runs.work`. On startup, `queue_runs.recover()` frees claims left in progress. | `backend/runs.py`, `backend/queue_runs.py` |
| Clock | `backend/clock.py` gives UTC `now()` and `stamp()` and is replaced in tests | `backend/clock.py` |
| Deps already locked | `psycopg[binary]`, `langgraph-checkpoint-postgres` (main group); `pyjwt[crypto]`, `sqlalchemy` (`server` group, not installed by default) | `pyproject.toml` |
| Tests | 104 Python test functions (128 with parametrize), vitest, and 14 Playwright tests. Each test gets a fresh seeded DB from `conftest.py`. | `conftest.py`, `backend/tests/`, `agent/tests/`, `e2e/` |

### Security boundary findings (already live today)

1. **PII filter is partial.** Email, phone, date of birth and address are filtered (`backend/tests/test_read.py:PERSONAL`). But `list_claims` and `get_claim` return the customer's **full name** (`claims.py:summary`), and so does `get_customer_history`.
2. **Medical records go to the external model.** `get_claim` returns document `content` with nothing removed. The 6 `emergency_medical` claims include `medical_record` and `medical_bill` documents, and these reach OpenRouter through the claim agent. This conflicts with the brief's rule against putting patient information in external prompts without authorization. **This is the most important finding.**
3. **The answer keys are well isolated.** `seed.py` loads only queue files. `test_read.py` and `test_documents.py` check that `evals/` and `security/` cannot be reached and do not appear in the instructions. This must be kept.
4. **No authorization on any route.** The queue, runs, sign-off, voice and analytics routes are all open.

### Dataset assessment (inspected by script; no PII printed)

| Set | Claims | Labels | Mix | Notes |
|---|---|---|---|---|
| `data/claims.json` + `evals/decisions.json` | 35 | 35 | 20 approve / 7 decline / 8 refer; 15 routine / 12 hard / 8 manual; 6 over limit; 5 `tiny` | All `status: open`, submitted 2026-06-24 to 2026-10-14 |
| `evals/held_out_*` | 25 | 25 | 14 / 5 / 6 | Generalization check |
| `evals/harder/` | 25 | 25 | 14 / 5 / 6, all hard, 12 over limit | Has `tempts`, no `failure_class` |
| `evals/even_harder/` | 25 | 25 | 17 / 6 / 2 | Depends on `knowledge.json` |
| `evals/followup_decisions.json` | 4 | 4 | all approve | Follow-ups are **not seeded** |
| `security/` | 3 | 3 | 2 decline / 1 approve | Prompt-injection claims |

- **Real or fictional:** all of it is **fictional demo data** (`data/README.md`: "Everything here is invented"). `customers.json` has PII-shaped fields (email, phone, DOB, address) that must still be handled as PII, because the same code paths will carry real data.
- **Label quality:** each label is one handler's decision (HND-01/02/03). There is no second rater, no adjudication and no recorded inter-rater agreement. Each label has `decision`, `payout`, step-by-step `calculation`, `reference` (a section string), `reason`, `difficulty`, `needs` and `tiny`. **The schema differs between sets** (`failure_class` only in the queue and held-out sets, `tempts` only in harder and even_harder). The `tempts`, `tone` and `tiny` fields show the sets were **written as a benchmark**, not taken from production history. They should be classed as **synthetic, handler-authored**, not "actual" or "independently verified".
- **Fraud labels:** none. Some claims look fraud-adjacent: CLM-1016 (the medical history contradicts the story → decline), CLM-1019 (third claim in 12 months → refer), CLM-1024 (the same loss already paid → refer). These are **handling outcomes, not fraud findings**, and must not be used as fraud ground truth. No identical document content appears across the queue. The largest number of claims for one customer is 2. There is **no payment-destination data** anywhere.
- **External-verification inputs:** 15 claims mention flights, but only in free text (no structured flight number or date). 4 mention a PIR. No time zones anywhere.
- **Statistical caution:** n=35 per set, with some categories under 10 (for example 8 refers, 3 cancellations). Any metric must report n and a confidence interval (Wilson) and must not claim significance.

### Gap analysis by feature

**1. Multi-tenant security**
- *Exists:* the run-scoped write check (`decisions.holds`), the queue agent's lack of pay tools, and the PII filter for contact fields. `handlers.role` and `can_approve_over_limit` act as a rough role model. HND-05 is labelled SIU in data but has no powers.
- *Partial:* the role in data is not enforced, except for the sign-off flag.
- *Missing:* users and credentials, sessions, a `tenants` table, `tenant_id` on every row, a role and permission matrix, an authorization dependency on routes, agent service credentials tied to tenant and run, tenant-aware recovery and queue selection, a `security_events` table, cross-tenant tests, and a Postgres evaluation.

**2. SLA, appeals and complaints**
- *Exists:* the sign-off SLA only (`company.sign_off_sla_hours`, `overdue` computed in `signoff.list_signoffs` on wall-clock UTC hours); `sendbacks`; decisions that are only ever inserted (history is kept already, and `latest_decision` takes the highest id).
- *Missing:* business calendars, holidays, time zones, per-tenant thresholds, SLAs for other stages (acknowledge, decide), escalation and breach notifications, complaints, appeals and reconsideration, independent reviewer rules, communication records, and a decision-supersession link.

**3. External verification:** nothing exists. There is no outbound HTTP besides OpenRouter (`httpx` is available).

**4. Fraud intelligence and SIU:** nothing exists beyond the manual's repeat-claim rule (`company.repeat_claim_review`) and `previous_claims` in customer history.

**5. Evaluation and analytics**
- *Exists:* the answer keys plus isolation tests; per-run tokens, time and attempts (`runs`, `queue_runs`); `get_analytics_brief` (counts by state and total paid); one manual live run in `docs/STATUS.md`.
- *Missing:* **no eval runner or scorer exists in code**. Also missing: dataset versioning, provenance classes, metrics, reports, and tenant-level reporting.

---

## B. Architectural decisions (recommended)

1. **Migrations before features.** Add a small stdlib migration runner: a `schema_migrations` table and ordered `backend/migrations/NNNN_*.py` files, run in `seed.seed()` before seeding. The current `SCHEMA` becomes migration 0001 unchanged. This replaces "rebuild with `--reset`" and is the precondition for every database change below.
2. **Tenancy in SQLite (an interim measure, not the production guarantee): add a `tenant_id` column, keep the global keys.** Tenant filters in the application are a defence for development and pilot use only. They are **not** enterprise-grade isolation, and no doc, README or status may say they are. Add `tenant_id TEXT NOT NULL DEFAULT 'T-UNDERCOVER'` to every business table. Keep the existing global text primary keys, and give new records globally unique ids (prefix or UUID). This avoids rebuilding tables to change primary keys and keeps every current id, test and URL valid. Enforce isolation in **one** place: a `TenantScope` passed into `store` helpers, so that every query has `AND tenant_id = ?`. Add a test that checks each table and query.
3. **Auth with the standard library, no new service.** Accounts with `hashlib.scrypt` password hashes. Opaque random session tokens, stored **hashed** in a `sessions` table, with idle and absolute expiry, sent in an `HttpOnly; SameSite=Strict; Secure` cookie (Secure off for localhost), plus a CSRF header check on writes. A FastAPI dependency `current_principal()` gives `(user, tenant_id, roles)`. Leave room for an OIDC provider later, but do not build it now.
4. **Agents get run-scoped service tokens.** `lease()` creates a short-lived token bound to `(tenant_id, queue_run_id or run_id, claim_id, allowed operation_ids)`. `agent/main.py:call` sends it as `Authorization: Bearer`. The backend checks it in the same dependency, so agents still cannot bypass backend controls, and the existing `holds()` check stays.
5. **PostgreSQL with Row-Level Security is a gate for production deployment.** No production deployment holding more than one tenant's data goes ahead until Postgres RLS on `tenant_id` is in place and tested (a session variable set per request and per service token; policies on every tenant table; the app's DB role cannot bypass RLS). Until then the product is documented as single-tenant or pilot only. **Decide in a written record now, migrate in a dedicated later phase.** Write `docs/ADR_POSTGRES.md` covering the gaps today: no row-level security, a single writer, thread workers and file locks. The proposed path: SQL kept portable, Postgres RLS on `tenant_id`, `psycopg` (already locked). Do **not** migrate in this upgrade. All 16+ modules use `sqlite3` with `?` placeholders, so a switch now is a rewrite.
6. **External data is a typed port with an adapter.** `VerificationResult{status: VERIFIED|CONTRADICTED|UNVERIFIED, data, provider, fetched_at, request_hash, error}`. Missing data or an outage gives `UNVERIFIED`, never a negative result. Only mock adapters ship. A real provider needs credentials and verification before it is called live.
7. **Fraud means indicators, never verdicts.** Deterministic rules produce `risk_indicators` rows, each with evidence references. The words "fraud" and "fraudulent" never appear in agent-facing or customer-facing output. Only a closed SIU case with disposition SUBSTANTIATED records a finding, and only a human can set it.
8. **Patient data gate.** A per-tenant config `external_model_medical: false` by default. When it is false, `get_claim` for agent principals replaces the content of `medical_record` and `medical_bill` documents with a structured, redacted summary and a placeholder: `[medical document withheld: N chars]`. Human principals with the right role see the full text. **This changes current agent behavior on 6 claims** (see open question 1).

---

## C. Database changes (cumulative)

| Migration | Tables / columns |
|---|---|
| 0001_baseline | current `SCHEMA`, unchanged |
| 0002_tenancy | `tenants(tenant_id, name, timezone, config JSON)`; `tenant_id` column + index on customers, policies, handlers, claims, calculations, decisions, payments, signoffs, sendbacks, runs, queue_runs, section_reads, run_events, signoff_requests, voice_turns; `reference` becomes `(tenant_id, name)` through a new `tenant_reference` table (`db.reference` reads it with a fallback) |
| 0003_auth | `users(user_id, tenant_id, handler_id NULL, email, password_hash, status)`, `user_roles(user_id, role)`, `sessions(token_hash, user_id, tenant_id, created_at, last_seen, expires_at, revoked_at)`, `service_tokens(token_hash, tenant_id, run_id, claim_id, scopes, expires_at)`, `security_events(id, tenant_id, actor, kind, target, outcome, ip, created_at, detail)` |
| 0004_sla | `business_calendars(tenant_id, calendar_id, timezone, workdays, hours)`, `holidays(calendar_id, date, name)`, `sla_policies(tenant_id, stage, threshold_business_hours, warn_at_pct, escalate_to_role)`, `sla_clocks(id, tenant_id, claim_id, stage, started_at, due_at, paused_at, met_at, breached_at)`, `notifications(id, tenant_id, kind, target_role, claim_id, payload, created_at, acked_at)` |
| 0005_complaints_appeals | `complaints(id, tenant_id, claim_id NULL, channel, category, status, received_at, acknowledged_at, resolved_at, outcome, handler_id)`, `appeals(id, tenant_id, claim_id, original_decision_id, grounds, status, reviewer_user_id, outcome, new_decision_id, ...)`, `decisions.supersedes_id NULL` + `decisions.origin ('agent'|'human_review'|'appeal')`, `communications(id, tenant_id, claim_id, complaint_id, appeal_id, direction, channel, summary, created_by, created_at)` (a record of contact only; nothing is sent) |
| 0006_verification | `verifications(id, tenant_id, claim_id, kind, request JSON, status, result JSON, provider, fetched_at, latency_ms, attempts, error)`, `verification_cache(key, tenant_id, result, expires_at)` |
| 0007_fraud_siu | `document_fingerprints(tenant_id, claim_id, doc_index, sha256_normalized, simhash, invoice_ref)`, `risk_indicators(id, tenant_id, claim_id, rule_id, rule_version, severity, evidence JSON, created_at, dismissed_by, dismissed_reason)`, `payment_destinations(id, tenant_id, customer_id, masked_ref, hash, created_at, created_by)`, `siu_cases(id, tenant_id, claim_id, status, assignee_user_id, opened_by, opened_at, disposition NULL, closed_at)`, `siu_notes(id, case_id, author, body, evidence JSON, created_at)` |
| 0008_evals | `eval_datasets(dataset_id, version, sha256, provenance ('actual'|'synthetic'|'verified'), n)`, `eval_runs(id, tenant_id, dataset_id, version, model, fingerprint, started_at, ...)`, `eval_results(eval_run_id, claim_id, metric, expected, actual, match)` |

Every migration is additive (new tables, or nullable or defaulted columns), so existing data and tests keep working.

---

## D. Implementation sequence and file-by-file plan

**Order and why:** Phase 0 (foundation) → **1 Security first** → 5a eval baseline → 2 SLA/appeals → 3 verification → 4 fraud/SIU → 5b analytics. Security goes first because every later feature adds tenant-owned tables and role-gated routes. Building them before tenancy would mean fitting both onto each feature afterwards. A small eval scorer (5a) comes right after, so that regressions in decision or payout quality from later slices can be measured.

### Phase 0: foundation (no behavior change). **Done 2026-11-03**
- `backend/migrations/__init__.py` (new): `apply(conn)` runs pending migrations from an explicit `MIGRATIONS` list (modules `mNNNN_*.py`, since a module name can't start with a digit) in order inside one transaction, and records them in `schema_migrations`. It refuses a database that records a migration newer than the code.
- `backend/migrations/m0001_baseline.py` (new): creates `db.SCHEMA`, or adopts an existing matching schema.
- `backend/migrations/schema.py` (new): `SchemaMismatch` and the comparison of tables and columns (type, NOT NULL, default, primary key) against the schema built in a scratch in-memory database.
- `backend/db.py`: `SCHEMA` stays where it is (0001 reads it), so nothing that imports it breaks. The connection settings are not changed in Phase 0. WAL is deferred to Phase 2, when background sweeps arrive.
- `backend/seed.py`: call `migrations.apply` before seeding. `--reset` is kept.
- `backend/tests/test_migrations.py` (new).
- **0001 checks an existing schema before marking itself applied.** If the database has no tables, 0001 creates the schema. If every expected table and column is there, 0001 is recorded as applied. If anything is missing or different (missing tables, missing or extra columns, or a pilot-era schema), the runner **raises `SchemaMismatch`**, names each difference, points to `seed --reset`, and records nothing. It never accepts an incomplete schema without saying so.
- **Accept:**
  - [x] A fresh database reaches the head version (`test_a_fresh_database_reaches_the_head_version`).
  - [x] A complete harness database is adopted as 0001 with no data loss (test, plus a copy of the local `undercover.db`: 35 claims and 5 decisions kept).
  - [x] An incomplete or incompatible database is refused with a clear error and nothing recorded (missing column, wrong type, missing table, extra column, extra table, newer migration).
  - [x] All existing tests pass unchanged (Python: 139 passed, 98.9% coverage; ruff and pyright clean).
  - [x] Running the migrations twice changes nothing.
  - [x] Playwright 14 of 14, after fixing `.env` taking precedence over the e2e settings (`agent/main.py:load_settings`).

### Phase 1: multi-tenant security. **Done 2026-11-03**
- `backend/migrations/0002_tenancy.py`, `0003_auth.py`.
- `backend/auth.py` (new): password hashing, sessions, `current_principal`, `require(permission)`, CSRF check, login rate limit, and the login, logout and me routes (`operation_id`s `login`, `logout`, `get_me`).
- `backend/permissions.py` (new): the role → permission matrix. Roles: tenant_admin, claims_handler, senior_handler, siu_investigator, auditor, plus the internal `agent_queue` and `agent_claim` roles. Auditors are read-only, including traces. Only senior_handler may sign off. siu_investigator gets SIU routes and full claim documents. tenant_admin can manage users and config but **cannot sign off or pay**.
- `backend/security_events.py` (new): `record(conn, principal, kind, target, outcome)` for login success and failure, denied access, sign-off, role changes, config changes and token use.
- `backend/store.py`: every helper takes `tenant_id`. `claim_row`, `policy_data` and `handler_row` filter by it and **return 404, not 403, across tenants** (no existence oracle).
- `backend/claims.py`, `decisions.py`, `signoff.py`, `runs.py`, `queue_runs.py`, `documents.py`, `voice/routes.py`: add `Depends(require(...))`. Take `handler_id` from the principal; a body `handler_id` is ignored or must match. Scope `eligible()`, `recover()`, `missed()` and the "one live run" rule per tenant.
- `backend/runs.py:lease`: create the service token. `backend/runner.py` passes it to the agents.
- `agent/main.py:call`, `agent/queue.py`: send `Authorization`. The claim token's scopes are its 8 tools on its own claim. The queue token's scopes are its 5 tools.
- `backend/claims.py`: the medical-document gate (decision B8), and `customer_name` reduced to a short name for agent principals.
- `backend/seed.py`: seed the tenant `T-UNDERCOVER` plus a second fixture tenant `T-ACME` (test-only data under `backend/tests/fixtures/`, never in `data/evals/`), and demo users mapped to HND-01 to HND-05 with dev-only passwords printed once.
- `dashboard/src/views/Login.tsx` (new), `api.ts` (credentials: include, CSRF header, 401 → login), `App.tsx` (session gate, role-aware rail), `SignOff.tsx` (handler dropdown removed; acts as the signed-in user).
- `e2e/`: a login fixture. Existing specs log in first.
- `docs/ADR_POSTGRES.md` (new), `docs/SPEC.md` ("No sign-in" goes), `ARCHITECTURE.md`, `STATUS.md`.
- **Tests (`backend/tests/test_tenancy.py`, `test_auth.py`):** a parametrized test over **every** operation in `app.openapi()` checks that it returns 401 with no session, the permission rules for each role, and that a T-ACME user gets 404 for every T-UNDERCOVER claim, policy, customer, run, queue run, trace and config. A claim-agent token cannot touch another claim, another tenant, or a sign-off. A queue token cannot pay. Recovery on startup frees only the right tenant's claims. Session expiry and revocation. Security events written for each denial. An OpenAPI walk asserts that no route lacks an authorization dependency.
- **Unauthenticated surface:** only `health`, `login` and a `get_public_config` endpoint that is genuinely public (product name, auth method, version; checked by a test to hold no secrets, keys, tenant names, tenant config or feature flags tied to a tenant). **Every voice operation, `voice/config` included, requires authentication.**
- **Accept:** all existing behavior is kept for a signed-in senior handler. No route is reachable without auth except `health`, `login` and `get_public_config`. The docs state that tenant isolation is application-level for now and that Postgres RLS is a deployment gate. No cross-tenant read or write succeeds in tests. Medical document text does not appear in any agent tool response unless the tenant has opted in. `npm run check` is green.
- **As built** (where it differs from the list above):
  - `guard` is set on the whole app (`FastAPI(dependencies=[Depends(auth.guard)])`) and reads the route's `operation_id`, so no route can be added without an entry in `permissions.py`. There is no per-route `require(...)` to forget. Agent kinds are token kinds (`claim`, `queue`, `voice`), not roles.
  - The second tenant `T-ACME` is seeded from `data/tenants/acme/`: fictional, 10 claims, kept apart from the labelled UnderCover queue.
  - `/docs` and `/openapi.json` sit outside the routes, so they are off unless `API_DOCS=1`.
  - Not built in the first pass, then added on 2026-11-03: user and settings management (`backend/accounts.py`, the Admin view), a seeded second tenant (`data/tenants/acme/`), per-tenant company settings and a stored sign-in throttle (migration 0004), and WAL. SIU routes stay in Phase 4. Startup recovery frees every tenant's claims, because a restart ends every tenant's runs.
  - The claim instructions don't yet say what to do with a withheld medical document. Measure the six medical claims in Phase 5a before changing them.
  - [x] All existing behavior kept for a signed-in senior handler (every earlier test passes, signed in or with an agent token).
  - [x] Only `health`, `login` and `get_public_config` answer without sign-in (`test_every_operation_but_three_needs_sign_in`, over every operation in `app.openapi()`).
  - [x] The docs say isolation is application-level and Postgres RLS is a deployment gate (`docs/ADR_POSTGRES.md`, `SPEC.md`, `ARCHITECTURE.md`, `STATUS.md`).
  - [x] No cross-tenant read or write succeeds (`test_tenancy.py`: 404 for each claim, policy, customer, run, trace, queue run, brief, sign-off, send-back and sign-off request; lists, search and analytics are per tenant; a T-ACME run's rows all carry T-ACME).
  - [x] Agent tokens: a claim token reaches only its claim, policy and customer, and ends with its run, on expiry and on restart; a queue token can't pay, decide or touch another queue run; a voice token has only what its person has.
  - [x] Medical text reaches no agent unless the tenant opts in (`test_medical_documents_never_reach_an_agent_unless_the_tenant_allows_it`).
  - [x] Sessions: cookie flags, CSRF on writes, idle and absolute expiry, sign-out, disabled users, throttled failures, hashes only (`test_auth.py`).
  - [x] `npm run check` green: Python 235 passed at 98.3%, TypeScript 38 at 96.5%, Playwright 14 of 14. After closing the gaps: Python 262 passed at 99%, TypeScript 42 at 96.3%, Playwright 16 of 16.

### Phase 5a: eval baseline (offline; the agent never sees keys). **Done 2026-11-03 (scripted model)**
- `evals/` package (new, **outside** `backend/` so the API can't serve it): `datasets.py` (manifest with sha256, version, provenance and n; normalizes the different schemas), `score.py` (coverage-decision accuracy, payout exact-match in cents against `calculation`, cited-section overlap against `reference`, referral precision and recall. Binary proportions get Wilson CIs. Continuous metrics (payout error in cents, handling time, latency) get median, p90 and a bootstrap CI for the median when n permits, otherwise only n and the range. Every metric reports n.), `run.py` (CLI: `uv run -m evals.run --set queue --tiny`, seeds a temporary DB from the set, runs the agent (stub by default), scores, writes `eval_runs` and `eval_results` to a **separate** eval DB).
- `data/evals/MANIFEST.json` (new): every set labelled `synthetic` with `labeller: single handler`.
- `evals/tests/` and an isolation test that `backend` never imports `evals`.
- **Accept:** a stub run scores deterministically (a fixed expected score is asserted). Reports print n and CI and mark any slice under 30 as "insufficient sample". Tests show that no answer-key text reaches an agent prompt.
- **As built:** `evals/datasets.py`, `stats.py`, `score.py`, `run.py`, `store.py` and `compare.py`, with tests in `evals/tests/`. The manifest is at `data/evals/MANIFEST.json`. Each run seeds a temporary backend from a staged folder holding no labels, and works each claim through the API under a claim token, as in production. The eval tables are in a separate `evals.db`, not migration 0008, so no score sits in the backend database. `--medical on|off` lets the gate be measured. The follow-up decisions and voice scenarios are not evaluated yet. `docs/EVALUATION.md` has the method and the baseline.
  - [x] The stub run scores the same every time, asserted in `test_the_scripted_model_scores_the_same_every_time`.
  - [x] Reports give n and a Wilson CI for each proportion, median, p90, range and a bootstrap CI for continuous measures, and mark n under 30.
  - [x] No answer-key text reaches a prompt (`test_no_answer_key_reaches_the_agent`), the staged data holds no labels, and backend and agent never import `evals`.
  - [ ] A real-model baseline, with medical documents off and on. This costs money, so it waits for the owner to run it.

### Phase 2: SLA, appeals, complaints
- `backend/sla.py` (new): pure functions `business_due(start, hours, calendar, holidays, tz)`, `elapsed_business(...)` (with `zoneinfo`; `tzdata` may be needed on Windows, already a transitive dependency of pandas), and clock start, pause and stop on state changes, called from `store.set_state`.
- `backend/sla_jobs.py` (new): a tenant-aware sweep (startup and a periodic thread through `runs.spawn`). Warnings, breaches and escalations go into `notifications` with no external send.
- `backend/signoff.py:list_signoffs`: uses `sla.py`. The `overdue` field is kept.
- `backend/complaints.py`, `backend/appeals.py`, `backend/communications.py` (new routers). An appeal's reviewer must not be the original decider or the signer: checked against `decisions.run_id`, `signoffs.handler_id` and appeal history. An appeal outcome **inserts** a new decision with `supersedes_id`; the original is never updated. Payment change on appeal goes through the existing `payout.calculate` and `decisions.pay`, and over $1,000 still needs sign-off.
- `dashboard/src/views/Complaints.tsx`, `Appeals.tsx`, a drawer History tab (decision chain + communications), SLA chips.
- **Tests:** calendar edge cases (weekends, holidays, DST changes, a claim submitted on Friday evening in another time zone), configurable thresholds, breach → notification, idempotent sweep, reviewer independence refused, an original decision that cannot change, the full history returned, and tenant isolation on all new tables.
- **Accept:** the existing sign-off `overdue` is unchanged with the default 24/7 calendar. An appeal reversal is visible as a chain. No customer message is sent anywhere.

### Phase 3: external verification
- `backend/verification/__init__.py`, `types.py` (pydantic results), `client.py` (timeout, retry with jitter, circuit breaker per provider and tenant, TTL cache in `verification_cache`), `flight.py`, `baggage.py` (PIR), `medical.py` (interfaces), `mock.py` (fixture-driven, deterministic, can simulate an outage, a timeout or no record).
- `backend/verification/routes.py`: `verify_flight(claim_id, flight_number, date, run_id)` and the others, added to the claim-agent scopes. Results are stored in `verifications`.
- `agent/main.py`: one new tool `verify_flight` (plus baggage) using the existing `call()`. `backend/instructions_claim.md`: UNVERIFIED means "not confirmed", never a reason to decline. This changes the instruction fingerprint, as expected.
- `VERIFICATION_PROVIDER=mock` is the default. Real adapters are not shipped.
- **Tests:** each status path; missing data gives UNVERIFIED; the breaker opens after N failures and gives UNVERIFIED without a call; cache hits; provenance and timestamps recorded; the claim agent stub declines nothing on UNVERIFIED.
- **Accept:** no test or default config makes a network call. The docs say plainly that no live provider is integrated.

### Phase 4: fraud intelligence and SIU
- `backend/fraud/rules.py` (new): deterministic, versioned rules, each returning indicators with evidence (`claim_id`, document index, matched span or hash). Rules: duplicate document (normalized sha256 and simhash over `documents[].content`); invoice ref or amount and date duplicates; identity and date inconsistency (incident before purchase, travelers not on the policy, dates outside the trip); repeat incident (same type and location within N days, or a `previous_claims` match); payment-destination change (needs the new `payment_destinations`; on current data the rule is **inert**: the data does not exist); provider anomaly is **disabled** until a benchmark exists (config flag, documented).
- `backend/fraud/routes.py`: `list_risk_indicators` (humans with roles only; the agent gets at most a neutral "referral recommended: needs review" flag), dismiss with reason.
- `backend/siu.py`: open a case (refer → SIU), assign (siu_investigator only), notes with evidence links, dispositions CLEARED, SUBSTANTIATED or INCONCLUSIVE (human only, required note). An open case blocks payment (`decisions.pay_claim` checks for an open case) but **does not pause any customer-facing or regulatory SLA clock**. Those deadlines keep running, warn and escalate as usual. Investigation time is tracked by its own timers (`siu_cases.due_at` and `siu_timers` with an SIU-specific policy), reported apart from the customer SLAs.
- `dashboard/src/views/SIU.tsx`, an indicators panel in the drawer (human roles only).
- **Tests:** each rule on its own fixtures, plus a check that no rule fires falsely on the 35 queue claims except the expected repeat-history cases (CLM-1019 and CLM-1024 surfaced as indicators, **not** labelled fraud); a disposition only by an SIU role; payment blocked while a case is open; no output contains "fraud" in the agent or customer surfaces; no model training code.
- **Accept:** every indicator is explainable from its stored evidence. No supervised model. Inert or disabled rules are reported as such in the UI and docs.

### Phase 5b: operational analytics
- `backend/analytics.py` (new router; `get_analytics_brief` is kept): throughput, handling time by stage, SLA met or breached, human overrides (`origin='human_review'`, send-backs), appeal reversal rate, verification reliability (success, UNVERIFIED and breaker-open rates from `verifications`), eval results by dataset version, all per tenant. Each metric carries `n`, `data_class` (actual, synthetic or verified) and `sufficient_sample`.
- `dashboard/src/views/Reports.tsx`.
- Fraud-signal evaluation: the scorer stays disabled until verified SIU dispositions exist, and returns `"no verified labels"`.
- **Accept:** no metric is shown without n. Synthetic eval figures are never merged with operational actuals. Tenant admins and auditors see only their own tenant.

---

## E. Risks

- **Migrating existing databases:** the harness DB has no version table. Migration 0001 must detect an existing schema and mark itself applied.
- **Authorization added to every route breaks the e2e and voice flows:** fix this through shared login fixtures, not per-test workarounds.
- **SQLite concurrency:** more background sweeps on top of agent threads. Use WAL plus short transactions, and record this in the Postgres ADR.
- **Instruction changes (verification tool, UNVERIFIED wording)** change the fingerprint and may shift decision quality: rerun the 5a baseline before and after.
- **The medical gate** may lower agent accuracy on 6 medical claims: measure with 5a.
- **Unused heavy deps** (gradio, boto3, deepagents and others): don't add more, and leave the cleanup as a separate change.

These are standing rules for every phase. At the end of each phase, record how each one was handled in the table below and in `docs/STATUS.md`.

| Risk | How it is handled | State after Phase 1 |
|---|---|---|
| Migrating existing databases | Every schema change is a migration in `backend/migrations/`; 0001 checks an existing schema and refuses a mismatch | Handled. 0002 to 0004 migrate a harness database in place (checked on a copy of the local `undercover.db`) |
| Auth breaks e2e and voice flows | Shared fixtures only: `backend/tests/sessions.py` and `e2e/session.ts` | Handled. No per-test workaround in any spec |
| SQLite concurrency | WAL and a 30-second busy timeout on every connection (`db.connect`); connections opened per step, never held across a model call; limits recorded in `docs/ADR_POSTGRES.md` | Handled now, ahead of Phase 2 |
| Instruction changes shift quality | No change to the agent's instructions or tools until the 5a baseline exists; then measure before and after | Tooling ready (`evals.run`, `evals.compare`). Fingerprint `1c8b2cef2c28` unchanged. Needs the real-model baseline before any change |
| Medical gate lowers accuracy | Measure the six medical claims in 5a with the gate on and off (the tenant setting); only then decide the instruction wording | Tooling ready (`--medical on|off`, the medical slice). Open until a real-model run |
| Unused heavy dependencies | Add none; clean up in a separate change | Held. Phase 1 added no dependency |

## F. Verification (each phase)

- `npm run check` (ruff, pyright, pytest ≥80% coverage, eslint, tsc, vitest, Playwright), with the actual counts and any failures recorded in `docs/STATUS.md`.
- Phase 1: the parametrized cross-tenant and unauthenticated suite over all OpenAPI operations; a manual browser login per role.
- Phase 5a: `uv run -m evals.run --set queue` on the stub (deterministic), then optionally one real model run capped at 5 after reseeding, reported with n and CI.
- Phases 2–4: the unit tests listed per phase plus one Playwright flow each (complaint → resolve; appeal → independent review → superseding decision; SIU open → note → disposition).

## Open questions (defaults assumed if unanswered)

1. Medical gate default: **off for the external model** (safer), even though it changes current agent behavior on 6 claims.
2. Auth: **local accounts + server sessions now**, with OIDC later.
3. Postgres: **ADR only** in this upgrade, no migration.
