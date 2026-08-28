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
import subprocess
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
        monkeypatch.setattr(check, "_trusted_baseline", _trusted(check, recorded))
        assert check.main([]) == 1
    capsys.readouterr()


def test_main_passes_when_the_ledger_matches(check, monkeypatch, capsys):
    ledger = {"demo.Root": {"known": "why"}}
    monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["known"]})
    monkeypatch.setattr(check, "_load_baseline", lambda *a: ledger)
    monkeypatch.setattr(check, "_trusted_baseline", _trusted(check, ledger))
    assert check.main([]) == 0
    assert "matches the current unread set" in capsys.readouterr().out


def _trusted(check, entries):
    """Stand in for the base-revision ledger without building a git history.

    `main` judges new debt against the base (#534), so a test that only
    substitutes the worktree ledger would be judged against the real
    repository's and fail for reasons it never set up.
    """
    baseline = check._provenance().Baseline(
        text="{}", origin="base", base_sha="0" * 40, path=Path("ledger.json")
    )
    return lambda *a, e=entries: (e, baseline)


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


class TestTheLedgerIsNotItsOwnOracle:
    """#534: banking a regression on the branch must not answer for it.

    Before this, adding an unread field, running `--update`, and writing the
    disposition were three edits one commit could make, and the gate went green
    with the unread count silently raised. The trusted ledger now comes from the
    base revision, so those edits change the bookkeeping and not the verdict.
    """

    def _weakened(self, check, monkeypatch, *, trusted, authorized=None):
        """A candidate that measures one more unread field than the base has."""
        banked = {"demo.Root": {"known": "why", "fresh": "self-written justification"}}
        monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["known", "fresh"]})
        monkeypatch.setattr(check, "_load_baseline", lambda *a: banked)
        monkeypatch.setattr(check, "_trusted_baseline", _trusted(check, trusted))
        prov = check._provenance()
        monkeypatch.setattr(prov, "load_authorizations", lambda *a, **k: authorized or {})
        monkeypatch.setattr(check, "_provenance", lambda: prov)

    def test_banking_and_justifying_in_one_tree_still_fails(
        self, check, monkeypatch, capsys
    ) -> None:
        self._weakened(check, monkeypatch, trusted={"demo.Root": {"known": "why"}})

        assert check.main([]) == 1
        assert "NEWLY UNREAD against the trusted baseline" in capsys.readouterr().err

    def test_the_verdict_names_the_commit_it_judged_against(
        self, check, monkeypatch, capsys
    ) -> None:
        """A failure a reader cannot trace to a base is not auditable."""
        self._weakened(check, monkeypatch, trusted={"demo.Root": {"known": "why"}})

        check.main([])

        assert "baseline: base " + "0" * 12 in capsys.readouterr().out

    def test_an_explicit_authorization_lets_a_deliberate_floor_raise_through(
        self, check, monkeypatch, capsys
    ) -> None:
        """The escape hatch is a separate file `--update` never writes."""
        self._weakened(
            check,
            monkeypatch,
            trusted={"demo.Root": {"known": "why"}},
            authorized={"demo.Root.fresh": "#534 -- @owner: consumed downstream"},
        )

        assert check.main([]) == 0
        assert "authorized: demo.Root.fresh" in capsys.readouterr().out

    def test_removing_a_tolerated_entry_needs_no_authorization(
        self, check, monkeypatch, capsys
    ) -> None:
        """Improvements bank automatically; only new debt is gated."""
        ledger = {"demo.Root": {"known": "why"}}
        monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["known"]})
        monkeypatch.setattr(check, "_load_baseline", lambda *a: ledger)
        monkeypatch.setattr(
            check,
            "_trusted_baseline",
            _trusted(check, {"demo.Root": {"known": "why", "gone": "was"}}),
        )

        assert check.main([]) == 0
        capsys.readouterr()

    def test_an_unreadable_base_fails_rather_than_trusting_the_candidate(
        self, check, monkeypatch, capsys
    ) -> None:
        """The fallback that would reopen the hole."""
        prov = check._provenance()

        def _refuse(*_a, **_k):
            raise prov.RatchetProvenanceError(
                "base revision 'origin/develop' could not be resolved"
            )

        monkeypatch.setattr(check, "unread_fields", lambda *a: {"demo.Root": ["known"]})
        monkeypatch.setattr(check, "_trusted_baseline", _refuse)

        assert check.main([]) == 1
        assert "could not be resolved" in capsys.readouterr().err


class TestTheSeamsTheOtherTestsSubstitute:
    """Every test above replaces `_trusted_baseline` and the ledger shim, which
    is what makes them cheap — and leaves the real ones unexercised. These run
    them for real, because a seam nothing ever executes is a seam that can rot.
    """

    def test_entries_from_tolerates_a_ledger_that_is_not_the_shape_it_expects(self, check) -> None:
        """The base ledger comes from an arbitrary revision, so it may predate
        this schema, be `null`, or have been hand-edited. None of those should
        crash the gate — they mean "nothing trusted is recorded"."""
        assert check._entries_from(None) == {}
        assert check._entries_from([1, 2, 3]) == {}
        assert check._entries_from({}) == {}
        assert check._entries_from({"roots": "not-a-mapping"}) == {}

    def test_entries_from_reads_the_real_shape(self, check) -> None:
        loaded = {"roots": {"demo.Root": {"source": _SOURCE, "unread": {"f": "why"}}}}

        assert check._entries_from(loaded) == {"demo.Root": {"f": "why"}}

    def test_trusted_baseline_resolves_or_refuses_by_what_the_checkout_offers(self, check) -> None:
        """The unsubstituted path, run against whatever checkout we are in.

        Both outcomes are correct and both are asserted, because which one
        happens is a property of the checkout rather than of the code. CI runs
        this suite in `ci.yml`'s `test` job, which clones shallow; the gate
        itself runs in `quality.yml`, which sets `fetch-depth: 0`. An earlier
        version of this test asserted only the resolving case and failed in the
        shallow job -- correctly, which is the point: with no merge base the
        resolver must refuse and say why, never quietly fall back to the
        candidate's own ledger. That refusal is the invariant the whole change
        exists to protect, so it is worth pinning in the environment that
        actually produces it.
        """
        prov = check._provenance()
        has_base = (
            subprocess.run(
                ["git", "merge-base", "origin/develop", "HEAD"],
                cwd=ROOT,
                capture_output=True,
            ).returncode
            == 0
        )

        if has_base:
            trusted, baseline = check._trusted_baseline()
            assert isinstance(trusted, dict)
            assert baseline.origin == "base"
            assert baseline.base_sha
        else:
            with pytest.raises(prov.RatchetProvenanceError, match="no merge base"):
                check._trusted_baseline()

    def test_a_helper_that_fails_to_load_leaves_no_broken_module_behind(
        self, check, monkeypatch, tmp_path
    ) -> None:
        """A half-executed module left in `sys.modules` would be handed to the
        next caller as if it had loaded, so the loader removes it and re-raises.
        Worth pinning: the cache that makes this fast is what makes the failure
        sticky if it is not cleaned up.
        """
        broken = tmp_path / "ratchet_provenance.py"
        broken.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        monkeypatch.setattr(check, "_PROVENANCE_SOURCE", broken)
        monkeypatch.delitem(sys.modules, "_ratchet_provenance", raising=False)

        with pytest.raises(RuntimeError, match="boom"):
            check._provenance()

        assert "_ratchet_provenance" not in sys.modules
