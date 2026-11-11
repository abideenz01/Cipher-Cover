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

Success criteria (done 2026-11-11):
- [x] Tests cover the manual's three worked examples ($215, $1,500 with sign-off, $1,150 with sign-off), hotel rooms and nights, meals at 11 and 30 hours, the cash limit, quantity, the deductible capped at the total, and an Acme payout of $800 needing sign-off.
- [x] `record_decision` still requires the payout to match the latest calculation.
- [x] The scripted 5a figures are checked: they did not move, because the scripted model's lines meet the same limits as before (noted in `docs/EVALUATION.md`).
- [x] The real-model run (gate off) is repeated and compared with G1 using `evals.compare`: `022d27c3cfa4`, $0.20. Decisions 30/35 and payouts 28/35, as in G1; refer recall 8/8. Three medical claims hit the 120-second time limit (open, see `docs/STATUS.md`).

## Phase D3: Supabase as the database

- `backend/db.py`: one SQLAlchemy Core engine. It is SQLite (WAL, 30-second busy timeout, a fresh connection each time) unless `DATABASE_URL` is in the process's environment, in which case it is the Supabase session pooler through psycopg, with `search_path` set to `undercover` and a pool of at most 4 connections.
- `db.connect()` keeps the sqlite3 methods every module uses (`execute`, `executemany`, rows read by name or position), so the 17 modules changed only their type hints. Queries keep their `?` placeholders, turned into named parameters in one place. The SQLite-only SQL is gone: `INSERT OR IGNORE` became `ON CONFLICT DO NOTHING`, and `rowid` ordering became a `seq` column (migration `m0005_run_order`). An integer key counts up on Postgres through `db.ddl()`.
- `backend/migrations/` keeps its chain and its rule of refusing a database that doesn't match. A harness SQLite database is still adopted as before. On Postgres the schema is always built by the chain, and tables found without a migration record are refused.
- The backend uses Supabase when `DATABASE_URL` is in its environment, which `npm run dev` gives it through `.env`. The tests, `playwright.config.ts` and the offline evaluations set it empty, so they stay on SQLite. `backend.seed --reset` drops and rebuilds the schema on Supabase.

Success criteria (done 2026-11-11):
- [x] Every existing Python, TypeScript and Playwright test passes on SQLite, with no test removed or weakened (Python 314 passed, TypeScript 42, Playwright 16 of 16).
- [x] `uv run --env-file .env -m backend.seed --reset` builds the `undercover` schema on Supabase, and the Supabase MCP server shows every table in `undercover` and none in `public`.
- [x] Counts on Supabase match the seed: 35 UnderCover claims and 10 Acme claims.
- [x] The dashboard against Supabase signs in, shows the board and opens a claim (checked with a Playwright script).
- [x] A test shows the pool never opens more than 4 connections.

## Phase D4: row-level security on Supabase

- Migration `m0006_rls` (Postgres only; nothing changes on SQLite):
  - RLS with `FORCE ROW LEVEL SECURITY` on all 21 tenant tables, using `tenant_id = current_setting('app.tenant_id', true)` for both reads and writes, plus `user_roles` through its user;
  - `tenant_id` without a default;
  - an application role, `undercover_app`, that has no login, owns nothing and can't bypass RLS. Migrations run as the owner.
- Supavisor needs no custom login: the owner's connection takes the application role for one transaction (`set_config('role', ...)`), so no second password is needed. `auth.scope`, an async dependency after the guard, holds the caller's tenant for the request, and `db.connect()` sets the role and `app.tenant_id` in one round trip inside every signed-in request. Work with no caller (startup recovery, sign-in, the agent's background threads) uses the owner's connection.
- The tenant filters in the code stay, as a second layer.

Success criteria (done 2026-11-11):
- [x] Opt-in tests (`-m postgres`, skipped without `TEST_DATABASE_URL`) run against Supabase with RLS on, in an `undercover_test` schema that is dropped afterwards: 8 passed.
- [x] A query with its tenant filter removed still returns only the caller's rows, and an insert with no tenant fails.
- [x] `get_advisors` through the Supabase MCP server reports no security warnings.
- [x] `docs/ADR_POSTGRES.md` is marked implemented and lists what is still out of scope.

## Phase D5: the durable claim agent

- `agent/graph.py`: the claim agent becomes a hand-written LangGraph `StateGraph`. Its nodes are the model, the tools (each step recorded on the claim, refusals returned to the model) and a pay step after every approval. It keeps a cap of 30 model calls and retries provider errors three times. The queue agent stays on `create_agent`.
- After an approval, the graph asks the backend whether the claim needs sign-off. If it does, it waits with `interrupt()`. The graph never applies the limit itself, and the backend still refuses an unsigned payout over the limit.
- Progress is saved after every step by the synchronous `PostgresSaver` (`durability="sync"`) in the `undercover` schema, sharing the 4-connection limit. Tests use `InMemorySaver`.
- `pay_claim` is no longer one of the agent's tools, and the instructions change to match. The backend operation stays, for the pay step.
- Backend changes, each in the module that does it today:
  - **No migration for runs:** a run's thread is its own `run_id`, and `paused` and `interrupted` are new values of the existing `status` text. (The migration that was needed is `m0007_signed_off_payments`, in D6: payments get `signed_off_by` and `signed_off_at`.)
  - **`queue_runs.recover()`:** a claim stopped partway with a checkpoint is marked `interrupted`, with no new attempt and its claim kept. A claim that failed with an error goes back to waiting with an attempt counted, as today.
  - **`auth.py`:** issues a new claim token for the same run and thread when a claim resumes.
  - **`record_decision` and `pay_claim`:** a repeat of what is already recorded returns the claim. A different decision is still a 409.
  - **The queue:** a stopped queue run is finished by the next one.

Success criteria (stub model, no network):
- [x] A claim over the limit stops at the interrupt, with its state saved and the claim waiting for sign-off.
- [x] A claim stopped after its first steps carries on from its last step on the same thread, with `failed_attempts` unchanged and one decision.
- [x] A claim that raises an error goes back to waiting and starts again from scratch.
- [x] A repeated decision or payment returns the claim. A different decision returns 409. No claim ever has two decisions or two payments.
- [x] The 30-call cap and the step-by-step trace behave as before (the existing tests, adapted only where `create_agent` is named).
- [x] The real-model runs (gate off and on) are compared with G1. This is the final measurement: `589fcf322cf2` (off) and `8102ded19bee` (on), no difference outside the intervals (see `docs/EVALUATION.md`).

## Phase D6: the agent's service and resuming on sign-off

- `agent/service.py`: a small FastAPI service at `UNDERCOVER_AGENT` (default `http://127.0.0.1:8002`) with a `resume_claim` operation. It accepts only a service token the backend issues and resumes the claim's thread. `npm run dev` starts it alongside the backend and the dashboard, and it works on Windows.
- `sign_off_claim` saves who signed off and when, does not pay, and moves the claim to in progress. Once that is saved, it calls the service without waiting for the payment. The sign-off stands if the service can't be reached.
- The pay step records the payment with the sign-off it rests on. Rejecting a held payout is left for the next production phase.
- On startup, the service and `uv run -m agent` first resume every claim that is `interrupted` or signed off and unpaid.
- The dashboard shows a signed-off claim as in progress, then paid with the handler and the time.
- `docs/CODE_STANDARDS.md` gets the service as the agent's fourth part, with the graph's nodes in place of the middleware.

Success criteria:
- [x] A Python test: a sign-off resumes the claim and pays it once, and the payment records the handler and the time.
- [x] A Python test: a sign-off while the service is down stands, and the next run pays the claim.
- [x] An end-to-end test: a sign-off on the dashboard reaches a stand-in service on port 8003, never the one on port 8002.
- [x] A test: the backend still refuses a payout over the limit without a sign-off, whatever the agent sends.

## Phase D7: live checks and the docs

After reseeding Supabase, on the default model:
- [x] A run capped at five claims works all five. A claim over the limit waits for sign-off. Queue run `953dded6…`: all five worked, ended `succeeded` at its cap in 1,089 s with 382,795 tokens; CLM-1001, 1004 and 1005 paid once each; CLM-1002 and CLM-1003 hit the 120-second claim time limit twice and were left for a handler. No claim in that run reached a sign-off, so the held claims were named runs on CLM-1011 ($1,150.00) and CLM-1008 ($2,240.00), both of which waited for sign-off.
- [ ] Signed off on the dashboard (a Playwright script; no Playwright MCP server here), that claim shows as paid within five seconds, with the handler and the time. **Not met from this machine:** CLM-1008 was paid 13 s after the sign-off was saved (19.6 s from the click), CLM-1011 9 s; the drawer then shows "Paid $2,240.00 at 17:19, signed off by Dana Whitfield at 17:19". The cause is the round trips to the database in Seoul (about 230 ms each); see `docs/STATUS.md`.
- [x] A run killed after a claim's first steps carries on with the same thread next time, with attempts unchanged and one decision. CLM-1011, run `582365ad…`: every process was killed during its section reads (7 checkpoints, 24 steps). On restart the service carried it on in the same thread: the pending reads ran once, nothing earlier was repeated, attempt 1, `failed_attempts` 0, one decision, then it waited for sign-off.
- [x] During the run, `pg_stat_activity` shows no more than 12 connections, counting the postgres user and the application role: peak 6 (including Supabase's own `pg_net`) over 205 samples in 34 minutes; 7 through the Supabase MCP server with the stack idle afterwards.
- [x] Langfuse's API shows the held claim's session with traces from before and after the sign-off. `CLM-1011:582365ad…` has three traces: 12:03:35 to 12:04:21 (before the kill), 12:05:14 to 12:07:18 (after the restart, up to the decision) and 12:08:11 (the pay step after the sign-off).
- [x] The spend for the whole plan is recorded and is within $1.50: $0.91.
- [x] `docs/SPEC.md` (its section on working the queue only), `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` describe the product as it now is (and `docs/ARCHITECTURE.md`).
- [x] `npm run check` is green with `.env` moved away: Python 343 passed and 9 skipped (the opt-in Postgres tests) at 96.6%, TypeScript 44 passed, Playwright 16 of 16.

## Set up for the production phases that follow

| Phase in `docs/PLAN_PRODUCTION.md` | What it builds on |
|---|---|
| 2 SLA, appeals, complaints | Rejecting a held payout, reconsideration and independent review are further ways of resuming the paused graph. Decisions are only ever added, so the original is kept. SLA sweeps run per tenant in the agent's service. |
| 3 External verification | A tool or node in the graph, with a cache table on Supabase. Missing data gives UNVERIFIED. |
| 4 Fraud intelligence and SIU | Deterministic rules in the backend, with SIU cases in tables under RLS. |
| 5b Operational analytics | Views on Supabase for each tenant, plus Langfuse for latency and reliability. |

From D4 on, every new table is a migration that brings its own RLS policy. Moving the dashboard's runs from backend threads into the agent's service is the natural next step for the cloud, and it is left out of this plan on purpose.
