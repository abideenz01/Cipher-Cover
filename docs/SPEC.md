# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue

One run works the whole queue. The agent plans the run as a to-do list, works each waiting claim with a fresh helper for that claim, and ends with a short summary for the handlers. A run can be capped at a number of claims, with the rest left waiting, and the agent can still be run on one named claim.

A claim that fails before it is decided goes back in the queue to be tried again. A claim that fails twice is left for a handler: it stays waiting, runs of the queue skip it, and a handler can still run the agent on it. No claim is ever decided or paid twice. A run has limits on the steps and the time for each claim and on the tokens for the whole run, pauses itself after repeated errors from the model provider, and can be stopped from the dashboard.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off or decided.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, including the sections of the wording and the manual it read.
- The current run's to-do list, with each item to do, in progress, done, left for a handler or not started, and each run's summary, usage and limits in a run history.
- Which claims are left for a handler.
- The agent's instructions for running the queue and for working a claim, read only.

## Rules

- A payout over $1,000 needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- Decisions follow the policy wording, and the claims manual where the wording is silent. The wording always comes first.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The agent must never see them.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Sign-in and tenants

- Everyone signs in with an email and password. A session ends after 30 minutes idle or 12 hours, whichever comes first.
- Each person belongs to one tenant (an insurer) and sees only that tenant's claims, policies, customers, runs and voice sessions. A record in another tenant is answered as not found.
- Roles decide what a person may do. A claims handler reads the queue, runs the agent, sends claims back and uses voice. A senior handler can also sign off payouts over $1,000.00. An SIU investigator, an auditor and a tenant admin can read; the auditor and the admin can also read the security log. Nobody but the agent records a decision or pays, and the agent only through its own run.
- Medical records and medical bills never go to the model unless the tenant has said they may. Agents see a customer's first name and last initial only.
- Isolation between tenants is enforced by the application on SQLite. Production with more than one tenant's data needs PostgreSQL with row-level security first (`docs/ADR_POSTGRES.md`).

## Not for now

- A tenant admin adds sign-ins, sets their roles, turns them off and on, and decides whether medical documents may go to the model. Creating a tenant is not for now: tenants come from `data/` when the database is seeded.
- No real payments.
- No messages to customers.