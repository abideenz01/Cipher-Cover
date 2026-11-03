"""The evaluation run: a fixed score for the scripted model, and no leaks."""

import json
import os
from pathlib import Path

import pytest

from agent import main
from agent.stub import ScriptedModel
from evals import compare, datasets, run, store

# What the scripted model scores on the queue set, which approves and pays
# every item on every claim. These figures are fixed: if one moves, the
# scorer, the payout rules or the labels changed.
QUEUE = {
    "run_succeeded": (35, 35),
    "decision_correct": (20, 35),
    "payout_exact": (11, 35),
    "decision_and_payout": (11, 35),
    "cites_an_expected_section": (8, 35),
    "cites_every_expected_section": (0, 35),
    "refer_precision": (0, 0),
    "refer_recall": (0, 8),
    "over_limit_waits_for_sign_off": (11, 11),
}


@pytest.fixture(scope="module")
def queue():
    """Score the scripted model on the whole queue set once for this module."""
    llm = ScriptedModel()
    return llm, run.evaluate("queue", llm, keep=False)


def counts(scores):
    return {k: (m["k"], m["n"]) for k, m in scores["overall"].items()}


def test_the_scripted_model_scores_the_same_every_time(queue):
    _, result = queue
    assert counts(result["scores"]) == QUEUE
    assert result["scores"]["confusion"] == {
        "approve->approve": 20,
        "decline->approve": 7,
        "refer->approve": 8,
    }
    again = run.evaluate("queue", ScriptedModel(), tiny=True, keep=False)
    first = {o["claim_id"]: o for o in result["rows"]}
    for row in again["rows"]:
        same = first[row["claim_id"]]
        for key in ("decision", "payout_cents", "sections", "state", "tokens"):
            assert row[key] == same[key], (row["claim_id"], key)


def test_the_report_gives_n_intervals_and_small_sample_warnings(queue):
    _, result = queue
    text = result["report"]
    assert "synthetic labels" in text
    assert "None of them is a significance test." in text
    assert "decision_correct" in text
    assert "20/35" in text
    assert "95% CI 40.9% to 72.0%" in text
    assert "insufficient sample (n<30)" in text
    medical = result["scores"]["slices"]["medical_documents"]["yes"]
    assert medical["decision_correct"]["n"] == 6
    assert medical["decision_correct"]["sufficient_sample"] is False
    payout = result["scores"]["continuous"]["payout_error_dollars"]
    assert payout["n"] == 35
    assert payout["median_ci95"] is not None


def test_no_answer_key_reaches_the_agent(queue):
    llm, _ = queue
    seen = "\n".join(m.text for prompt in llm.prompts for m in prompt)
    labels = datasets.load("queue").labels.values()
    assert seen
    for label in labels:
        assert label.reason not in seen, label.claim_id
    assert "over_approval_limit" not in seen


def test_the_staged_data_holds_no_labels(tmp_path):
    data = datasets.load("security")
    staged = tmp_path / "staged"
    staged.mkdir()
    run.stage(data, staged)
    names = {p.name for p in staged.iterdir()}
    assert names == {*run.SHARED, "claims.json", "policies.json", "customers.json"}
    text = "".join(p.read_text(encoding="utf-8") for p in staged.iterdir())
    for label in data.labels.values():
        assert label.reason not in text
    assert '"decision"' not in text


def test_the_run_leaves_the_process_as_it_found_it():
    before = (os.environ.get("DB_PATH"), os.environ.get("DATA_DIR"), main.backend)
    run.evaluate("security", ScriptedModel(), keep=False)
    after = (os.environ.get("DB_PATH"), os.environ.get("DATA_DIR"), main.backend)
    assert before == after


def test_the_command_line_stores_the_run_and_compares_two(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("EVAL_DB_PATH", str(tmp_path / "evals.db"))
    out = tmp_path / "scores.json"
    first = run.main_cli(["--set", "security", "--json", str(out)])
    assert "Evaluation" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["meta"]["dataset"] == "security"
    second = run.main_cli(["--set", "security", "--medical", "on"])
    stored = store.run(second["meta"]["eval_run_id"])
    assert stored["medical"] == 1
    assert stored["n"] == 3
    text = compare.compare(store.run(first["meta"]["eval_run_id"]), stored)
    assert "changed: medical: 0 -> 1" in text
    assert "no evidence of a difference" in text
    other = run.main_cli(["--set", "security", "--tiny"])
    with pytest.raises(ValueError, match="cannot be compared"):
        compare.compare(stored, store.run(other["meta"]["eval_run_id"]))
    with pytest.raises(KeyError):
        store.run("nope")


def test_backend_and_agent_never_import_the_evaluation():
    for path in [*Path("backend").rglob("*.py"), *Path("agent").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "import evals" not in text, path
        assert "from evals" not in text, path
