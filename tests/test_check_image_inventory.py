"""Tests for the shipped-image inventory gate (#346).

The gap this closes is not "some image had a CVE" -- it is that nothing
enumerated the images, so coverage was whatever `security.yml` happened to
name and nobody could tell. These pin the two directions that make the set
closed (a Dockerfile with no entry fails, an entry with no Dockerfile fails)
and the check that makes the inventory more than a document: a shipped entry
must name jobs that actually exist.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-image-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_image_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKFLOW = """\
name: demo
on: [push]
jobs:
  containers:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
  other-job:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


def _tree(tmp_path: Path, images: list[dict[str, object]], dockerfiles: list[str]) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "security.yml").write_text(WORKFLOW, encoding="utf-8")
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality" / "image-inventory.json").write_text(
        json.dumps({"images": images}), encoding="utf-8"
    )
    for name in dockerfiles:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("FROM scratch\n", encoding="utf-8")
    return tmp_path


def _run(gate, tmp_path: Path, monkeypatch) -> int:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "INVENTORY", tmp_path / "quality" / "image-inventory.json")
    monkeypatch.setattr(gate, "WORKFLOWS", tmp_path / ".github" / "workflows")
    return gate.main()


SHIPPED = {
    "id": "demo",
    "dockerfile": "Dockerfile",
    "disposition": "PUBLISHED",
    "rationale": "the one image",
    "built_by": [".github/workflows/security.yml:containers"],
    "scanned_by": [".github/workflows/security.yml:containers"],
    "published_by": ".github/workflows/security.yml:containers",
}


def test_a_matching_inventory_passes(gate, tmp_path, monkeypatch):
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 0


def test_a_dockerfile_with_no_entry_fails(gate, tmp_path, monkeypatch, capsys):
    """The failure #346 is actually about. `Dockerfile.research` existed and
    was unscanned; nothing said so because nothing enumerated the images."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile", "Dockerfile.research"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "Dockerfile.research: on disk, not in the inventory" in capsys.readouterr().out


def test_an_entry_with_no_dockerfile_fails(gate, tmp_path, monkeypatch, capsys):
    """Otherwise the inventory rots into a list of things that used to exist,
    and its counts start describing a repository nobody has."""
    tree = _tree(tmp_path, [SHIPPED], [])
    assert _run(gate, tree, monkeypatch) == 1
    assert "Dockerfile: in the inventory, not on disk" in capsys.readouterr().out


def test_a_shipped_entry_naming_a_job_that_does_not_exist_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """The check that makes this more than a document.

    "Add the image to the list" is cheap, and would let a coverage claim drift
    from coverage exactly the way the unscanned images did. Naming a job that
    has to exist is what costs something.
    """
    entry = {**SHIPPED, "scanned_by": [".github/workflows/security.yml:no-such-job"]}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "declares no job 'no-such-job'" in capsys.readouterr().out


def test_a_shipped_entry_with_no_scan_job_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "scanned_by": []}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `scanned_by` job" in capsys.readouterr().out


def test_a_published_entry_with_no_publisher_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "published_by": None}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `published_by` job" in capsys.readouterr().out


def test_an_internal_entry_needs_no_jobs_but_needs_a_reason(gate, tmp_path, monkeypatch, capsys):
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "INTERNAL",
        "rationale": "",
        "built_by": [],
        "scanned_by": [],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no rationale" in capsys.readouterr().out


def test_an_internal_entry_that_claims_a_scan_job_fails(gate, tmp_path, monkeypatch, capsys):
    """A scanned image is DISTRIBUTED or PUBLISHED. Letting INTERNAL claim a
    scan would give the cheapest disposition the strongest-looking evidence."""
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "INTERNAL",
        "rationale": "test harness only",
        "built_by": [],
        "scanned_by": [".github/workflows/security.yml:containers"],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "entries name no scanned_by" in capsys.readouterr().out


def test_a_retired_entry_must_name_a_successor_and_an_owner(gate, tmp_path, monkeypatch, capsys):
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "RETIRED",
        "rationale": "superseded",
        "built_by": [],
        "scanned_by": [],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "RETIRED needs `replaced_by`" in out
    assert "RETIRED needs `removal_owner`" in out


def test_an_unknown_disposition_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "disposition": "PROBABLY_FINE"}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "is not one of" in capsys.readouterr().out


def test_dockerignore_files_are_not_images(gate, tmp_path, monkeypatch):
    """`Dockerfile.rsi-runner.dockerignore` sits beside its Dockerfile and
    matches `Dockerfile*`. It configures a build; it is not one."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile", "Dockerfile.rsi-runner.dockerignore"])
    assert _run(gate, tree, monkeypatch) == 0


def test_the_real_inventory_matches_the_real_repository(gate):
    """Not a unit test of the gate — the gate run against this repository.

    Everything above uses a synthetic tree, which proves the logic and proves
    nothing about the tree that ships.
    """
    assert gate.main() == 0
