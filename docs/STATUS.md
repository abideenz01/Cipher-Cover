# Status

Kept up to date as `docs/PROCESS.md` asks: updated at the end of every phase and after every change.

## What's built

- `backend/`: FastAPI on SQLite (`backend/db.py`). On startup it seeds an empty database from `data/` (`backend/seed.py`), reading only the company, plans, policies, customers, handlers and claims. The read API is in `backend/claims.py`. No operation returns a customer's email, phone, date of birth or address.
- `backend/payout.py` applies section 10 of the wording; `backend/decisions.py` has `calculate_payout`, `record_decision` and `pay_claim`. `pay_claim` refuses any payout over $1,000.00, which waits for a handler's sign-off. `calculate_payout`, `record_decision` and `pay_claim` take a `run_id` and refuse unless it is a live claim run on that claim. `record_decision` refuses a claim that isn't in progress, an empty reason, no sections, or a section the run never read. The agent's instructions are `backend/instructions_claim.md` and `backend/instructions_queue.md`; `get_instructions` returns both with a 12-character fingerprint.
- `backend/signoff.py`: `list_signoffs`, `sign_off_claim` (HND-01 to HND-03 only; signing off pays the claim) and `send_back_claim`. A sign-off waiting longer than `sign_off_sla_hours` is `overdue`.
- `backend/runs.py`: `start_run` runs the claim agent on one named claim in a background thread (`backend/runner.py`); each step is stored as a run event for `list_run_events`. A claim is leased in one conditional update, so it can't be taken twice. A run that raises or ends without a decision fails and returns its claim to `waiting`. `AGENT_STUB=1` swaps in the scripted model.
- `backend/queue_runs.py`: queue runs. `start_queue_run {cap}` (0 for no cap) refuses while one is live and stores the limits, model, reasoning effort and instructions fingerprint. `begin_attempt` leases a claim for a claim run, refusing with 409 when the run is stopping, paused or out of budget, the claim is left for a handler, or the cap is reached (a retry doesn't count against it). `finish_attempt` ends a claim run and returns one line; provider failures in a row (`PROVIDER_FAILURES_TO_PAUSE`, default 3) pause the run. `finish_queue_run` refuses while waiting claims within the cap remain undecided, then marks unfinished to-do items `not_started`. `stop_queue_run`, `write_todos`, `get_queue_run`, `list_queue_runs` (the last 20) and `list_queue_run_events`. Tokens count against `RUN_TOKEN_LIMIT` (default 1,000,000). A queue agent that raises or ends without a summary has its claims freed. On startup, claims left in progress return to waiting with a failed attempt and live runs fail with "The backend restarted."
- `backend/voice/`: the voice operations. All need sign-in, and all are 404 unless `VOICE_ENABLED=1`, except `get_voice_config`. Briefs speak money and claim ids in words and never carry a story, document text or personal data. `request_signoff` only records a request for 10 minutes; a handler's click is the sign-off. Turns are rate limited per session (`VOICE_TURNS_PER_MINUTE`), time out after 30 seconds with a spoken fallback, and are logged in `voice_turns`.
- `agent/voice.py`: the voice agent, `run_turn(session_id, handler_id, text, llm=None, token="")`, with nine tools and `backend/voice_instructions.md` as its prompt. `agent/voice_stub.py` is its scripted model.
- `agent/`: the claim agent, `run(claim_id, thread_id, llm=None, on_step=None, seconds=120)` in `agent/main.py`, with eight tools over the API, including `list_sections` and `read_section`. The thread id is the run id. It defaults to `deepseek/deepseek-v4.1-flash` with low reasoning effort (`MODEL_NAME` overrides it), retries provider errors three times with `ModelRetryMiddleware`, stops at `CLAIM_STEP_LIMIT` model calls (default 30) with `ModelCallLimitMiddleware`, and stops after the run timeout in `company.json`. A failed run is sorted into `provider`, `step_limit`, `time_limit` or `error`, adds one to the claim's `failed_attempts` and returns it to waiting. Each run records its tokens, model calls and model. `agent/stub.py` has the scripted model, which approves and pays every item citing `wording-10`, and `FaultyModel`, which can raise provider errors, loop or cite an unread section.
- `agent/queue.py`: the queue agent, `run_queue(run_id, llm=None, claim_llm=None, on_step=None)`, with five tools: `get_run_status`, `list_waiting_claims`, `write_todos`, `work_claim` and `finish_run`. It has no tool to decide or pay. `work_claim` leases the claim, runs a fresh claim agent on it, and ends the attempt with its failure kind; it is the one place the agent catches an error, so one bad claim can't stop the run. Its model calls are capped at four per claim plus 20. `agent/stub.py`'s `QueueScript` plans, works and ticks off each claim in order, for tests and `AGENT_STUB=1`.
- `dashboard/`: the Cipher Cover console from `BRAND.md`. A rail (Queue, Sign-off, Instructions), a command bar (`/` to search, theme switch, Run all waiting), a metric strip, a four-column board and a claim drawer with Overview, Documents, Decision and Trace tabs. The board polls every two seconds; the trace polls every second while a run is live. Styles are all in `dashboard/src/theme.css`.
- The harness in the dashboard: the command bar's run control has a Claims field (default 5) with an All box and a Run button, replaced by the run's status chip and Stop while a run is live. The Queue view has a run panel above the board: the live or latest run's to-do list with a labelled chip per item, its tokens, time, model and limits, its summary and why it ended, and a Run history of the last 20 runs. Cards left for a handler carry a chip. The drawer's Trace tab groups steps by attempt, with each attempt's tokens, time and sections read; the Decision tab lists the sections relied on. The Instructions view shows the queue and claim instructions with the fingerprint.
- `dashboard/src/voice/`: voice in the dashboard. A mic button in the command bar (hold it or hold `V` to talk, a tap for hands-free, Escape stops speech), a captions panel showing who is speaking and a Type instead field, and a one-time consent notice. `focus_signoff` highlights the claim on the Sign-off view with a Confirm button; only that click signs off. With voice off there is no mic and no panel. Speech uses the browser's own recognition and synthesis (Chrome or Edge); `VOICE_PROVIDER=stub` is for Playwright.
- `backend/documents.py`: `list_sections` and `read_section` split the policy wording and the claims manual on their numbered headings (`wording-5`, `manual-9`). Each read is recorded in `section_reads` against a live claim run.
- `backend/migrations/`: versioned schema migrations, applied by `seed.seed()` on every startup and recorded in `schema_migrations`. `m0001_baseline` is the harness schema (`db.SCHEMA`). On a database made before migrations it compares every table and column with that schema, and only records itself as applied if they match. Otherwise it raises `SchemaMismatch`, lists each difference and records nothing. A database that records a migration newer than the code is refused too.
- `backend/migrations/m0002_tenancy.py` adds `tenants` and a `tenant_id` (default `T-UNDERCOVER`) with an index on all 15 business tables. `m0003_auth.py` adds `users`, `user_roles`, `sessions`, `service_tokens` and `security_events`. A harness database is migrated in place and keeps its claims and decisions (checked on a copy of the local `undercover.db`: 35 claims and 5 decisions kept, all in `T-UNDERCOVER`).
- `backend/auth.py`: sign-in and the check on every operation. `guard` is set on the whole app, so every route needs a caller except `health`, `login` and `get_public_config`; `/docs` and `/openapi.json` are off unless `API_DOCS=1`. It has `login` (email and password, scrypt hashes; five failures in 15 minutes for one email or address give 429), `logout`, `get_me`, `get_public_config` (product name and sign-in method only) and `list_security_events`. A session is an HttpOnly, SameSite=Strict, Secure cookie (`COOKIE_SECURE=0` for plain http), with a CSRF token required on every cookie write, or a bearer token. It ends after `SESSION_IDLE_MINUTES` (30) idle or `SESSION_HOURS` (12). Agents get service tokens. A claim token is bound to its run, claim, policy and customer, and ends with the run. A queue token is bound to its queue run and the claim runs it leased. A voice token lasts one turn and allows only the voice tools its person may also call. Every agent token ends on restart. Tokens are stored only as SHA-256 hashes.
- `backend/permissions.py`: operations by role. `claims_handler` reads, runs the agent and the queue, sends back and uses voice. `senior_handler` can also sign off and request sign-off. `siu_investigator` reads. `auditor` and `tenant_admin` read and see the security log. Only agents record decisions, calculate and pay. Seeded roles: HND-01 to HND-03 senior, HND-04 handler, HND-05 SIU, plus an admin and an auditor.
- `backend/security_events.py` logs sign-ins and their failures, sign-outs, refusals (401 with a bad credential, and 403), CSRF failures, sign-offs, send-backs, sign-off requests and tokens issued.
- Tenancy: every query filters by the caller's tenant, and a record in another tenant is a 404. Sign-off, send-back and voice act as the signed-in handler; any `handler_id` in a body is ignored. `get_claim` withholds medical records and bills from agents unless the tenant's config sets `external_model_medical`, and agents see short customer names. This is application-level isolation for development and pilots, not the production guarantee: production with more than one tenant needs PostgreSQL with row-level security first (`docs/ADR_POSTGRES.md`).
- `dashboard/` now has a sign-in screen (`views/Login.tsx`, `Session.tsx`) in front of the console, a Sign out button with the signed-in name on the rail, and the CSRF token on every write. The handler pickers on Sign-off and in the captions panel are gone: both act as the signed-in handler. A 401 at any point returns to sign-in.
- `evals/`: the offline evaluation, outside `backend/` and `agent/` (neither imports it). `uv run -m evals.run --set queue|held_out|harder|even_harder|security [--tiny] [--limit N] [--model stub|real] [--medical on|off]` seeds a temporary backend with a set's claims, policies and customers only, runs the claim agent through the API under its run token, and only then scores against the labels. It reports proportions with Wilson 95% intervals; the payout error, seconds and tokens as median, p90 and range, with a bootstrap interval for the median once n is at least 20; slices by difficulty, claim type, expected decision and medical documents; and every figure with its n, flagging n under 30. Runs are stored in a separate `evals.db` (`EVAL_DB_PATH`), and `uv run -m evals.compare A B` compares two of them. `data/evals/MANIFEST.json` records each set's version, n, provenance (all synthetic, single-handler labels) and file hashes, and a changed set is refused. Details and the baseline are in `docs/EVALUATION.md`.
- `e2e/queue.spec.ts` covers a capped run, the sections on a decided claim and Stop. It runs before `voice.spec.ts`, which needs CLM-1405 still waiting.
- `e2e/`: Playwright tests of the dashboard against a backend on a fresh temporary database with `AGENT_STUB=1`.
- `docs/screens/`: screenshots of the dashboard in dark and light mode.

## How to run it

- `uv sync` and `npm install`, then `npm run dev` for the backend on port 8000 and the dashboard on port 5173.
- The database is `undercover.db` at the repo root, or `DB_PATH` if set. `uv run -m backend.seed --reset` rebuilds it from `data/`. A database from the harness is adopted by the migrations as it is. A database from the pilot, or any other schema that doesn't match, stops the backend with a `SchemaMismatch` that lists the differences, and must be rebuilt this way.
- `npm run check` runs every check.
- Sign in with a demo sign-in: one per handler (`dana.whitfield@undercover.example` and so on, from `data/handlers.json`), `admin@undercover.example` or `auditor@undercover.example`. They are created once, when the users table is empty. With `DEMO_PASSWORD` set they all get that password; otherwise each gets a random one, printed in the backend's output.
- To run the queue, sign in, set the number of claims in the command bar and press Run. From the command line, send `POST /api/runs` with a session token as `Authorization: Bearer`; the README shows how. The limits are settings in `.env` (see `.env.example`): `CLAIM_STEP_LIMIT` (30 model calls a claim), `RUN_TOKEN_LIMIT` (1,000,000 tokens a run), `PROVIDER_FAILURES_TO_PAUSE` (3) and `MODEL_TIMEOUT_SECONDS` (60); the time on one claim is `agent_run_timeout_seconds` (120) in `data/company.json`.
- To try voice, set `VOICE_ENABLED=1` in `.env` and open the dashboard in Chrome or Edge. `.env.example` lists the voice settings.
- The agent calls the backend at `http://127.0.0.1:8000`, not `localhost`: on Windows, `localhost` tries IPv6 first and adds about two seconds to every call.

## Notes

- Cherry with white text is 4.45 to 1, just under WCAG AA, so the Decline and Overdue chips use a slightly deeper Cherry, `#D41F49`. Every other color is as `BRAND.md` gives it.
- The brand review of the screens was done with a Playwright script (`chromium.launch`), because no Playwright MCP server is connected in these sessions.
- 2026-10-30: this machine was moved to Node 26.13.0 LTS, and `%SystemRoot%\System32` was added back to the user PATH so Playwright can stop its servers. With both, `npm install` and `npm run check` pass with no workarounds: Python 91 tests at 98.7%, TypeScript 27 tests at 96.0%, Playwright 11 of 11 in about 45 seconds.

## Phases

The production upgrade plan is in `docs/PLAN_PRODUCTION.md`.

| Production phase | State |
|---|---|
| 0 Schema migrations | Done 2026-11-03. Python 139 passed at 98.9%, TypeScript 32 at 96.5%, Playwright 14 of 14 |
| 1 Multi-tenant security | Done 2026-11-03, gaps closed the same day. Python 262 passed at 99%, TypeScript 42 at 96.3%, Playwright 16 of 16. Isolation is application-level only; Postgres RLS is a deployment gate |
| 5a Evaluation baseline | Done 2026-11-03 for the scripted model. The real-model baseline has not been run yet, because it costs money (`docs/EVALUATION.md`) |
| 2 SLA, appeals and complaints | Not started |
| 3 External verification | Not started |
| 4 Fraud intelligence and SIU | Not started |
| 5b Operational analytics | Not started |

- 2026-11-03: `e2e/voice.spec.ts` "holding the mic sends what it heard and opens the claim" failed locally (not in CI). Cause: `agent/main.py` loaded `.env` with `override=True`, so a local `.env` with `VOICE_PROVIDER=browser` replaced the `VOICE_PROVIDER=stub` that `playwright.config.ts` starts the backend with. The dashboard then used real speech recognition, which hears nothing in headless Chromium. The same override could have replaced `DB_PATH` or `AGENT_STUB` in e2e. Fix: `agent.main.load_settings()` fills settings from `.env` without overriding the process's own, tested by `test_settings_given_to_the_process_beat_the_env_file`. Python 139 passed at 98.9%, TypeScript 32 passed at 96.5%. Playwright 14 of 14.

- 2026-11-03, Phase 1 gaps closed:
  - Admins now manage sign-ins and settings. `backend/accounts.py` adds `list_users`, `create_user`, `set_user_roles`, `disable_user`, `enable_user`, `get_tenant_settings` and `update_tenant_settings`, all inside the admin's own tenant and all written to the security log. An admin cannot remove their own admin role or disable themselves. Disabling a sign-in ends its sessions. The dashboard has an Admin view for tenant admins. Auditors can read the sign-ins and settings but cannot change them.
  - A second tenant is seeded. Acme Travel Cover (`T-ACME`, `data/tenants/acme/`) is a fictional insurer with 10 claims (CLM-5001 to CLM-5010), 8 customers, 10 policies, 3 handlers and an admin. Its sign-off limit is $750.00 and its SLA 8 hours. It sits apart from the 35-claim UnderCover queue, which the labels in `data/evals/` and the tests depend on.
  - Each tenant has its own settings. `tenant_reference` (migration 0004) holds a tenant's own company settings; a tenant without one uses the shared `reference`. The sign-off limit, SLA, run timeout and wording version are read per tenant.
  - The sign-in throttle is stored in `login_failures` (migration 0004), so a restart or a second process does not reset it.
  - SQLite runs in WAL mode with a 30-second busy timeout. `--reset` also removes the `-wal` and `-shm` files.
- 2026-11-03, Phase 5a: the scripted baseline is fixed and asserted (queue: decisions 20/35, payouts 11/35, an expected section cited 8/35, over-limit approvals waiting 11/11). It checks the harness, not decision quality. The real-model runs that the risk rules need (medical documents off and on) are written out in `docs/EVALUATION.md` but not run. Python 289 passed at 98%, TypeScript 42 at 96.3%, Playwright 16 of 16.
- Still open, by the risk rules in `docs/PLAN_PRODUCTION.md` section E: the claim instructions don't yet say what to do with a withheld medical document, so the agent may decide the six medical claims differently. Changing the instructions now would move the fingerprint with nothing to measure it against. The 5a tooling can now measure the six claims with the gate on and off (`--medical on|off`), but it needs a real-model run. Startup recovery still frees every tenant's claims, which is correct, because a restart ends every tenant's runs. The plans and the policy wording are still shared by both tenants.

The harness plan is in `docs/PLAN_HARNESS.md`.

| Harness phase | State |
|---|---|
| 1 Sections of the wording and the manual | Done |
| 2 The claim agent, hardened | Done |
| 3 Queue runs in the backend | Done |
| 4 The queue agent | Done |
| 5 The dashboard | Done |
| 6 A live run and the docs | Done |

The pilot's plan is in `docs/PLAN.md`. The earlier plan is kept in `docs/PLAN_EXTENDED.md`.

| Phase | State |
|---|---|
| 1 Data and read API | Done |
| 2 The agent decides | Done |
| 3 Sign-off | Done |
| 4 Runs and the live trace | Done |
| 5 The dashboard | Done |
| 6 Voice backend | Done |
| 7 Voice in the dashboard | Done, except the manual microphone check |

## Manual checks

| Check | Result |
|---|---|
| Real model run on CLM-1001 | 2026-10-30, `openai/gpt-6-luna`: approve, $420.00, paid. Section 3. Trip Delay. Reason: a crew cancellation delayed the departure past the Premium six-hour waiting period, and the receipts support the hotel, meals and taxis. Its first parallel calls guessed the policy and customer ids from the claim id, then it corrected itself from the 404 replies. |
| Live queue run, harness | 2026-11-01, after reseeding, a run capped at 5 on `deepseek/deepseek-v4.1-flash` (low): it ordered the claims itself (CLM-1001, 1002, 1004, 1005, then 1003), worked all 5 on the first attempt, and ended `succeeded` at its cap in 2 min 7 s with 357,530 tokens (78,874 for the queue agent, about 50,000 to 61,000 per claim). Four approvals paid ($420.00, $580.00, $186.00, $243.00); CLM-1003, $3,750.00, waits for sign-off. The other 30 claims stayed waiting, nothing was left in progress, and no claim has more than one decision or payment. Each claim read 10 to 13 sections, manual sections included, and cited 6 to 9. The dashboard showed the to-do list fill in and tick off as the run went (`docs/screens/run-live-dark.png`, `run-finished-dark.png`, `trace-dark.png`). Two things to watch: the claims read more sections than they needed, which is most of their tokens, and some reasons run to four sentences rather than two or three. |
| Voice in the browser, misheard claim numbers and reply time | Not done yet: it needs a person with a real microphone in Chrome or Edge. |
