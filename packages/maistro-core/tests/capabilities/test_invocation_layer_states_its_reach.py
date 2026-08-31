"""The capability Invocation layer says that nothing constructs it (#717).

The layer is complete, tested, and unreached: `grep -rn "send_invocation"
packages/ | grep -v /tests/` returns the definition and nothing else. That is a
legitimate state for code written ahead of the wiring #55 will do, and it is
also exactly the state a reader cannot see from the inside. Every signal a
module gives off -- a persisted effect-key ledger, a policy verdict recorded
before crossing the boundary, an approval keyed to a logical effect -- reads as
a running guarantee.

So the statement is asserted rather than merely written. These read the real
modules' own docstrings; a test asserting on a transcribed copy would prove
nothing about what ships. When #55 wires the layer, these tests fail, and
removing the statement is then the correct fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.capabilities import governed_invocation, harness_manager, invocation, invocation_store

pytestmark = [pytest.mark.contract("behavioral")]

_REPO = Path(__file__).resolve().parents[4]
_MIGRATIONS = _REPO / "alembic" / "versions"


def _states_unreached(doc: str | None) -> bool:
    """Whether `doc` says the thing is unreached and names the issue that changes it.

    Both halves matter. "Unreached" alone invites deletion as dead code; the
    issue number is what marks it as pending wiring rather than abandoned.
    """
    text = (doc or "").lower()
    return ("unreached" in text or "nothing constructs" in text) and "#55" in text


class TestTheInvocationLayerStatesItsReach:
    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_the_module_says_nothing_constructs_an_invocation(self) -> None:
        assert _states_unreached(invocation.__doc__)

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_the_execution_service_says_so_on_itself(self) -> None:
        """On the class, not only the module: an editor showing the hover text
        for `InvocationExecutionService(...)` shows the class docstring."""
        assert _states_unreached(invocation.InvocationExecutionService.__doc__)

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_the_governed_service_says_so_too(self) -> None:
        assert _states_unreached(governed_invocation.GovernedInvocationExecutionService.__doc__)

    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_the_one_caller_of_the_seam_says_so(self) -> None:
        """`send_invocation` is what a reader searching for the seam finds
        first, and it is the least obviously unreached of the four: it is a
        method on a manager the container does construct."""
        assert _states_unreached(harness_manager.HarnessSessionManager.send_invocation.__doc__)


class TestTheStoreStatesItsReachAndItsTable:
    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_store_module_says_nothing_wires_it(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "unreached" in doc or "nothing constructs" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_it_disambiguates_itself_from_the_store_the_container_does_wire(self) -> None:
        """Two classes named `SqliteInvocationStore` are re-exported from
        `maistro.capabilities`. The wired one is the events store."""
        assert "maistro.events.invocations" in (invocation_store.__doc__ or "")

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_it_says_its_table_has_no_migration(self) -> None:
        doc = (invocation_store.__doc__ or "").lower()
        assert "no migration" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-2")
    def test_the_claim_about_the_migration_is_true(self) -> None:
        """A docstring asserting an absence is worth exactly as much as a check
        that the absence holds. If a revision ever creates the table, this fails
        and the paragraph above it is the thing to correct."""
        creating = [
            path.name
            for path in sorted(_MIGRATIONS.glob("*.py"))
            if "capability_invocations" in path.read_text()
        ]
        assert creating == []

    def test_the_migration_scan_has_a_corpus(self) -> None:
        """A guard that reads no files guards nothing."""
        assert len(list(_MIGRATIONS.glob("*.py"))) > 10


class TestTheReachIsWhatTheStatementSays:
    @pytest.mark.ac("SPEC-083026-6cef/AC-1")
    def test_no_production_module_calls_the_seam(self) -> None:
        """The statement is a claim about the repository, so the repository is
        what settles it. Scanning `src` trees only: a test may construct the
        layer freely -- that is what the layer is for today."""
        callers = sorted(
            str(path.relative_to(_REPO))
            for path in _REPO.glob("packages/*/src/**/*.py")
            if _calls_the_seam(path.read_text())
        )
        assert callers == []

    def test_the_caller_scan_finds_a_call_when_there_is_one(self) -> None:
        """A scan that can only return empty proves nothing. This is the shape
        the check will see on the day #55 wires the layer."""
        assert _calls_the_seam("    result = await manager.send_invocation(session_id, msgs)")
        assert not _calls_the_seam("    async def send_invocation(")
        assert not _calls_the_seam("``HarnessSessionManager.send_invocation``, is unreached")


def _calls_the_seam(text: str) -> bool:
    """Whether `text` contains a call to `send_invocation`, not its definition.

    The paren is what separates a call from a prose mention: the modules now
    *say* the seam is unreached, so a bare substring scan would find the very
    statements these tests assert are present.
    """
    return any(
        "send_invocation(" in line and not line.lstrip().startswith(("async def", "def"))
        for line in text.splitlines()
    )
