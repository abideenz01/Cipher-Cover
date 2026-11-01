# Status

Kept up to date as `docs/PROCESS.md` asks: updated at the end of every phase and after every change.

## What's built

- `backend/`: FastAPI on SQLite (`backend/db.py`). On startup it seeds an empty database from `data/` (`backend/seed.py`), reading only the company, plans, policies, customers, handlers and claims. The read API is in `backend/claims.py`. No operation returns a customer's email, phone, date of birth or address.
- `backend/payout.py` applies section 10 of the wording; `backend/decisions.py` has `calculate_payout`, `record_decision` and `pay_claim`. `pay_claim` refuses any payout over $1,000.00, which waits for a handler's sign-off. The agent's instructions are `backend/instructions.md`.
- `backend/signoff.py`: `list_signoffs`, `sign_off_claim` (HND-01 to HND-03 only; signing off pays the claim) and `send_back_claim`. A sign-off waiting longer than `sign_off_sla_hours` is `overdue`.
- `backend/runs.py`: `start_run` and `start_queue_run` run the agent in a background thread (`backend/runner.py`); each step is stored as a run event for `list_run_events`. A run that raises or ends without a decision fails and returns its claim to `waiting`. `AGENT_STUB=1` swaps in the scripted model.
- `backend/voice/`: the voice operations, all 404 unless `VOICE_ENABLED=1` except `get_voice_config`. Briefs speak money and claim ids in words and never carry a story, document text or personal data. `request_signoff` only records a request for 10 minutes; a handler's click is the sign-off. Turns are rate limited per session (`VOICE_TURNS_PER_MINUTE`), time out after 30 seconds with a spoken fallback, and are logged in `voice_turns`.
- `agent/voice.py`: the voice agent, `run_turn(session_id, handler_id, text, llm=None)`, with nine tools and `backend/voice_instructions.md` as its prompt. `agent/voice_stub.py` is its scripted model.
- `agent/`: `run(claim_id, thread_id, llm=None, on_step=None)` in `agent/main.py`, with six tools over the API. `agent/stub.py` is a scripted model for tests that approves and pays every item.
- `dashboard/`: the Cipher Cover console from `BRAND.md`. A rail (Queue, Sign-off, Instructions), a command bar (`/` to search, theme switch, Run all waiting), a metric strip, a four-column board and a claim drawer with Overview, Documents, Decision and Trace tabs. The board polls every two seconds; the trace polls every second while a run is live. Styles are all in `dashboard/src/theme.css`.
- `dashboard/src/voice/`: voice in the dashboard. A mic button in the command bar (hold it or hold `V` to talk, a tap for hands-free, Escape stops speech), a captions panel with the acting handler and a Type instead field, and a one-time consent notice. `focus_signoff` highlights the claim on the Sign-off view with a Confirm button; only that click signs off. With voice off there is no mic and no panel. Speech uses the browser's own recognition and synthesis (Chrome or Edge); `VOICE_PROVIDER=stub` is for Playwright.
- `backend/documents.py`: `list_sections` and `read_section` split the policy wording and the claims manual on their numbered headings (`wording-5`, `manual-9`). Each read is recorded in `section_reads` against a live claim run.
- `e2e/`: Playwright tests of the dashboard against a backend on a fresh temporary database with `AGENT_STUB=1`.
- `docs/screens/`: screenshots of the dashboard in dark and light mode.

## How to run it

- `uv sync` and `npm install`, then `npm run dev` for the backend on port 8000 and the dashboard on port 5173.
- The database is `undercover.db` at the repo root, or `DB_PATH` if set. `uv run -m backend.seed --reset` rebuilds it from `data/`. The harness changes the schema, so a database from the pilot must be rebuilt this way.
- `npm run check` runs every check.
- To try voice, set `VOICE_ENABLED=1` in `.env` and open the dashboard in Chrome or Edge. `.env.example` lists the voice settings.
- The agent calls the backend at `http://127.0.0.1:8000`, not `localhost`: on Windows, `localhost` tries IPv6 first and adds about two seconds to every call.

## Notes

- Cherry with white text is 4.45 to 1, just under WCAG AA, so the Decline and Overdue chips use a slightly deeper Cherry, `#D41F49`. Every other color is as `BRAND.md` gives it.
- The brand review of the screens was done with a Playwright script (`chromium.launch`), because no Playwright MCP server is connected in these sessions.
- 2026-10-30: this machine was moved to Node 26.13.0 LTS, and `%SystemRoot%\System32` was added back to the user PATH so Playwright can stop its servers. With both, `npm install` and `npm run check` pass with no workarounds: Python 91 tests at 98.7%, TypeScript 27 tests at 96.0%, Playwright 11 of 11 in about 45 seconds.

## Phases

The harness plan is in `docs/PLAN_HARNESS.md`.

| Harness phase | State |
|---|---|
| 1 Sections of the wording and the manual | Done |
| 2 The claim agent, hardened | Not started |
| 3 Queue runs in the backend | Not started |
| 4 The queue agent | Not started |
| 5 The dashboard | Not started |
| 6 A live run and the docs | Not started |

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
| Voice in the browser, misheard claim numbers and reply time | Not done yet: it needs a person with a real microphone in Chrome or Edge. |
