"""An `ac-modules` anchor must name a module the reachability graph knows (#631).

The top rung, `reachable`, asks whether anything actually runs the code a
criterion is about. It answered that by checking membership in the *unreachable*
set — so a name absent from that set read as reachable, and a name the graph has
never heard of is absent from it. A typo, a bare module name, a script filename
and an invented string all cleared the rung that exists to catch exactly this.

`design_coverage` is built from those rungs and is a **floor** the ratchet
enforces, so an anchor that resolves to nothing does not merely mislabel one
criterion: it raises the number the merge button trusts.

The two failures are kept apart deliberately. "This anchor names nothing" is a
corpus error and fails the gate; "this module is real but nothing imports it"
is the finding the rung was built for and still reports `passing`. Collapsing
them would hide the second inside the first.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "scripts" / "check_ac_state_impl.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("ac_state_anchor_resolution", IMPL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _spec(module: str | None, *, ac: str = "AC-1") -> dict[str, object]:
    """The shape `collect_specs` produces, narrowed to what the check reads."""
    return {
        "file": "docs/specs/SPEC-000-thing.md",
        "criteria": [{"id": f"SPEC-000/{ac}", "module": module}],
    }


class TestTheUniverseIsTheGraphsOwn:
    @pytest.mark.ac("SPEC-082926-c2d7/AC-1")
    def test_the_universe_is_not_empty(self, check) -> None:
        """A silently empty universe would make the gate vacuous, not strict."""
        assert len(check.load_module_universe()) > 500

    @pytest.mark.ac("SPEC-082926-c2d7/AC-1")
    def test_it_holds_the_three_identity_shapes(self, check) -> None:
        """Packages, flat apps and tooling are all anchorable, and spelled differently.

        A gate that only understood dotted package names would reject the
        Conductor and the gate scripts, which is how an author is pushed back
        toward the bare name that started this.
        """
        universe = check.load_module_universe()

        assert "maistro.runs.store" in universe
        assert "@flat/hive-conductor/routes.settings" in universe
        assert "@tool/ac_state_notes" in universe


class TestAnchorsMustResolve:
    @pytest.mark.ac("SPEC-082926-c2d7/AC-2")
    @pytest.mark.parametrize(
        "module",
        [
            "ac_state_notes",  # a real module, named without its scope
            "check-convergence-matrix",  # a script filename, not an identity
            "not_a_real_module_at_all",  # a typo or a rename left behind
            "",  # the empty string, which also used to pass
        ],
    )
    def test_an_anchor_naming_nothing_is_reported(self, check, module: str) -> None:
        universe = check.load_module_universe()

        found = check.unresolvable_anchors([_spec(module)], universe)

        assert [m for _, _, m in found] == [module]

    @pytest.mark.ac("SPEC-082926-c2d7/AC-2")
    def test_a_resolvable_anchor_is_not_reported(self, check) -> None:
        universe = check.load_module_universe()

        assert check.unresolvable_anchors([_spec("maistro.runs.store")], universe) == []

    @pytest.mark.ac("SPEC-082926-c2d7/AC-2")
    def test_a_criterion_with_no_anchor_is_not_reported(self, check) -> None:
        """Unannotated is a known state the rung already handles as `passing`."""
        universe = check.load_module_universe()

        assert check.unresolvable_anchors([_spec(None)], universe) == []

    @pytest.mark.ac("SPEC-082926-c2d7/AC-2")
    def test_an_unloadable_universe_reports_nothing(self, check) -> None:
        """A gate that fails for its own reason, not the corpus's, is worse than silent."""
        assert check.unresolvable_anchors([_spec("anything_at_all")], set()) == []


class TestTheTwoFailuresStayApart:
    """Wrong anchor and unwired module are different findings."""

    def test_an_unresolvable_anchor_still_reads_as_reachable_to_the_rung(self, check) -> None:
        """The defect itself, pinned: the rung cannot tell, which is why the gate must.

        `_is_reachable` tests membership in the unreachable set, so a name that
        is in no set at all comes back True. This is not a bug to fix in the
        rung -- it has no way to distinguish "absent because reachable" from
        "absent because meaningless" -- it is the reason the anchors are
        checked before anything is counted.
        """
        assert check._is_reachable("not_a_real_module_at_all", {"maistro.dead"}) is True

    @pytest.mark.ac("SPEC-082926-c2d7/AC-3")
    def test_a_real_but_unwired_module_is_resolvable_and_not_reachable(self, check) -> None:
        """The finding the rung was built for survives the new gate untouched."""
        universe = check.load_module_universe()
        unreachable = check.load_unreachable()
        unwired = next(iter(unreachable))

        assert unwired in universe
        assert check.unresolvable_anchors([_spec(unwired)], universe) == []
        assert check._is_reachable(unwired, unreachable) is False
