# Getting ready for harder claims

From the head of claims operations, with our IT team.

## Where we're heading

Our claims are going to get harder to decide. From now on, decisions follow the claims manual as well as the policy wording, and over the coming months we expect claims with more documents, more rules to weigh and more to look up. We want the UnderCover Agent to grow into that work: taking on longer jobs, working through them on its own, and dealing with problems without someone stepping in.

In the pilot (`docs/STATUS.md`), our code does much of the organizing. It feeds the agent one claim at a time and gives it the whole policy wording every time, and a claim that fails partway stays stuck in progress. We want the agent to organize its own work instead.

## What we want

1. **One run works the whole queue.** We start the agent once and it works every waiting claim, choosing the order itself, then finishes with a short summary for the handlers. For trials we need a way to start a run capped at a number of claims, with the rest left waiting, so a trial on five claims costs little. We still need to be able to run it on one named claim.

2. **A to-do list we can watch.** The agent plans its work as a to-do list and keeps it up to date as it goes, with each item to do, in progress, done or left for a handler. The queue page of the dashboard shows the list for the current run, so the team can see what the agent means to do and how far it has got.

3. **A fresh helper for each claim.** The agent running the queue hands each claim to a subagent that works that one claim from a clean start and reports back in a line: the decision and payout, or what went wrong. This keeps each claim's work focused and stops each step getting more expensive as the run goes on. Every step on a claim is still recorded on that claim.

4. **The claims manual, looked up the way a handler would.** The manual (`data/claims_manual.md`) covers things the wording does not, such as a third claim within 12 months, losses to wild animals and meals without receipts. For each claim the agent should find and read the sections of the manual and the wording it needs, rather than being handed whole documents, and the claim page should show what it read. Please update `docs/SPEC.md`, where the manual is still "Not for now".

5. **Problems are put right automatically.** A long run will meet timeouts, errors from the model provider and steps that fail. One bad claim must never stop the run or leave a claim stuck in progress. A claim that fails before it is decided goes back in the queue to be tried again, and a claim that fails twice is left for a handler. No claim is ever decided or paid twice. Before it finishes, the agent checks that it has not missed a waiting claim within its cap.

6. **The model.** Our trials found DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash` on OpenRouter, with low reasoning effort) the best balance of accuracy, speed and cost, so it becomes the default. `MODEL_NAME` still overrides it.

7. **Instructions we can read.** The instructions page shows the agent's instructions for running the queue and for working a claim. Write them from the policy wording and the manual, never from our handlers' decisions in `data/evals/`.

## Ready for production

From our IT team. The agent will soon run unattended on a full queue, so a run has to be safe to leave alone, cheap to stop and easy to audit afterwards. These sit on top of the seven points above and change none of them.

8. **Budgets on every run.** Besides the claim cap, a run has a limit on model calls (steps) for each claim and a time limit for each claim, taken from the agent run timeout in `data/company.json`. A claim that hits its step or time limit counts as a failed attempt under point 5. A run also has an overall spend limit in tokens: when it is reached, the run stops starting new claims, finishes the claim in hand and leaves the rest waiting. The limits are settings with sensible defaults, and the run summary says which limit, if any, ended the run.

9. **Provider errors are not claim failures.** Timeouts, rate limits and server errors from OpenRouter are retried on the same model call a few times with a growing, slightly random wait, and only count against the claim if the retries run out. If several claims in a row fail for provider reasons, the run pauses itself and says so, rather than leaving the whole queue for handlers because OpenRouter was down. The model stays DeepSeek V4.1 Flash, or `MODEL_NAME`: there is no automatic switch to another model.

10. **One run at a time, one worker per claim.** Starting a queue run while one is live is refused with a clear reason. A claim being worked holds a lease tied to its run; nothing else may decide, pay or restart it while the lease is held. If the backend stops or restarts mid-run, any claim left in progress with no live run goes back to waiting on startup, with its failed attempt counted.

11. **Paying and deciding are safe to repeat.** Recording a decision on a decided claim, or paying a paid claim, is refused by the backend rather than trusted to the agent. A retried step after a timeout can therefore never double a decision or a payment. The $1,000 sign-off rule is still enforced by the backend.

12. **Each helper can only touch its own claim.** The subagent for a claim gets only the tools it needs to work a claim, and the backend refuses its writes to any other claim. The agent running the queue can read the queue, hand out claims, keep the to-do list and write the summary, but cannot decide or pay a claim itself.

13. **Decisions are checked before they are recorded.** Every decision carries the decision, the payout, a two or three sentence reason and the sections it relied on. A decision that cites a section the subagent never read, gives a payout on a decline or a refer, or is missing any part is refused, and the subagent is told why and may correct it within its step limit. Looking up a section returns that section only, so no single lookup can flood the claim's context.

14. **A run we can audit later.** Every run is kept with its cap and limits, the model and reasoning effort, a fingerprint of the instructions it ran with, its to-do list, its summary, and for each claim the number of attempts, the steps, the tokens used, the time taken and the sections read. Every decision records the run and the model that made it. The dashboard keeps a short history of past runs, each opening to its summary and to-do list.

15. **We can stop a run.** The queue page has a Stop button for the live run. The run finishes the claim in hand, marks the rest of its to-do list as not started, leaves those claims waiting and writes its summary.

## What stays the same

- The rules in `docs/SPEC.md`, including sign-off on payouts over $1,000.
- Our tech stack, including SQLite. Build these pieces into our own agent rather than adding another agent framework or a new service.
- Tests never call a model, and the code stays simple, as `docs/CODE_STANDARDS.md` asks. The points above are mostly rules the backend enforces; they should not become defensive code spread through the agent.
- No sign-in, no real payments, no messages to customers, and the agent never sees `data/evals/`.

## Not for now

The following are planned for later and are not part of this work: moving the database off SQLite or the agent onto a graph framework, evaluation runs against `data/evals/`, versioned agent configuration, sign-in, checks for instructions hidden in claims, and memory across runs.

## What done looks like

- `npm run check` is green, with tests on a stub model for each new behavior: the to-do list stored and shown, the cap on a run, a failed claim that does not stop the run, a failed claim going back in the queue and being tried again, a claim that fails twice left for a handler, and the check for missed claims.
- The stub model can be scripted to time out, return provider errors, return a malformed decision or run past its step limit, and there are tests for each production point: the step, time and spend limits; provider retries and the run pausing itself; a second run refused; a claim left in progress recovered on startup; a repeated decision or payment refused; a subagent refused a write to another claim; the queue agent unable to pay; a decision citing an unread section refused and then corrected; run history and per-claim usage stored and shown; and Stop leaving the remaining claims waiting.
- After reseeding, a run capped at five claims on the default model works five claims on its own. The dashboard shows the to-do list filling in and being ticked off, and each claim's steps, including the sections the agent read. The other claims stay waiting. The run's summary shows the tokens and time used, and the run appears in the run history.
- `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is, including the run settings and their defaults.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_HARNESS.md` and tick it off there. `docs/PLAN.md` is the pilot's finished plan and stays as it is. For any live run with the real model, reseed first and cap the run at five claims.
