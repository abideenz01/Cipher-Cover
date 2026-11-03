"""Score finished claim runs against the handlers' decisions, and print a report."""

from collections import Counter
from collections.abc import Callable
from typing import Any

from evals.datasets import Label
from evals.stats import SUFFICIENT, distribution, proportion

Outcome = dict[str, Any]
Check = Callable[[Label, Outcome], bool]

CHECKS: dict[str, Check] = {
    "run_succeeded": lambda _, o: o["status"] == "succeeded",
    "decision_correct": lambda label, o: o["decision"] == label.decision,
    "payout_exact": lambda label, o: o["payout_cents"] == label.payout_cents,
    "decision_and_payout": lambda label, o: (
        o["decision"] == label.decision and o["payout_cents"] == label.payout_cents
    ),
    "cites_an_expected_section": lambda label, o: bool(
        set(o["sections"]) & set(label.sections)
    ),
    "cites_every_expected_section": lambda label, o: (
        set(label.sections) <= set(o["sections"])
    ),
}

SLICES: dict[str, Callable[[Label], str]] = {
    "difficulty": lambda label: label.difficulty,
    "claim_type": lambda label: label.claim_type,
    "expected_decision": lambda label: label.decision,
    "medical_documents": lambda label: "yes" if label.medical else "no",
}


def rate(pairs: list[tuple[Label, Outcome]], check: Check) -> dict[str, Any]:
    """Return the proportion of pairs that pass a check."""
    return proportion(sum(check(label, o) for label, o in pairs), len(pairs))


def score(
    labels: dict[str, Label], outcomes: list[Outcome], limit_cents: int
) -> dict[str, Any]:
    """Return every metric, overall and by slice, each with its n."""
    pairs = [(labels[o["claim_id"]], o) for o in outcomes]
    overall = {name: rate(pairs, check) for name, check in CHECKS.items()}
    referred = [(lab, o) for lab, o in pairs if o["decision"] == "refer"]
    should_refer = [(lab, o) for lab, o in pairs if lab.decision == "refer"]
    overall["refer_precision"] = rate(referred, lambda lab, _: lab.decision == "refer")
    overall["refer_recall"] = rate(should_refer, lambda _, o: o["decision"] == "refer")
    over = [
        (lab, o)
        for lab, o in pairs
        if o["decision"] == "approve" and o["payout_cents"] > limit_cents
    ]
    overall["over_limit_waits_for_sign_off"] = rate(
        over, lambda _, o: o["state"] == "waiting_for_signoff" and not o["paid_cents"]
    )
    decided = [(lab, o) for lab, o in pairs if o["decision"]]
    continuous = {
        "payout_error_dollars": distribution(
            [abs(o["payout_cents"] - lab.payout_cents) / 100 for lab, o in decided]
        ),
        "seconds_per_claim": distribution([o["seconds"] for _, o in pairs]),
        "tokens_per_claim": distribution([float(o["tokens"]) for _, o in pairs]),
    }
    slices = {
        name: {
            value: {
                "decision_correct": rate(group, CHECKS["decision_correct"]),
                "payout_exact": rate(group, CHECKS["payout_exact"]),
            }
            for value, group in sorted(grouped(pairs, key).items())
        }
        for name, key in SLICES.items()
    }
    confusion = Counter(
        f"{lab.decision}->{o['decision'] or 'none'}" for lab, o in pairs
    )
    return {
        "n": len(pairs),
        "overall": overall,
        "continuous": continuous,
        "slices": slices,
        "confusion": dict(sorted(confusion.items())),
    }


def grouped(
    pairs: list[tuple[Label, Outcome]], key: Callable[[Label], str]
) -> dict[str, list[tuple[Label, Outcome]]]:
    """Group pairs by a slice of their label."""
    groups: dict[str, list[tuple[Label, Outcome]]] = {}
    for label, outcome in pairs:
        groups.setdefault(key(label), []).append((label, outcome))
    return groups


def flag(metric: dict[str, Any]) -> str:
    """Mark a figure whose sample is too small to lean on."""
    return (
        "" if metric["sufficient_sample"] else f"  insufficient sample (n<{SUFFICIENT})"
    )


def line(name: str, metric: dict[str, Any]) -> str:
    """Format one proportion with its interval."""
    if not metric["n"]:
        return f"  {name:<40} n=0, nothing to score"
    low, high = metric["ci95"]
    return (
        f"  {name:<40} {metric['k']:>3}/{metric['n']:<3} {metric['rate']:6.1%}"
        f"  95% CI {low:5.1%} to {high:5.1%}{flag(metric)}"
    )


def spread(name: str, metric: dict[str, Any]) -> str:
    """Format one continuous measure."""
    if not metric["n"]:
        return f"  {name:<40} n=0"
    ci = metric["median_ci95"]
    interval = f", 95% CI of median {ci[0]:.2f} to {ci[1]:.2f}" if ci else ""
    return (
        f"  {name:<40} n={metric['n']} median {metric['median']:.2f}"
        f" p90 {metric['p90']:.2f} range {metric['min']:.2f} to {metric['max']:.2f}"
        f"{interval}{flag(metric)}"
    )


def report(meta: dict[str, Any], scored: dict[str, Any]) -> str:
    """Return the report as text: the set, the run, then every figure with its n."""
    lines = [
        f"Evaluation {meta['eval_run_id']}",
        f"  set {meta['dataset']} v{meta['version']}, {meta['provenance']} labels:"
        f" {meta['labeller']}",
        f"  model {meta['model']}, instructions {meta['fingerprint']},"
        f" medical documents to the model: {'on' if meta['medical'] else 'off'}",
        f"  claims scored: {scored['n']}",
        "  These figures describe synthetic, single-handler labels. None of them is"
        " a significance test.",
        "",
        "Overall",
        *(line(name, m) for name, m in scored["overall"].items()),
        *(spread(name, m) for name, m in scored["continuous"].items()),
        "",
        "Expected -> actual decision",
        *(f"  {k:<40} {v}" for k, v in scored["confusion"].items()),
    ]
    for name, values in scored["slices"].items():
        lines += ["", f"By {name.replace('_', ' ')}"]
        for value, metrics in values.items():
            lines += [line(f"{value}: {m}", metric) for m, metric in metrics.items()]
    return "\n".join(lines)
