"""Tests for the wiring-reads ratchet.

The script is a CI gate, so the property that matters is that it *fails* on a
field that is wired and never read. A gate that stays quiet on the defect it
names is worse than no gate: it reads as evidence the class is handled.

The `a2a_broker` reconstruction below is the case ADR-082526-1899 was written
about. It is rebuilt here as a synthetic tree rather than pinned to a commit so
the evidence survives history rewrites, but the same check run against
`7131bfe^` reports `a2a_broker` and against `ab998ce` does not.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-wiring-reads.py"
BASELINE = ROOT / "quality" / "wiring-reads-baseline.json"
_SOURCE = "packages/demo/src/demo/container.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_wiring_reads", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path):
    """Build a synthetic production tree and return its unread-field scanner."""

    def build(check, container_src: str, **others: str) -> list[str]:
        src = tmp_path / "packages" / "demo" / "src" / "demo"
        src.mkdir(parents=True, exist_ok=True)
        (src / "__init__.py").write_text("")
        (src / "container.py").write_text(container_src)
        for name, body in others.items():
            (src / f"{name}.py").write_text(body)
        roots = (check.DIRoot(name="demo.Root", source=_SOURCE, cls="Root"),)
        return check.unread_fields(root=tmp_path, di_roots=roots)["demo.Root"]

    return build


ROOT_CLASS = """
from dataclasses import dataclass


@dataclass
class Root:
    used: object = None
    unused: object = None
    _private: object = None
"""


@pytest.mark.ac("ADR-082526-1899/AC-1")
def test_reports_a_field_no_production_module_reads(check, tree):
    """The whole point: wired, stored, and nothing reads it back."""
    unread = tree(check, ROOT_CLASS, consumer="from demo.container import Root\n")
    assert unread == ["used", "unused"]


@pytest.mark.ac("ADR-082526-1899/AC-2")
def test_a_field_read_by_any_production_module_is_silent(check, tree):
    unread = tree(
        check,
        ROOT_CLASS,
        consumer="def go(root):\n    return root.used\n",
    )
    assert unread == ["unused"]


@pytest.mark.ac("ADR-082526-1899/AC-2")
def test_the_di_root_reading_its_own_field_counts_as_a_read(check, tree):
    """`Container` consuming its own field is real use, not self-dealing."""
    unread = tree(check, ROOT_CLASS + "\n    def go(self):\n        return self.used\n")
    assert unread == ["unused"]


@pytest.mark.ac("ADR-082526-1899/AC-2")
def test_writing_a_field_is_not_reading_it(check, tree):
    """`self.x = y` is the wiring under suspicion, not evidence against it."""
    unread = tree(
        check,
        ROOT_CLASS,
        consumer="def wire(root, value):\n    root.unused = value\n",
    )
    assert unread == ["used", "unused"]


@pytest.mark.ac("ADR-082526-1899/AC-1")
def test_private_fields_are_not_the_gate_s_business(check, tree):
    assert "_private" not in tree(check, ROOT_CLASS)


@pytest.mark.ac("ADR-082526-1899/AC-3")
def test_reports_the_a2a_broker_shape(check, tree):
    """Constructed during container construction, stored, read by nobody.

    This is #225's defect as it stood at `7131bfe^`: `_wire_a2a_broker` ran on
    every construction, so every frame below it was entry-point-live and the
    transitive-deadness design proposed in #236 marks it reachable. What is
    decidable is that nothing reads the attribute back out.
    """
    container = """
from dataclasses import dataclass


@dataclass
class Root:
    a2a_broker: object = None


class _AgentMapCardResolver:
    def resolve(self, agent, user_id):
        return AgentCard.from_identity(agent.identity, user_id=user_id)


def _wire_a2a_broker(agents):
    return A2ABroker(resolver=_AgentMapCardResolver())


def create_root(agents):
    a2a_broker = _wire_a2a_broker(agents)
    return Root(a2a_broker=a2a_broker)
"""
    assert tree(check, container) == ["a2a_broker"]


@pytest.mark.ac("ADR-082526-1899/AC-4")
def test_an_uncalled_public_export_is_not_reported(check, tree):
    """The 662-entry surface stays silent: this gate only speaks about DI roots."""
    exported = (
        "class NeverCalled:\n"
        "    def method(self):\n"
        "        return 1\n"
        "\n\n"
        "def never_called():\n"
        "    return NeverCalled()\n"
    )
    unread = tree(check, ROOT_CLASS, api=exported)
    assert unread == ["used", "unused"]


@pytest.mark.ac("ADR-082526-1899/AC-1")
def test_tests_are_not_production(check, tmp_path):
    """A field only tests read is still unread — that is the defect, not a defence."""
    src = tmp_path / "packages" / "demo" / "src" / "demo"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "container.py").write_text(ROOT_CLASS)
    suite = tmp_path / "packages" / "demo" / "src" / "demo" / "tests"
    suite.mkdir()
    (suite / "test_root.py").write_text("def test_it(root):\n    assert root.used\n")
    roots = (check.DIRoot(name="demo.Root", source=_SOURCE, cls="Root"),)
    assert check.unread_fields(root=tmp_path, di_roots=roots)["demo.Root"] == ["used", "unused"]


def test_an_undeclared_class_is_a_hard_error(check, tmp_path):
    """A typo in DI_ROOTS must not read as 'nothing unread'."""
    src = tmp_path / "packages" / "demo" / "src" / "demo"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "container.py").write_text(ROOT_CLASS)
    roots = (check.DIRoot(name="demo.Missing", source=_SOURCE, cls="Missing"),)
    with pytest.raises(RuntimeError, match="declared DI root Missing not found"):
        check.unread_fields(root=tmp_path, di_roots=roots)


def test_unparseable_production_file_does_not_crash_the_gate(check, tree):
    """A syntax error elsewhere is not this gate's failure to report."""
    unread = tree(check, ROOT_CLASS, broken="def (:\n")
    assert unread == ["used", "unused"]


@pytest.mark.ac("ADR-082526-1899/AC-5")
def test_an_unbaselined_unread_field_is_reported_as_added(check):
    added, stale, undocumented = check._report({"demo.Root": ["fresh"]}, {"demo.Root": {}})
    assert added == ["demo.Root.fresh"]
    assert not stale and not undocumented


@pytest.mark.ac("ADR-082526-1899/AC-5")
def test_a_field_that_became_read_is_reported_as_stale(check):
    """The ledger can only shrink; a stale entry would absorb the next regression."""
    added, stale, undocumented = check._report(
        {"demo.Root": []}, {"demo.Root": {"now_read": "why"}}
    )
    assert stale == ["demo.Root.now_read"]
    assert not added and not undocumented


@pytest.mark.ac("ADR-082526-1899/AC-6")
def test_a_ledger_entry_without_a_disposition_is_reported(check):
    added, stale, undocumented = check._report(
        {"demo.Root": ["banked"]}, {"demo.Root": {"banked": "   "}}
    )
    assert undocumented == ["demo.Root.banked"]
    assert not added and not stale


@pytest.mark.ac("ADR-082526-1899/AC-5")
def test_main_fails_on_each_ledger_divergence(check, monkeypatch, capsys):
    for current, recorded in (
        ({"demo.Root": ["fresh"]}, {}),
        ({"demo.Root": []}, {"demo.Root": {"gone": "why"}}),
        ({"demo.Root": ["bare"]}, {"demo.Root": {"bare": ""}}),
    ):
        monkeypatch.setattr(check, "unread_fields", lambda *a, c=current: c)
        monkeypatch.setattr(check, "_load_baseline", lambda *a, r=recorded: r)
        assert check.main([]) == 1
    capsys.readouterr()


def test_main_passes_when_the_ledger_matches(check, monkeypatch, capsys):
    monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["known"]})
    monkeypatch.setattr(check, "_load_baseline", lambda *a: {"demo.Root": {"known": "why"}})
    assert check.main([]) == 0
    assert "matches the current unread set" in capsys.readouterr().out


@pytest.mark.ac("ADR-082526-1899/AC-6")
def test_update_carries_existing_dispositions_and_leaves_new_ones_empty(
    check, monkeypatch, tmp_path, capsys
):
    """Banking must not invent a rationale, so a new entry lands empty and fails."""
    written = tmp_path / "ledger.json"
    roots = (check.DIRoot(name="demo.Root", source=_SOURCE, cls="Root"),)
    monkeypatch.setattr(check, "BASELINE", written)
    monkeypatch.setattr(check, "DI_ROOTS", roots)
    monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["kept", "fresh"]})
    monkeypatch.setattr(check, "_load_baseline", lambda *a: {"demo.Root": {"kept": "reviewed"}})
    assert check.main(["--update"]) == 0
    capsys.readouterr()

    entry = json.loads(written.read_text())["roots"]["demo.Root"]
    assert entry["source"] == _SOURCE
    assert entry["unread"] == {"fresh": "", "kept": "reviewed"}

    _, _, undocumented = check._report(
        {"demo.Root": ["kept", "fresh"]}, {"demo.Root": entry["unread"]}
    )
    assert undocumented == ["demo.Root.fresh"]


def test_missing_ledger_reads_as_empty_rather_than_crashing(check, tmp_path):
    assert check._load_baseline(tmp_path / "absent.json") == {}


def test_committed_ledger_matches_the_tree(check):
    """The committed ledger is the current truth — otherwise the first CI run
    after any merge fails for reasons unrelated to that merge."""
    current = check.unread_fields()
    recorded = {
        name: dict(entry["unread"])
        for name, entry in json.loads(BASELINE.read_text())["roots"].items()
    }
    added, stale, undocumented = check._report(current, recorded)
    assert not added, f"unbaselined unread field(s): {added}"
    assert not stale, f"stale ledger entr(y/ies): {stale}"
    assert not undocumented, f"ledger entr(y/ies) with no disposition: {undocumented}"


def test_every_declared_di_root_exists(check):
    """A declaration that no longer resolves must fail loudly, not silently pass."""
    for di_root in check.DI_ROOTS:
        assert check._public_fields(ROOT / di_root.source, di_root.cls)
