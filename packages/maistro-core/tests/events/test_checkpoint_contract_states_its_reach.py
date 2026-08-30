"""The superseded checkpoint contract says it is superseded (#729).

`events/checkpoints.py` is 428 lines carrying exactly what a canonical
checkpoint should: `schema_version`, `executable_version`, a content hash, Run
ids, an append-only store. Nothing constructs any of it. The record that *is*
the canonical checkpoint of a graph execution is `DurableRunRecord`, which
`resume_durable_graph` reads and `GraphContinuationStore` persists with a real
PostgreSQL twin (ADR-083026-ebcb).

Two mechanisms hid that, and both are asserted here rather than merely fixed.
The module was counted *reachable* because `maistro.events.__init__` re-exported
it — the walker treats an `ImportFrom` in a package `__init__` as an edge like
any other — and its store's methods were kept off the dead-code ledger by a
tuple of references that existed only to be referenced. Nothing imported those
names from the package, so the re-export published a surface with no consumer.

These read the real modules. A test asserting on a transcribed docstring proves
nothing about the docstring that ships.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro.events import checkpoints
from maistro.orchestrator.waves import ensemble

pytestmark = [pytest.mark.contract("behavioral")]

_REPO = Path(__file__).resolve().parents[4]
_MIGRATIONS = _REPO / "alembic" / "versions"
_EVENTS_INIT = _REPO / "packages/maistro-core/src/maistro/events/__init__.py"
_BASELINE = _REPO / "quality/reachability-baseline.json"
_DISPOSITIONS = _REPO / "quality/reachability-dispositions.json"

_MODULE = "maistro.events.checkpoints"
_CONTRACT = _REPO / "packages/maistro-core/src/maistro/events/checkpoints.py"


class TestTheContractStatesItsReach:
    @pytest.mark.ac("SPEC-083026-7297/AC-1")
    def test_the_module_says_nothing_constructs_one(self) -> None:
        doc = (checkpoints.__doc__ or "").lower()
        assert "nothing in this repository constructs one" in doc

    @pytest.mark.ac("SPEC-083026-7297/AC-1")
    def test_it_names_the_record_that_supersedes_it(self) -> None:
        """ "Superseded" without a successor is an invitation to delete it. The
        successor is the whole content of the decision."""
        doc = checkpoints.__doc__ or ""
        assert "DurableRunRecord" in doc
        assert "ADR-083026-ebcb" in doc

    @pytest.mark.ac("SPEC-083026-7297/AC-1")
    def test_it_says_its_table_reaches_no_deployment(self) -> None:
        doc = (checkpoints.__doc__ or "").lower()
        assert "canonical_checkpoints" in doc
        assert "no revision" in doc or "no migration" in doc


class TestThePackageStopsPublishingIt:
    @pytest.mark.ac("SPEC-083026-7297/AC-2")
    def test_the_events_package_does_not_re_export_the_superseded_names(self) -> None:
        import maistro.events as events

        exported = set(getattr(events, "__all__", ()))
        assert not (exported & {"Checkpoint", "CheckpointStore", "SqliteCheckpointStore"})
        assert not hasattr(events, "Checkpoint")

    @pytest.mark.ac("SPEC-083026-7297/AC-2")
    def test_no_tuple_keeps_the_store_methods_looking_used(self) -> None:
        """A keep-alive turns a true signal into a false one: vulture's finding
        was correct, and answering it by manufacturing a reference is worse than
        having no check. The absence belongs in the ledger instead."""
        assert "_CHECKPOINT_STORE_OPERATIONS" not in _EVENTS_INIT.read_text()

    @pytest.mark.ac("SPEC-083026-7297/AC-2")
    def test_the_package_says_why_it_stopped(self) -> None:
        import maistro.events as events

        doc = events.__doc__ or ""
        assert "not re-exported" in doc
        assert "#729" in doc


class TestTheLedgerCountsItHonestly:
    @pytest.mark.ac("SPEC-083026-7297/AC-3")
    def test_the_baseline_records_it_as_unreachable(self) -> None:
        baseline = json.loads(_BASELINE.read_text())["unreachable"]
        assert _MODULE in baseline

    @pytest.mark.ac("SPEC-083026-7297/AC-3")
    def test_the_dispositions_ledger_gives_it_an_owner_and_a_successor(self) -> None:
        groups = json.loads(_DISPOSITIONS.read_text())["groups"]
        owning = [g for g in groups if _MODULE in g["modules"]]
        assert len(owning) == 1, "exactly one group owns it"
        [group] = owning
        assert group["disposition"] == "RETIRE"
        assert group["replaced_by"].strip()
        assert "durable_runs" in group["replaced_by"]


class TestTheTwoStoresDoNotCollide:
    @pytest.mark.ac("SPEC-083026-7297/AC-4")
    def test_they_really_do_share_a_name_and_no_methods(self) -> None:
        """The premise of the disambiguation, asserted rather than assumed: if
        these ever converge, the docstrings below become wrong."""
        canonical = {m for m in vars(checkpoints.CheckpointStore) if not m.startswith("_")}
        wave = {m for m in vars(ensemble.CheckpointStore) if not m.startswith("_")}
        assert canonical and wave
        assert not (canonical & wave)

    @pytest.mark.ac("SPEC-083026-7297/AC-4")
    def test_each_names_the_other(self) -> None:
        assert "waves.ensemble" in (checkpoints.CheckpointStore.__doc__ or "")
        assert "events.checkpoints" in (ensemble.CheckpointStore.__doc__ or "")

    @pytest.mark.ac("SPEC-083026-7297/AC-4")
    def test_the_reached_one_is_named_as_the_reached_one(self) -> None:
        """Which is which is the fact a reader needs; two stores that merely
        cross-reference each other still leave it ambiguous."""
        assert "reached" in (ensemble.CheckpointStore.__doc__ or "").lower()


class TestTheClaimedAbsencesAreTrue:
    @pytest.mark.ac("SPEC-083026-7297/AC-5")
    def test_no_revision_creates_the_canonical_checkpoint_table(self) -> None:
        creating = [
            path.name
            for path in sorted(_MIGRATIONS.glob("*.py"))
            if "canonical_checkpoints" in path.read_text()
        ]
        assert creating == []

    def test_the_migration_scan_has_a_corpus(self) -> None:
        """A guard that reads no files guards nothing."""
        assert len(list(_MIGRATIONS.glob("*.py"))) > 10

    @pytest.mark.ac("SPEC-083026-7297/AC-5")
    def test_no_source_module_imports_the_superseded_contract(self) -> None:
        """The statement is a claim about the repository, so the repository
        settles it. Tests import it freely — that is all it is for.

        Imports, not constructor calls. Scanning for `InMemoryCheckpointStore(`
        would match the *wave* store of the same name, and `Checkpoint(` matches
        `TaskCheckpoint(`, which is the reached one — the very ambiguity AC-4
        exists to end. An import names a module and cannot be confused.
        """
        importers = sorted(
            str(path.relative_to(_REPO))
            for path in _REPO.glob("packages/*/src/**/*.py")
            if _imports_it(path.read_text()) and path.resolve() != _CONTRACT.resolve()
        )
        assert importers == []

    def test_the_import_scan_finds_one_when_there_is_one(self) -> None:
        """A scan that can only return empty proves nothing. This is the shape
        it will see the day something wires the contract again."""
        assert _imports_it("from maistro.events.checkpoints import Checkpoint")
        assert _imports_it("import maistro.events.checkpoints")
        assert not _imports_it("# maistro.events.checkpoints is superseded")
        assert not _imports_it("from maistro.tasks.checkpoint import TaskCheckpoint")


class TestARetiredDuplicateCannotBecomeAuthoritative:
    @pytest.mark.ac("SPEC-083026-7297/AC-6")
    def test_the_container_wires_no_second_checkpoint_store(self) -> None:
        """#62's fifth acceptance bullet, given a mechanism rather than a
        sentence. A duplicate lifecycle store cannot become authoritative after
        a restore because nothing wires one; this fails the day something does.
        The durable-run path is not spelled `Checkpoint`, so it is unaffected."""
        container = (_REPO / "packages/maistro-core/src/maistro/container.py").read_text()
        wired = [
            line.strip()
            for line in container.splitlines()
            if "CheckpointStore(" in line or _imports_it(line)
        ]
        assert wired == []


def _imports_it(text: str) -> bool:
    """Whether `text` imports the superseded contract module.

    A comment mentioning it is not an import, and the modules now name it in
    prose, so the line has to start with `import` or `from`.
    """
    return any(
        stripped.startswith(
            ("import maistro.events.checkpoints", "from maistro.events.checkpoints")
        )
        for stripped in (line.strip() for line in text.splitlines())
    )
