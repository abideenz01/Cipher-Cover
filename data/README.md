# UnderCover seed data

The data behind UnderCover Travel Insurance, a fictional insurer. Everything here is invented, including the people, the airlines and the hotels. Amounts are in US dollars.

## The insurer's systems

- `company.json`: company settings, including the $1,000 payout approval limit, the 30 day document request window, the sign-off SLA and the agent run timeout.
- `plans.json`: the three plans (Economy, Premium, First) with their limits, waiting periods and deductibles, and the three add-ons.
- `policies.json`: one policy per trip, with the plan, the add-ons, the purchase date, the trip and the travelers.
- `customers.json`: contact details and claim history, with the date and a one line summary of each earlier claim. This is personal data.
- `handlers.json`: the claims handlers. HND-04 cannot approve over the limit and HND-05 is the Special Investigations officer.
- `claims.json`: the claims queue, thirty-five claims. Each has the customer's story, the items claimed and the supporting documents as text.
- `followups.json`: documents that customers send after a claim was referred. Each follow-up names the claim it belongs to.
- `knowledge.json`: dated events, products and places that some claims depend on.

## The documents

- `policy_wording.md` and `policy_wording_short.md`: the contract with the customer.
- `claims_manual.md`: the internal handling manual. Longer, and it holds rules the wording does not.

## The evaluation set

- `evals/decisions.json`: the handlers' decisions on the claims in the queue. An agent deciding claims must never be shown this file.
- `evals/followup_decisions.json`: the expected outcome of each claim after its follow-up documents arrive. The agent must never see it.
- `evals/held_out_claims.json` and `evals/held_out_decisions.json`: twenty-five more claims with their decisions, for checking that an improvement generalizes.
- `evals/harder/` and `evals/even_harder/`: two further sets with the same file layout. The even harder set depends on `knowledge.json`.

Every decision carries a few tags. `difficulty` is `routine`, `hard` or `manual`. `tempts` names the wrong answer a model is likely to give. `needs` lists what the claim depends on beyond the wording. `tiny` marks a small subset for quick runs.

A decision is scored on two things: the decision itself and the payout. A valid claim that pays more than $1,000 is still an approve. The payment waits for a handler's sign-off, and `over_approval_limit` marks those claims.
- `evals/voice_scenarios.json`: 19 spoken requests with the tool calls, replies and screen actions expected. The voice agent must never see it.

## A second insurer

- `tenants/acme/`: Acme Travel Cover, a second fictional insurer, seeded as tenant `T-ACME` so that tenant isolation can be shown and tested. It has its own `tenant.json` and `company.json` (a $750.00 sign-off limit and an 8 hour SLA), plus 8 customers, 10 policies, 3 handlers and 10 claims (CLM-5001 to CLM-5010). It shares the plans and the policy wording. Its claims have no labelled decisions and are not part of any evaluation set.

## The security claims

- `security/`: CLM-1901, CLM-1902 and CLM-1903. Each carries an instruction aimed at the AI inside the customer's text or a supporting document. They have their own policies, customers and handler decisions, apart from the queue and the evaluation sets.
