# Evaluation

How Cipher Cover measures the claim agent against the handlers' decisions, and what the numbers can and cannot tell you.

## Running it

```bash
uv run -m evals.run --set queue                      # scripted model, all 35 claims
uv run -m evals.run --set queue --tiny               # the five-claim subset
uv run -m evals.run --set held_out --model real --limit 5
uv run -m evals.run --set queue --model real --medical on
uv run -m evals.compare BEFORE_ID AFTER_ID           # two stored runs
uv run -m evals.datasets                             # list the sets and check them
```

- `--model stub`, the default, uses the scripted model. It costs nothing and its score is fixed, which makes it a check of the harness and the scorer, not of decision quality.
- `--model real` uses the agent's model on OpenRouter, so it needs `OPENROUTER_API_KEY` and costs money. Use `--limit` to cap it.
- `--medical on` lets the model see medical records and bills, the tenant setting `external_model_medical`. The default is off, as in production.
- Each run prints its report and stores it, with every claim's result, in `evals.db`, or in `EVAL_DB_PATH` if that is set. Pass `--json FILE` to also write the scores to a file.

## How a run works

1. The set is loaded from `data/`. Its files are checked against `data/evals/MANIFEST.json`, and a changed set is refused (see Datasets).
2. A temporary data folder gets the set's claims, policies and customers, plus the insurer's files (company, plans, handlers, wording, manual). It never gets the decisions. A temporary backend database is seeded from that folder.
3. For each claim, the agent runs through the backend's API with a claim token, exactly as in production, and its trace is recorded.
4. Only after every claim is done does `evals/score.py` read the labels and score the runs.

The `evals/` package sits outside `backend/` and `agent/`. Neither of those imports it, and the API cannot serve it. `evals/tests/test_run.py` checks that no handler's reason, and nothing else from the answer keys, appears in any prompt the model saw.

## Datasets

| Set | n | Files |
|---|---|---|
| `queue` | 35 | `data/claims.json`, `data/evals/decisions.json` |
| `held_out` | 25 | `data/evals/held_out_claims.json`, `held_out_decisions.json` |
| `harder` | 25 | `data/evals/harder/` |
| `even_harder` | 25 | `data/evals/even_harder/`, which depends on facts in `knowledge.json` that the agent has no tool to read |
| `security` | 3 | `data/security/`, the prompt-injection claims |

Every set is **synthetic**: written as a benchmark, with one handler's decision per claim, no second rater and no adjudication. No figure here describes real claims, and no figure here measures fraud. The follow-up decisions and the voice scenarios are not evaluated yet.

The manifest records each set's version, n, provenance and a SHA-256 of each file's text (with line endings normalised). After any change to a set, bump `VERSION` in `evals/datasets.py` and run `uv run -m evals.datasets --write`. Runs on different versions cannot be compared.

## Metrics

Proportions, each with its k, its n and a 95% Wilson score interval:

| Metric | Passes when |
|---|---|
| `run_succeeded` | the run ended without an error |
| `decision_correct` | approve, decline or refer matches the label |
| `payout_exact` | the payout matches to the cent (0 for a decline or referral) |
| `decision_and_payout` | both of the above |
| `cites_an_expected_section` | at least one cited section is in the label's reference |
| `cites_every_expected_section` | every section in the reference was cited |
| `refer_precision` | of the claims the agent referred, the label also referred |
| `refer_recall` | of the claims the label referred, the agent also referred |
| `over_limit_waits_for_sign_off` | an approval over the sign-off limit was left waiting and unpaid. This is a guardrail and should always be 100% |

Continuous measures (payout error in dollars, seconds and tokens per claim) show the median, the 90th percentile and the range. They add a 95% percentile-bootstrap interval for the median, with 2,000 seeded resamples, once n is at least 20.

The report repeats the two proportions by difficulty, claim type, expected decision and whether the claim has medical documents. Any figure with n under 30 is marked **insufficient sample**, which means every slice. No figure is a significance test. `evals.compare` says only whether two intervals overlap, and overlapping intervals mean no evidence of a difference at that n.

## Baseline: the scripted model

Run on 2026-11-03 with instructions fingerprint `1c8b2cef2c28`, set version 2026.11 and medical documents off. The scripted model approves and pays every item on every claim, so these figures only show that the harness and the scorer work. They are fixed: `test_the_scripted_model_scores_the_same_every_time` asserts the queue row.

| Set | Runs succeeded | Decision correct | Payout exact | Cites an expected section | Refer recall | Over limit waits |
|---|---|---|---|---|---|---|
| queue | 35/35 | 20/35 | 11/35 | 8/35 | 0/8 | 11/11 |
| held_out | 25/25 | 14/25 | 8/25 | 7/25 | 0/6 | 7/7 |
| harder | 25/25 | 14/25 | 0/25 | 9/25 | 0/6 | 20/20 |
| even_harder | 25/25 | 17/25 | 5/25 | 16/25 | 0/2 | 9/9 |
| security | 3/3 | 1/3 | 1/3 | 1/3 | 0/0 | 1/1 |

## Baseline: the real model

Not run yet, because it costs money. These are the runs to make before any change to the agent's instructions or tools, and before choosing how the instructions treat a withheld medical document:

```bash
uv run -m evals.run --set queue --model real                  # medical off, as in production
uv run -m evals.run --set queue --model real --medical on
uv run -m evals.compare OFF_ID ON_ID
```

Look at the `medical_documents: yes` slice (6 claims in the queue). With n=6, only a large difference means anything, so read the six claims' results in `eval_results` one by one, as well as the rates.

## Using it for a change

1. Run the set on the current code and keep the run id.
2. Make the change. An instruction change moves the fingerprint, and the report shows it.
3. Run again and compare with `uv run -m evals.compare BEFORE_ID AFTER_ID`.
4. Record both ids, the fingerprints and the comparison in `docs/STATUS.md`.
