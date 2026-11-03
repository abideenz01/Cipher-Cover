import json
import shutil

import pytest

from evals import datasets


@pytest.mark.parametrize("name", sorted(datasets.SETS))
def test_every_set_matches_its_manifest(name):
    data = datasets.load(name)
    assert data.provenance == "synthetic"
    assert len(data.labels) == len(data.claims)
    assert all(label.sections for label in data.labels.values())
    assert {p["policy_id"] for p in data.policies} == {
        c["policy_id"] for c in data.claims
    }


def test_the_manifest_is_current():
    recorded = json.loads(datasets.MANIFEST.read_text(encoding="utf-8"))
    assert recorded == {name: datasets.manifest_entry(name) for name in datasets.SETS}
    assert {e["n"] for e in recorded.values()} == {35, 25, 3}


def test_a_changed_set_is_refused(tmp_path, monkeypatch):
    shutil.copytree(datasets.DATA, tmp_path / "data")
    monkeypatch.setattr(datasets, "DATA", tmp_path / "data")
    monkeypatch.setattr(datasets, "MANIFEST", tmp_path / "data/evals/MANIFEST.json")
    labels = tmp_path / "data/evals/decisions.json"
    changed = json.loads(labels.read_text(encoding="utf-8"))
    changed[0]["decision"] = "decline"
    labels.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(datasets.DatasetChanged, match="evals/decisions.json"):
        datasets.load("queue")
    assert datasets.load("harder").name == "harder"


def test_unknown_set():
    with pytest.raises(KeyError):
        datasets.load("nope")


@pytest.mark.parametrize(
    ("reference", "ids"),
    [
        ("Policy wording, sections 5 and 10", ("wording-5", "wording-10")),
        ("Claims manual, section 9", ("manual-9",)),
        (
            "Policy wording, section 3; Claims manual, section 10",
            ("wording-3", "manual-10"),
        ),
        ("Nothing to cite", ()),
    ],
)
def test_references_become_section_ids(reference, ids):
    assert datasets.section_ids(reference) == ids


def test_crlf_and_lf_hash_alike(tmp_path):
    unix, windows = tmp_path / "u.json", tmp_path / "w.json"
    unix.write_bytes(b"[1,\n2]\n")
    windows.write_bytes(b"[1,\r\n2]\r\n")
    assert datasets.digest(unix) == datasets.digest(windows)
