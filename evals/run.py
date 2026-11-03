"""Run the claim agent over an evaluation set and score it.

    uv run -m evals.run --set queue              scripted model, every claim
    uv run -m evals.run --set queue --tiny       the five-claim subset
    uv run -m evals.run --set queue --model real --limit 5
    uv run -m evals.run --set queue --model real --medical on

Each run seeds a temporary database with the set's claims, policies and
customers only: never its decisions. The agent works each claim through the
backend's API under its run's token, exactly as in production. Only when
every claim is done are the decisions read and the runs scored. The scores
go to the evaluation database (evals/store.py), never the backend's.
"""

import argparse
import json
import os
import secrets
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel

from agent import main
from agent.stub import ScriptedModel
from backend import claims, clock, db, runs, seed
from backend.main import app
from evals import datasets, score, store
from evals.datasets import Dataset

TENANT = "T-UNDERCOVER"
# The insurer's own files a set is seeded with, besides its records.
SHARED = (
    "company.json",
    "plans.json",
    "handlers.json",
    "policy_wording.md",
    "claims_manual.md",
)


@contextmanager
def environment(**values: str) -> Iterator[None]:
    """Set environment variables for the block, then put them back."""
    before = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def stage(data: Dataset, folder: Path) -> None:
    """Write a data folder holding the set's records and nothing of its labels."""
    for name in SHARED:
        shutil.copy(datasets.DATA / name, folder / name)
    for name, records in (
        ("claims.json", data.claims),
        ("policies.json", data.policies),
        ("customers.json", data.customers),
    ):
        (folder / name).write_text(json.dumps(records), encoding="utf-8")


@contextmanager
def backend_for(data: Dataset, medical: bool) -> Iterator[None]:
    """Seed a temporary backend with the set and point the agent at it."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp) / "data"
        folder.mkdir()
        stage(data, folder)
        with environment(
            DATA_DIR=str(folder),
            DB_PATH=str(Path(tmp) / "eval.db"),
            DEMO_PASSWORD=secrets.token_urlsafe(16),
        ):
            seed.seed()
            with db.connect() as conn:
                conn.execute(
                    "UPDATE tenants SET config = ? WHERE tenant_id = ?",
                    (json.dumps({"external_model_medical": medical}), TENANT),
                )
            client = TestClient(app)
            original = main.backend
            main.backend = lambda: nullcontext(client)  # type: ignore[assignment]
            try:
                yield
            finally:
                main.backend = original


def work(claim_id: str, llm: BaseChatModel, seconds: float) -> dict[str, Any]:
    """Run the agent on one claim as the backend would, and read what it did."""
    run_id = runs.begin(claim_id, TENANT)
    with db.connect() as conn:
        token = runs.claim_token(conn, run_id)
    started = time.monotonic()
    error, failure = "", ""
    try:
        with main.acting(token):
            main.run(
                claim_id, run_id, llm, lambda step: runs.record(run_id, step), seconds
            )
    except Exception as caught:  # noqa: BLE001 - one bad claim must not stop the set
        error, failure = main.describe(caught), main.failure(caught)
    runs.finish(run_id, claim_id, error, failure or "error")
    took = time.monotonic() - started
    with db.connect() as conn:
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        claim = conn.execute(
            "SELECT state FROM claims WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        decision = conn.execute(
            "SELECT * FROM decisions WHERE claim_id = ? ORDER BY id DESC LIMIT 1",
            (claim_id,),
        ).fetchone()
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()[0]
    return {
        "claim_id": claim_id,
        "status": run["status"],
        "failure": run["failure"],
        "tokens": run["tokens"],
        "seconds": round(took, 3),
        "state": claim["state"],
        "decision": decision["decision"] if decision else "",
        "payout_cents": decision["payout_cents"] if decision else 0,
        "sections": json.loads(decision["sections"]) if decision else [],
        "paid_cents": paid,
    }


def model(kind: str) -> BaseChatModel:
    """Return the scripted model, or the real one, which needs OPENROUTER_API_KEY."""
    return ScriptedModel() if kind == "stub" else main.model()


def evaluate(  # noqa: PLR0913 - each is one switch of the command line
    name: str,
    llm: BaseChatModel,
    *,
    tiny: bool = False,
    limit: int = 0,
    medical: bool = False,
    keep: bool = True,
) -> dict[str, Any]:
    """Run and score one set, store the result, and return it with the report."""
    data = datasets.load(name)
    ids = [
        c["claim_id"]
        for c in data.claims
        if not tiny or data.labels[c["claim_id"]].tiny
    ]
    ids = ids[:limit] if limit else ids
    meta = {
        "eval_run_id": uuid.uuid4().hex[:12],
        "dataset": data.name,
        "version": data.version,
        "sha256": data.sha256,
        "provenance": data.provenance,
        "labeller": datasets.LABELLER,
        "model": main.label(llm),
        "fingerprint": claims.instructions()["fingerprint"],
        "medical": medical,
        "tiny": tiny,
        "started_at": clock.stamp(),
    }
    with backend_for(data, medical):
        with db.connect() as conn:
            company = db.reference(conn, "company", TENANT)
        seconds = company["agent_run_timeout_seconds"]
        outcomes = [work(claim_id, llm, seconds) for claim_id in ids]
    limit_cents = db.cents(company["payout_approval_limit"])
    scores = score.score(data.labels, outcomes, limit_cents)
    meta["ended_at"] = clock.stamp()
    rows = [
        o
        | {
            "expected_decision": data.labels[o["claim_id"]].decision,
            "expected_cents": data.labels[o["claim_id"]].payout_cents,
            "expected_sections": list(data.labels[o["claim_id"]].sections),
        }
        for o in outcomes
    ]
    if keep:
        store.save(meta, rows, scores)
    return {
        "meta": meta,
        "scores": scores,
        "rows": rows,
        "report": score.report(meta, scores),
    }


def main_cli(argv: list[str] | None = None) -> dict[str, Any]:
    """Parse the command line, run the evaluation and print its report."""
    parser = argparse.ArgumentParser(
        prog="evals.run", description=(__doc__ or "").split("\n")[0]
    )
    parser.add_argument("--set", default="queue", choices=sorted(datasets.SETS))
    parser.add_argument("--model", default="stub", choices=["stub", "real"])
    parser.add_argument("--tiny", action="store_true", help="only the tiny subset")
    parser.add_argument("--limit", type=int, default=0, help="at most this many claims")
    parser.add_argument("--medical", default="off", choices=["on", "off"])
    parser.add_argument("--json", default="", help="also write the scores to this file")
    args = parser.parse_args(argv)
    result = evaluate(
        args.set,
        model(args.model),
        tiny=args.tiny,
        limit=args.limit,
        medical=args.medical == "on",
    )
    print(result["report"])
    if args.json:
        Path(args.json).write_text(
            json.dumps({"meta": result["meta"], "scores": result["scores"]}, indent=2),
            encoding="utf-8",
        )
    return result


if __name__ == "__main__":
    main_cli()
