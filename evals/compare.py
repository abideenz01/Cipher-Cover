"""Compare two stored evaluation runs, such as before and after a change.

    uv run -m evals.compare BEFORE_ID AFTER_ID

It prints each proportion for both runs with its interval. With n this small,
overlapping intervals mean the runs show no evidence of a difference, and
even intervals that don't overlap are not a significance test. It refuses to
compare runs on different sets or set versions, whose figures are not
comparable.
"""

import sys
from typing import Any

from evals import store
from evals.stats import overlap

SAME = ("dataset", "version", "sha256", "tiny")
COMPARED = ("model", "fingerprint", "medical")


def compare(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Return the comparison of two stored runs as text."""
    differing = [k for k in SAME if before[k] != after[k]]
    if differing:
        raise ValueError(
            "These runs used different labels and cannot be compared: "
            + ", ".join(f"{k} {before[k]} vs {after[k]}" for k in differing)
        )
    changes = [
        f"{k}: {before[k]} -> {after[k]}" for k in COMPARED if before[k] != after[k]
    ]
    lines = [
        f"Comparing {before['eval_run_id']} with {after['eval_run_id']}"
        f" on {before['dataset']} v{before['version']}",
        "  changed: " + ("; ".join(changes) if changes else "nothing recorded"),
        "  No result here is a significance test.",
        "",
    ]
    a, b = before["scores"]["overall"], after["scores"]["overall"]
    for name in a:
        left, right = a[name], b[name]
        if not left["n"] or not right["n"]:
            lines.append(f"  {name:<32} not scored in both runs")
            continue
        verdict = (
            "intervals overlap: no evidence of a difference"
            if overlap(left["ci95"], right["ci95"])
            else "intervals do not overlap"
        )
        lines.append(
            f"  {name:<32} {left['k']}/{left['n']} -> {right['k']}/{right['n']}"
            f"  ({verdict})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(compare(store.run(sys.argv[1]), store.run(sys.argv[2])))
