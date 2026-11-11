# Plan: approvals that wait, and work that survives a restart

The brief is `docs/DURABLE.md`.

Written 2026-11-11. Nothing is built yet. Tick each box as it is checked, and update `docs/STATUS.md` at the end of every phase, as `docs/PROCESS.md` asks.

## Decisions taken in planning

- **Where the payout rules come from.** The lab files are not used (2026-11-11). The rules come from section 10 of `data/policy_wording.md` and sections 6, 7 and 10 of `data/claims_manual.md`: per-item and Electronics Plus limits, $350 a night with one room for every two travelers, $35 per traveler per started 24 hours for meals without receipts, cash up to $100, and a deductible no larger than the total. They extend `backend/payout.py` and `calculate_payout`. There is no second payout engine.
- **The sign-off limit** is the tenant's `payout_approval_limit`, read through `db.reference(..., tenant_id)` (UnderCover $1,000, Acme $750), not `data/company.json` directly.
- **Supabase is the system of record** from Phase D3 on. Every later production phase (`docs/PLAN_PRODUCTION.md` 2, 3, 4, 5b) builds on it. The tests stay on SQLite and need no network.
- **Row-level security comes with the move** (Phase D4), as `docs/ADR_POSTGRES.md` requires before more than one tenant's data sits in one database.
- **Dependencies.** `sqlalchemy` moves from the `server` group to the main dependencies. Nothing new is added: `langfuse`, `langgraph-checkpoint-postgres` and `psycopg` are already locked.
- **Agent changes are measured, within a budget.** The owner approved $1.50 of OpenRouter spend for this plan (2026-11-11), out of $5.00 of credit. The 5a evaluation runs on the default model on the 35-claim queue set at three points: G1 (medical gate off and on) before the first change to the agent's tools or instructions, after D2 (gate off), and after D5 (gate off and on), which is also the final measurement because D3, D4 and D6 don't change what the agent sees or does. The D1 smoke test uses `openrouter/free`. The D7 live checks use the default model. The actual tokens and cost are added up after every paid run, and the work stops to ask before the total would pass $1.50. The scripted figures fixed in `evals/` tests change with D2, and the change is explained in `docs/EVALUATION.md`.
- **Langfuse** gets only what an external model may see. Medical records and bills are left out unless the tenant's `external_model_medical` is on, and contact details are never sent.
- **Unchanged:** tenancy, roles and the security log; the backend's sign-off limit; citation checks; budgets and leases; the medical gate; voice; the eval sets and their hashes; and the 35-claim UnderCover queue that the labels depend on.

## Phase D1: tracing in Langfuse

No change to what the agent does. The `run_events` trace and the dashboard's Trace tab stay as they are.

- `agent/tracing.py`: a Langfuse callback handler when the three `LANGFUSE_*` settings are present, and none otherwise. Each claim's work goes in one session, `<claim_id>:<thread_id>`. The queue agent's run is its own trace, linked to each claim's session.
- Inputs and outputs are masked before they are sent, as set out above.

Success criteria (done 2026-11-11):
- [x] `langfuse.auth_check()` passes with the keys in `.env`, and the result is recorded in `docs/STATUS.md`.
- [x] A test with a stub model shows one session per claim named `<claim_id>:<thread_id>`, using a recording handler, with no network.
- [x] A test shows that a medical document and a customer's email never reach the handler's payload when the medical gate is off.
- [x] With `.env` moved away, `npm run check` is green and makes no call to Langfuse.
- [x] A run on one claim with `openrouter/free` (after reseeding) shows up in Langfuse's API as one session with the claim's steps.

## Gate G1: the real-model baseline

Done 2026-11-11: `812783e22e15` (medical off) and `6158f1b36985` (medical on), $0.30 in all. Figures in `docs/EVALUATION.md`.

- [x] `uv run -m evals.run --set queue --model real --medical off` and `--medical on` are run and stored in `evals.db`, and the figures and the instructions fingerprint go into `docs/EVALUATION.md`.

## Phase D2: the payout rules from the manual

- `backend/payout.py`: a line has `kind` (`item`, `electronics`, `cash`, `expense`, `hotel`, `meals_without_receipts`), `quantity`, `nights` and `hours`. The number of travelers comes from the policy. Everything is in cents. The result says whether the payout needs sign-off, using the tenant's limit.
- `calculate_payout` takes the new line shape. Every input is required, as `docs/TECH_STACK.md` asks. The agent's tool and `backend/instructions_claim.md` change to match.

Success criteria:
- [ ] Tests cover the manual's three worked examples ($215, $1,500 with sign-off, $1,150 with sign-off), hotel rooms and nights, meals at 11 and 30 hours, the cash limit, quantity, the deductible capped at the total, and an Acme payout of $800 needing sign-off.
- [ ] `record_decision` still requires the payout to match the latest calculation.
- [ ] The scripted 5a figures are updated, with the reason given in `docs/EVALUATION.md`.
- [ ] The real-model run (gate off) is repeated and compared with G1 using `evals.compare`.

## Phase D3: Supabase as the database

- `backend/db.py`: one SQLAlchemy Core engine. It is SQLite (WAL, 30-second busy timeout) unless `DATABASE_URL` is in the process's environment, in which case it is the Supabase session pooler with `search_path` set to `undercover` and a pool of at most 4 connections.
- The 17 modules that use `sqlite3` are ported mechanically, with no change to their logic: named parameters instead of `?`, a portable upsert instead of `INSERT OR IGNORE`, explicit ids instead of `rowid`.
- `backend/migrations/` keeps its chain and its rule of refusing a database that doesn't match, but checks the schema with SQLAlchemy's inspector instead of `sqlite_master` and `PRAGMA`. A harness SQLite database is still adopted as before. A new Supabase schema is built by running the whole chain.
- `npm run dev` passes `.env` (`uv run --env-file .env`). The tests and `playwright.config.ts` never do. `backend.seed --reset` works on Supabase.

Success criteria:
- [ ] Every existing Python, TypeScript and Playwright test passes on SQLite, with no test removed or weakened.
- [ ] `uv run --env-file .env -m backend.seed --reset` builds the `undercover` schema on Supabase, and `list_tables` through the Supabase MCP server shows every table in `undercover` and none in `public`.
- [ ] Counts on Supabase match the seed: 35 UnderCover claims and 10 Acme claims.
- [ ] The dashboard against Supabase signs in, shows the board and opens a claim.
- [ ] A test shows the pool never opens more than 4 connections.

## Phase D4: row-level security on Supabase

- Migration `m0005_rls` (Postgres only):
  - RLS with `FORCE ROW LEVEL SECURITY` on every tenant table, using `tenant_id = current_setting('app.tenant_id')` for both reads and writes;
  - `tenant_id` without a default;
  - an application role that doesn't own the tables and can't bypass RLS. Migrations run as the owner.
- `db.connect(tenant_id)` sets `SET LOCAL app.tenant_id` from the principal that `backend/auth.py` already resolves. Sign-in and startup recovery, which work across tenants, use the owner connection, and each such use is written down.
- The tenant filters in the code stay, as a second layer.
- Before building, check whether Supavisor's session pooler accepts the custom role. If it doesn't, stop and ask.

Success criteria:
- [ ] Opt-in tests (`-m postgres`, skipped without `DATABASE_URL`) run the cross-tenant suite against Supabase with RLS on.
- [ ] A query with its tenant filter removed still returns only the caller's rows, and an insert with no tenant fails.
- [ ] `get_advisors` through the Supabase MCP server reports no RLS warnings for `undercover`.
- [ ] `docs/ADR_POSTGRES.md` is marked implemented and lists what is still out of scope.

## Phase D5: the durable claim agent

- `agent/graph.py`: the claim agent becomes a hand-written LangGraph `StateGraph`. Its nodes are the model, the tools (each step recorded on the claim, refusals returned to the model) and a pay step after every approval. It keeps a cap of 30 model calls and retries provider errors three times. The queue agent stays on `create_agent`.
- After an approval, the graph asks the backend whether the claim needs sign-off. If it does, it waits with `interrupt()`. The graph never applies the limit itself, and the backend still refuses an unsigned payout over the limit.
- Progress is saved after every step by the synchronous `PostgresSaver` (`durability="sync"`) in the `undercover` schema, sharing the 4-connection limit. Tests use `InMemorySaver`.
- `pay_claim` is no longer one of the agent's tools, and the instructions change to match. The backend operation stays, for the pay step.
- Backend changes, each in the module that does it today:
  - **Migration `m0006`:** `runs` get `thread_id` and the states `paused` and `interrupted`.
  - **`queue_runs.recover()`:** a claim stopped partway with a checkpoint is marked `interrupted`, with no new attempt and its claim kept. A claim that failed with an error goes back to waiting with an attempt counted, as today.
  - **`auth.py`:** issues a new claim token for the same run and thread when a claim resumes.
  - **`record_decision` and `pay_claim`:** a repeat of what is already recorded returns the claim. A different decision is still a 409.
  - **The queue:** a stopped queue run is finished by the next one.

Success criteria (stub model, no network):
- [ ] A claim over the limit stops at the interrupt, with its state saved and the claim waiting for sign-off.
- [ ] A claim stopped after its first steps carries on from its last step on the same thread, with `failed_attempts` unchanged and one decision.
- [ ] A claim that raises an error goes back to waiting and starts again from scratch.
- [ ] A repeated decision or payment returns the claim. A different decision returns 409. No claim ever has two decisions or two payments.
- [ ] The 30-call cap and the step-by-step trace behave as before (the existing tests, adapted only where `create_agent` is named).
- [ ] The real-model runs (gate off and on) are compared with G1. This is the final measurement.

## Phase D6: the agent's service and resuming on sign-off

- `agent/service.py`: a small FastAPI service at `UNDERCOVER_AGENT` (default `http://127.0.0.1:8002`) with a `resume_claim` operation. It accepts only a service token the backend issues and resumes the claim's thread. `npm run dev` starts it alongside the backend and the dashboard, and it works on Windows.
- `sign_off_claim` saves who signed off and when, does not pay, and moves the claim to in progress. Once that is saved, it calls the service without waiting for the payment. The sign-off stands if the service can't be reached.
- The pay step records the payment with the sign-off it rests on. Rejecting a held payout is left for the next production phase.
- On startup, the service and `uv run -m agent` first resume every claim that is `interrupted` or signed off and unpaid.
- The dashboard shows a signed-off claim as in progress, then paid with the handler and the time.
- `docs/CODE_STANDARDS.md` gets the service as the agent's fourth part, with the graph's nodes in place of the middleware.

Success criteria:
- [ ] A Python test: a sign-off resumes the claim and pays it once, and the payment records the handler and the time.
- [ ] A Python test: a sign-off while the service is down stands, and the next run pays the claim.
- [ ] An end-to-end test: a sign-off on the dashboard reaches a stand-in service on port 8003, never the one on port 8002.
- [ ] A test: the backend still refuses a payout over the limit without a sign-off, whatever the agent sends.

## Phase D7: live checks and the docs

After reseeding Supabase, on the default model:
- [ ] A run capped at five claims works all five. A claim over the limit waits for sign-off.
- [ ] Signed off on the dashboard through the Playwright MCP server, that claim shows as paid within five seconds, with the handler and the time.
- [ ] A run killed after a claim's first steps carries on with the same thread next time, with attempts unchanged and one decision.
- [ ] During the run, `pg_stat_activity` through the Supabase MCP server shows no more than 12 connections, counting the postgres user and the application role.
- [ ] Langfuse's API shows the held claim's session with traces from before and after the sign-off.
- [ ] The spend for the whole plan is recorded and is within $1.50.
- [ ] `docs/SPEC.md` (its section on working the queue only), `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` describe the product as it now is.
- [ ] `npm run check` is green with `.env` moved away.

## Set up for the production phases that follow

| Phase in `docs/PLAN_PRODUCTION.md` | What it builds on |
|---|---|
| 2 SLA, appeals, complaints | Rejecting a held payout, reconsideration and independent review are further ways of resuming the paused graph. Decisions are only ever added, so the original is kept. SLA sweeps run per tenant in the agent's service. |
| 3 External verification | A tool or node in the graph, with a cache table on Supabase. Missing data gives UNVERIFIED. |
| 4 Fraud intelligence and SIU | Deterministic rules in the backend, with SIU cases in tables under RLS. |
| 5b Operational analytics | Views on Supabase for each tenant, plus Langfuse for latency and reliability. |

From D4 on, every new table is a migration that brings its own RLS policy. Moving the dashboard's runs from backend threads into the agent's service is the natural next step for the cloud, and it is left out of this plan on purpose.
