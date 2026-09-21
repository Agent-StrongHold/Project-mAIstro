"""Documentation conformance for the quarantine PR gate (#347).

`test_selfbranch.py` proves selfbranch-5's *behavior* (absent check -> no PR,
uncleared verdict -> no PR, cleared verdict -> PR). This module pins the
*specification* to that behavior so the two cannot drift apart again: the
quarantine check is a required gate that must execute against the diff that
ships and clear -- absence is a refusal, not a bypass.

The assertions check security *meaning* -- what the gate conjoins and what it
denies -- rather than keyword presence: reverting the spec's connective to
"absent or cleared" fails the first class even though the word "quarantine"
survives untouched, and reverting the code's conjunction fails the second.
"""

from __future__ import annotations

import re
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
_SPEC = _PKG / "SPEC.md"
_SELFBRANCH = _PKG / "src" / "maistro_rsi" / "selfbranch.py"

#: The fail-open connective this issue exists to remove: any clause that lets a
#: PR through when the check is absent/missing *or* cleared. Bold markers and
#: backticks are normalized away before matching, and the match is bounded to
#: the sentence so a distant "or" cannot satisfy it.
_ABSENT_OR_CLEARED = re.compile(
    r"quarantine[_ ]check is (?:absent|missing|omitted|not supplied|not wired)"
    r"[^.]*\bor\b",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return text.replace("**", "").replace("`", "").lower()


def _selfbranch_5_row() -> str:
    text = _SPEC.read_text(encoding="utf-8")
    match = re.search(r"^\| selfbranch-5 \|(.*?)\|\s*$", text, re.MULTILINE)
    assert match is not None, "SPEC.md must keep its selfbranch-5 acceptance row"
    return _normalized(match.group(1))


class TestTheSpecStatesTheGateIsRequired:
    def test_no_sentence_offers_an_absent_check_escape_hatch(self) -> None:
        """selfbranch-5 (docs): no sentence in SPEC.md may pair an absent or
        missing quarantine check with an 'or' that would let a PR through."""
        text = _normalized(_SPEC.read_text(encoding="utf-8"))
        assert not _ABSENT_OR_CLEARED.search(text)

    def test_selfbranch_5_requires_present_executed_current_cleared(self) -> None:
        """selfbranch-5 (docs): the PR gate conjoins presence, execution against
        the diff that ships, and a cleared verdict -- and states that absence
        refuses rather than bypasses."""
        row = _selfbranch_5_row()
        assert "quarantine_check is present" in row
        assert "executed against the diff that ships" in row
        assert "returning a cleared verdict" in row
        assert "fails closed" in row
        # Absence itself must be enumerated among the refusals, not just an
        # uncleared verdict.
        assert "absent" in row
        assert "must never produce a pr" in row

    def test_selfbranch_5_supersedes_the_fail_open_wording(self) -> None:
        """selfbranch-5 (docs): the historical fail-open text is superseded
        with rationale in the spec, not silently overwritten."""
        row = _selfbranch_5_row()
        assert "supersedes" in row
        assert "fail-open" in row


class TestTheCodeKeepsTheFailClosedConjunction:
    def test_shipping_requires_presence_and_cleared(self) -> None:
        """selfbranch-5 (docs <-> code): the shipping decision is exactly the
        conjunction `quarantine_verdict is not None and quarantine_verdict.cleared`.
        Reverting either operand to a bypass (e.g. `is None or ...`) changes the
        gate's meaning and fails here, keeping spec and code in lockstep."""
        source = _SELFBRANCH.read_text(encoding="utf-8")
        assert "quarantine_verdict is not None and quarantine_verdict.cleared" in source, (
            "the ship gate must conjoin an executed (non-None) verdict with cleared=True"
        )

    def test_no_fail_open_disjunction_survives_in_code(self) -> None:
        """selfbranch-5 (docs <-> code): the old fail-open shape -- `is None or`
        treating a missing verdict as permission -- must not return."""
        source = _SELFBRANCH.read_text(encoding="utf-8")
        assert "quarantine_verdict is None or" not in source
