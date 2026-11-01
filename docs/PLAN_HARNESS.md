# The harness: plan

The CipherCover Agent grows from "decide the claim you're given" into "work the queue". A **queue agent** plans the run as a to-do list, hands each claim to a fresh **claim agent** (a subagent), and ends with a summary for the handlers. The claim agent looks up the sections of the wording and the claims manual it needs instead of being handed the whole wording. Problems are put right automatically: provider errors are retried, failed claims go back in the queue and a claim that fails twice is left for a handler. The production points in `docs/HARNESS.md` (8 to 15) add budgets, leases, writes scoped to one claim, checks on each decision, an audit trail and a Stop button.

The plan starts from the pilot as `docs/STATUS.md` describes it. `docs/PLAN.md` is finished and stays as it is.

## What the plan builds and what it leaves out

Built: points 1 to 15 of `docs/HARNESS.md`, the dashboard changes they need, and updates to `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md`.

Left out, as the brief's "Not for now" says: moving off SQLite, a LangGraph graph of our own, Supabase, evaluation runs against `data/evals/`, versioned agent configuration, sign-in, a check for instructions hidden in claims, and memory across runs. Voice is unchanged, apart from what it reads from the instructions endpoint. No new Python or npm dependencies. `deepagents` is already in `pyproject.toml`, but the brief asks for our own agent rather than another framework, so it isn't used.

## Key design choices

1. **Two agents, both LangChain's `create_agent`, each with its own tools.** The queue agent (`agent/queue.py`) can read the queue, keep the to-do list, work a claim and finish the run. The claim agent (`agent/main.py`) can read one claim, look up sections, calculate, decide and pay. The queue agent has no decision or payment tools at all (point 12). Each claim gets a new claim agent with an empty message history (point 3), so each claim's work costs the same however long the run is. The claim agent reports back in one line.
2. **The backend enforces the rules, and the agent stays thin.** Point 5 and points 8 to 15 sit mostly in the backend, where one check covers every path: the cap, the token budget, leases, writes scoped to one claim, decisions that can't be repeated, the check for missed claims, and Stop. The agent learns about each one from a 409 reply it can read, as it already does for the $1,000 rule. That keeps `CODE_STANDARDS.md`'s "avoid overly defensive code" true for the agent.
3. **LangChain's built-in middleware for retries and step limits.** `ModelRetryMiddleware` retries timeouts, rate limits, connection errors and 5xx replies up to 3 times, waiting 1, 2 and 4 seconds with a little random jitter (point 9). The OpenAI client's own retries are turned off (`max_retries=0`), so there is only one retry policy. `ModelCallLimitMiddleware` caps the claim agent's model calls (point 8). Both ship with `langchain`, which is already in our stack, so they aren't another framework.
4. **The to-do list lives in the backend, not in the agent's state.** LangChain's `TodoListMiddleware` would keep the list in the agent's memory, where the dashboard can't see it. Our `write_todos` tool saves the whole list to the queue run through the API, and the dashboard polls it. Items are `to_do`, `in_progress`, `done` or `left_for_handler`; Stop and the end of a run turn whatever is left into `not_started`.
5. **The run id is a required body field on each write, filled in by the tool, never by the model.** `calculate_payout`, `record_decision` and `pay_claim` take `run_id`, which the tool reads from its LangGraph config, just as it already reads `model`. The backend refuses a write unless that run is a live claim run holding the lease on that claim (point 12). The model can't name another run because the argument isn't part of the tool's schema.
6. **Sections, not documents.** `list_sections` gives the number, title and size of each section of the wording or the manual. `read_section` returns one section and records the read on the run. The claim page shows those reads, and `record_decision` refuses to cite a section the run never read (point 13). The longest section, manual section 7, is about 4,700 characters, so no lookup floods the context.
7. **A failed attempt stays in its column, with a tag.** Claim states stay as the spec has them: `waiting`, `in_progress`, `waiting_for_signoff` and `decided`. Each claim gets a `failed_attempts` count. At 2 the claim is *left for a handler*: it stays in Waiting with a "Left for a handler" tag, queue runs skip it, and a handler can still start a named run on it. This keeps the board's four columns and avoids a fifth state that nothing yet needs.
8. **Recovery on startup is simple because runs live in the backend's process.** When the backend starts, no run can still be live, so every claim in `in_progress` returns to `waiting` with one more failed attempt, and every run still marked running ends `failed` with "The backend restarted." (point 10).
9. **Limits are stored on each queue run.** The limits are set when the run starts, from environment variables with defaults, and saved on the run. The agent reads them from the API, and the run history shows what each run was allowed.

## Conventions

- As in the pilot: states, decisions, money in integer cents, 24 hour times, and operations with an `operation_id`, a one-line docstring and no optional inputs. `cap: 0` means no cap.
- Section ids look like `wording-5` and `manual-9`.
- Queue run statuses: `running`, `stopping`, `succeeded`, `stopped`, `paused` and `failed`. Claim run (attempt) statuses: `running`, `succeeded` and `failed`, with a `failure` of `""`, `provider`, `step_limit`, `time_limit` or `error`.
- Settings and defaults (all in `.env.example`):

| Setting | Default | What it limits |
|---|---|---|
| `CLAIM_STEP_LIMIT` | 30 | Model calls by the claim agent on one claim |
| `agent_run_timeout_seconds` in `data/company.json` | 120 | Time on one claim |
| `RUN_TOKEN_LIMIT` | 1,000,000 | Tokens across the whole run, both agents |
| `PROVIDER_FAILURES_TO_PAUSE` | 3 | Claims in a row that fail for provider reasons before the run pauses |
| `MODEL_TIMEOUT_SECONDS` | 60 | One model call |

- Tests never call a model. `agent/stub.py` gains a scripted queue model, and a `FaultyModel` wrapper that can time out, raise rate limit or 5xx errors a set number of times, return a decision citing an unread section, or keep calling tools past its step limit.

## API

New or changed operations. Everything else is as in `docs/PLAN.md`.

| operation_id | Route | Purpose |
|---|---|---|
| list_sections | GET /api/documents/{source}/sections | Number, title and size of each section of `wording` or `manual` |
| read_section | GET /api/documents/{source}/sections/{number}?run_id= | One section's text, with the read recorded on the run |
| get_instructions | GET /api/instructions | *Changed:* `{queue, claim, fingerprint}` |
| calculate_payout | POST /api/claims/{claim_id}/calculate | *Changed:* body gains `run_id` |
| record_decision | POST /api/claims/{claim_id}/decision | *Changed:* body gains `run_id`; `section` becomes `sections` (a list of ids) |
| pay_claim | POST /api/claims/{claim_id}/pay | *Changed:* body gains `run_id` |
| start_queue_run | POST /api/runs | *Changed:* body `{cap}`; 409 while a queue run is live |
| list_queue_runs | GET /api/queue-runs | The last 20 queue runs, newest first |
| get_queue_run | GET /api/queue-runs/{run_id} | Status, limits, to-do list, usage, summary and stop reason |
| list_queue_run_events | GET /api/queue-runs/{run_id}/events | The queue agent's own steps |
| write_todos | PUT /api/queue-runs/{run_id}/todos | Replace the to-do list |
| begin_attempt | POST /api/queue-runs/{run_id}/attempts | Lease a claim for a new claim run, or 409 with the reason (cap, budget, stopping, paused, not waiting, left for a handler) |
| finish_attempt | POST /api/runs/{run_id}/finish | End a claim run with its failure kind and token usage; returns the one-line outcome |
| finish_queue_run | POST /api/queue-runs/{run_id}/finish | Record the summary, or 409 listing waiting claims still within the cap |
| stop_queue_run | POST /api/queue-runs/{run_id}/stop | Ask the live run to stop after the claim in hand |
| list_claims, get_claim | | *Changed:* add `failed_attempts` and `left_for_handler`; a claim's runs gain attempt, failure, tokens, model calls, seconds and sections read |

`start_run` (one named claim) still runs the claim agent directly, with no queue run, and voice keeps using it.

## Phase 1: Sections of the wording and the manual

**Why first:** both the new claim agent and the claim page depend on looking up sections and recording what was read. Building the backend for that first fixes the section ids every later phase uses.

Build:

- `backend/documents.py`: split `policy_wording.md` and `claims_manual.md` on their `## N.` headings. `list_sections` and `read_section` as in the API table. `read_section` takes the run id and records `(run_id, section_id, created_at)` in a new `section_reads` table. A run id that isn't a live claim run gets 409.
- The `runs` table gains the columns the later phases need (`queue_run_id`, `attempt`, `failure`, `tokens`, `model_calls`, `model`), and claims gain `failed_attempts`. The schema changes, so the plan says to reseed with `uv run -m backend.seed --reset`.
- `docs/SPEC.md`: the manual moves out of "Not for now". Decisions follow the wording first and the manual where the wording is silent, as section 1 of the manual says. Add a queue run, the to-do list and "left for a handler" under "What the team needs to see".

Success criteria:

- [x] `list_sections` for `wording` returns 12 sections and for `manual` 14, each with an id, a title and a character count. An unknown source returns 404.
- [x] `read_section('manual', 9)` returns only section 9, "Repeat claims", and starts with its heading. Number 15 returns 404.
- [x] With a live claim run, the read appears in `section_reads`. With a finished or unknown run, it's refused with 409.
- [x] `docs/SPEC.md` no longer lists the manual under "Not for now".
- [x] `npm run check:python` passes. Commit.

## Phase 2: The claim agent, hardened

**Why now:** the queue agent hands claims to this agent, so it must be correct and safe on its own first. Every point that applies to one claim (4, 6, 8, 9, 11, 12, 13) is built and tested here, on a named-claim run.

Build:

- **Model:** `DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"` with `reasoning_effort="low"`. `MODEL_NAME` still overrides it, as now. `ChatOpenAI` gets `timeout=MODEL_TIMEOUT_SECONDS` and `max_retries=0`.
- **Tools:** the claim agent loses the whole wording from its prompt and gains `list_sections` and `read_section`. `calculate_payout`, `record_decision` and `pay_claim` fill in `run_id` from config. `record_decision` takes `sections: list[str]`.
- **Middleware:** `ModelRetryMiddleware(max_retries=3, initial_delay=1, backoff_factor=2, jitter=True, retry_on=<provider errors>, on_failure="error")` and `ModelCallLimitMiddleware(run_limit=CLAIM_STEP_LIMIT, exit_behavior="end")`.
- **Time limit:** `run` checks the clock between steps and raises `ClaimTimeout` after `agent_run_timeout_seconds`. A single model call is already bounded by its own timeout.
- **Usage:** each model step in the trace carries its `usage_metadata`. `runs.record` adds the tokens and the model calls to the claim run.
- **Backend checks:** `calculate_payout`, `record_decision` and `pay_claim` refuse with 409 unless `run_id` is a live claim run on that claim. `record_decision` also refuses a claim that isn't `in_progress`, an empty reason, an empty `sections` list, or a section the run never read; the detail says which. A repeated decision or payment is refused. The existing payout checks stay. The decision stores `sections` and `run_id`.
- **The failure kind:** `runs.work` sorts what went wrong into `provider` (the retries ran out), `step_limit`, `time_limit` or `error`, and stores it. A failed run adds one to the claim's `failed_attempts` and returns the claim to `waiting`.
- **Instructions:** `backend/instructions.md` becomes `backend/instructions_claim.md`, rewritten from the wording and the manual and nothing else. It covers checking the history for a third claim in 12 months, using `list_sections` and then reading what the claim needs, citing every section relied on, meals without receipts, and when to refer. `get_instructions` returns `{queue, claim, fingerprint}`, where `fingerprint` is the first 12 hex digits of the SHA-256 of both texts. Voice keeps its own endpoint.
- **Stubs:** the scripted claim model reads `wording-10` and cites it. `FaultyModel` as described in the conventions.

Success criteria:

- [x] `model_name()` is `deepseek/deepseek-v4.1-flash` when `MODEL_NAME` is unset and `openrouter/free` when it's set to that. The model is built with `reasoning_effort="low"` and `max_retries=0`.
- [x] A stub run on CLM-1001 ends `succeeded`. Its trace includes `read_section` and the claim's run lists `wording-10` among its sections read. The decision stores `sections == ["wording-10"]` and the run id.
- [x] The system prompt no longer contains the wording: it's shorter than the instructions plus 500 characters.
- [x] A `FaultyModel` that raises a rate limit error twice and then answers ends `succeeded` after 2 retries, with no failed attempt. One that keeps raising 5xx ends `failed` with failure `provider`, and the claim is `waiting` with `failed_attempts == 1`. Tests pass `initial_delay=0`, so they don't wait.
- [x] A `FaultyModel` that loops past `CLAIM_STEP_LIMIT=5` ends `failed` with `step_limit`. A clock moved past the time limit ends `failed` with `time_limit`.
- [x] `record_decision` with a run id from another claim, from a finished run, or with no run is refused with 409. So are `calculate_payout` and `pay_claim`.
- [x] A decision citing `manual-9` when the run read only `wording-10` is refused with a detail naming `manual-9`. A `FaultyModel` that makes that mistake once and then reads the section and decides again ends `succeeded`.
- [x] Recording a second decision on a decided claim, and paying a paid claim, are both refused with 409.
- [x] Each model step's tokens are summed onto the run: a stub reporting 100 tokens per call over its 8 calls shows `tokens == 800` and `model_calls == 8`.
- [x] `get_instructions` returns both texts and a 12-character fingerprint. Neither text mentions `data/evals`, and a test checks that no file under `agent/` or `backend/` opens `data/evals`.
- [x] `npm run check:python` passes. Commit.

## Phase 3: Queue runs in the backend

**Why now:** the queue agent is only as safe as the operations it calls. Building and testing them first, driven by a plain Python script standing in for the agent, proves points 1, 5, 8, 10, 14 and 15 without any model.

Build:

- `backend/queue_runs.py` and a `queue_runs` table: `run_id`, `status`, `cap`, the limits, `model`, `reasoning_effort`, `fingerprint`, `todos` (JSON), `summary`, `stop_reason`, `tokens`, `consecutive_provider_failures`, `started_at`, `ended_at`.
- `start_queue_run {cap}` refuses with 409 while a queue run is `running` or `stopping`. It saves the limits and starts `runner.execute_queue` in the worker thread. It returns the run id.
- `begin_attempt {claim_id}` checks, in order, that the run is `running` (`stopping` gives "The run is stopping.", `paused` gives "The run is paused after provider errors."), that the tokens are under the limit ("The token budget is spent."), that the claim is `waiting` and not left for a handler, and that the cap allows another distinct claim. A retry of a claim already taken in this run doesn't count against the cap. Then it leases the claim: it creates the claim run, numbers the attempt and moves the claim to `in_progress`.
- `finish_attempt` ends the claim run as Phase 2 does. A `provider` failure adds one to the queue run's run of consecutive provider failures, and a success resets it to 0. At `PROVIDER_FAILURES_TO_PAUSE` the queue run becomes `paused`. It returns one line: "CLM-1001: approve, $420.00, paid", "CLM-1011: approve, $1,150.00, waiting for sign-off", "CLM-1004: failed (provider), back in the queue" or "CLM-1004: failed twice, left for a handler".
- `write_todos` replaces the list. Each item is a claim id, a status and a short note.
- `finish_queue_run {summary}` refuses with 409 while the run is `running`, under its token budget, and some waiting claim that isn't left for a handler is still within its cap. The detail lists those claims (the check for missed claims, point 5). A `stopping` or `paused` run, or one with no budget left, may always finish. Finishing sets the status (`succeeded`, `stopped` or `paused`) and `stop_reason`, and turns any `to_do` item into `not_started`.
- `stop_queue_run` moves a `running` run to `stopping`.
- `runner.execute_queue` wraps the queue agent. If the agent raises or returns without finishing, the backend closes the run: `paused` if the cause was a provider error, otherwise `failed` with the error. Any claim still `in_progress` on this run goes back to `waiting` with a failed attempt, as point 5 asks.
- On startup, `lifespan` recovers stale claims and runs, as in design choice 8.
- `list_queue_runs`, `get_queue_run` and `list_queue_run_events`. The queue agent's steps are stored in `run_events` under the queue run's id.

Success criteria (driven by a scripted Python stand-in, not a model):

- [x] A second `start_queue_run` while one is `running` returns 409. Once the first has finished, a new one starts.
- [x] With `cap: 2`, `begin_attempt` on two claims succeeds and a third distinct claim returns 409 ("The cap is reached."). A retry of the first claim after it failed succeeds.
- [x] After a failed attempt the claim is `waiting` with `failed_attempts == 1`, and it can be begun again. After a second failure it's left for a handler: `begin_attempt` refuses it, and `list_claims` shows `left_for_handler: true`.
- [x] A second `begin_attempt` on a claim that is `in_progress` returns 409. A test with two threads gets exactly one lease.
- [x] With `RUN_TOKEN_LIMIT=1000` and 1,200 tokens used, `begin_attempt` returns 409 ("The token budget is spent."), `finish_queue_run` is allowed, and `stop_reason` is `token_limit`.
- [x] Three provider failures in a row move the run to `paused`. A success in between resets the count.
- [x] `finish_queue_run` with an untouched waiting claim within the cap returns 409 naming that claim. After it is worked, finishing succeeds.
- [x] `stop_queue_run` during an attempt: the attempt still finishes, the next `begin_attempt` returns 409, finishing gives `stopped`, the `to_do` items become `not_started` and those claims stay `waiting`.
- [x] A stand-in that raises halfway leaves no claim `in_progress`, and the run ends `failed`.
- [x] Seeding a database with a claim `in_progress` and a run `running`, then starting the app, leaves the claim `waiting` with `failed_attempts == 1` and the run `failed` with "The backend restarted."
- [x] `get_queue_run` returns the cap, the limits, the model, the reasoning effort, the fingerprint, the to-do list, the tokens and the summary. `list_queue_runs` returns newest first, at most 20.
- [x] `npm run check:python` passes. Commit.

## Phase 4: The queue agent

**Why now:** with the operations safe, the queue agent can be thin: plan, hand out claims, keep the list and summarize.

Build:

- `agent/queue.py`: `run_queue(queue_run_id, llm=None, claim_llm=None, on_step=None)`, built with `create_agent`, the same retry middleware and `ModelCallLimitMiddleware(run_limit=4 * claims + 20)`. Its tools:
  - `list_waiting_claims`: the waiting claims that aren't left for a handler, with id, type, amount and failed attempts. No story, no documents.
  - `write_todos`.
  - `work_claim(claim_id)`: calls `begin_attempt`, runs a fresh claim agent through `main.run`, and calls `finish_attempt` with the failure kind and tokens. It returns the one-line outcome, or the 409 reason. Its `try` around the claim agent is the one place the agent catches errors, so one bad claim can't stop the run.
  - `get_run_status`: the cap, the claims taken so far, the tokens used and the status.
  - `finish_run(summary)`.
- `backend/instructions_queue.md`: read the waiting claims, write the to-do list (decide routine claims first and longer or older ones after), work each claim and tick it off, retry a claim that failed once, mark one that failed twice as left for a handler, then finish with a summary of three to six lines covering decisions, payouts waiting for sign-off, and claims left for a handler with the reason. If `finish_run` names missed claims, work them. If a reply says the run is stopping, paused or out of budget, update the list and finish.
- `runner.execute_queue` uses the scripted queue model and claim model when `AGENT_STUB=1`.
- The scripted queue model: list, write the to-do list, work each claim, mark each one off, finish.

Success criteria (stub models only):

- [ ] A stub queue run with `cap: 3` on a fresh database decides 3 claims, leaves the other 32 `waiting`, and ends `succeeded` with a summary. Its to-do list has 3 items, all `done`.
- [ ] Each claim run in that queue run has its own events and its own first message ("Claim CLM-…"), with no messages from another claim.
- [ ] The queue agent's tools don't include `record_decision`, `pay_claim` or `calculate_payout`, and the backend refuses a decision sent with the queue run's id.
- [ ] A claim agent that raises on CLM-1002 doesn't stop the run: the other claims are decided, CLM-1002 is tried again, and if it fails again it's left for a handler and its to-do item is `left_for_handler`.
- [ ] A queue model that tries to finish early is refused, works the missed claim, and then finishes.
- [ ] A queue model whose provider keeps failing leaves the run `paused`, with no claim `in_progress`.
- [ ] A named-claim `start_run` still works and voice's tests still pass.
- [ ] `npm run check:python` passes. Commit.

## Phase 5: The dashboard

**Why now:** the API holds everything the team needs to see. This phase shows it, in the console style of `BRAND.md`.

Build:

- **Command bar:** "Run all waiting" becomes a run control. It has a cap field (a mono number field, default 5, with "All" for 0) and a Run button. While a run is live, the Run button is replaced by a Stop button and a run status chip.
- **Run panel, on the Queue view above the board:** the live or latest run's to-do list, one row per item. Each row has its claim id in mono, its note and a status chip with a word and a color: To do in Lagoon, In progress in Ultraviolet with the pulsing dot, Done in Citron, Left for a handler in Tangerine, Not started in muted Lilac Mist. Beneath it are the tokens, the time used, the model, and the cap and limits. When the run ends, its summary appears in Fraunces italic, along with its stop reason. The panel polls with the board every 2 seconds.
- **Run history:** a collapsible list of the last 20 runs, each with its start time, status, claims worked and tokens. Clicking a run shows its to-do list and summary in the panel.
- **Board cards:** a "Left for a handler" chip on claims with 2 failed attempts.
- **Claim drawer:** the Trace groups steps by attempt ("Attempt 2 · failed (provider)"), with each attempt's tokens and time. A new **Sections read** list on the Trace tab shows each section's id and title in order. The Decision tab lists the sections relied on and the model that decided.
- **Instructions view:** two raised panels, "Running the queue" and "Working a claim", each with Copy, and the fingerprint in mono.
- Playwright on `AGENT_STUB=1`.

Success criteria:

- [ ] Vitest: the run panel shows each to-do status with its word; Stop is shown only while a run is live; the cap field sends `{cap: 5}` and "All" sends `{cap: 0}`; the history opens a past run; the drawer groups the trace by attempt and lists sections read; the Instructions view shows both panels and the fingerprint. TypeScript coverage stays at or above 80%.
- [ ] Playwright: a run with cap 3 fills the to-do list, ticks off 3 items, shows the summary, and leaves the other claims in Waiting.
- [ ] Playwright: opening a decided claim shows `wording-10` under Sections read and on the Decision tab.
- [ ] Playwright: Stop during a run ends it `stopped`, with the remaining items Not started.
- [ ] The Playwright brand check passes in dark and light mode: chips carry labels, focus rings show, and text meets AA. Screenshots are refreshed in `docs/screens/`.
- [ ] `npm run check` passes. Commit.

## Phase 6: A live run and the docs

**Why now:** everything passes on stubs. This phase checks the real model once, as the brief asks, and brings the docs up to date.

Build and check:

- `uv run -m backend.seed --reset`, then `npm run dev`. Start a run capped at 5 on the default model, DeepSeek V4.1 Flash, with `MODEL_NAME` unset.
- Update `docs/TECH_STACK.md` (two entry points, the default model, the middleware), `docs/STATUS.md` (what's built, the settings and their defaults, how to run, the live check) and `docs/SPEC.md` if anything changed during the build. Add the settings to `.env.example`.

Success criteria:

- [ ] The live run works exactly 5 claims and ends `succeeded`. The other 30 claims stay `waiting`. The model on the run and its decisions is `deepseek/deepseek-v4.1-flash`.
- [ ] In the browser, the to-do list fills in and is ticked off as the run goes. Each of the 5 claims shows its steps and the sections it read, including at least one manual section. The summary shows the tokens and time used, and the run appears in the history. The tokens are recorded in `docs/STATUS.md`.
- [ ] No claim is `in_progress` after the run, and no claim has more than one decision or payment.
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is.
- [ ] `npm run check` passes. Commit.

## Final report

When Phase 6 is done, run `npm run check` and report the Python and TypeScript coverage, the Playwright results, and the live run's claims, decisions, tokens and time. Don't push.
