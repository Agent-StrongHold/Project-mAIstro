"""Tests for the BACKLOG.md consistency gate (#30).

BACKLOG.md is the hand-maintained work-source of record until the database
backlog is live (#50), and agents read it as well as people. The properties
worth pinning are that an undefined status fails, a dangling citation fails, and
— the point of the design — that the vocabulary comes from the file's own
legends rather than from this script, so a legend and its usage cannot drift.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-backlog-consistency.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_backlog_consistency", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def backlog(*items: str, statuses: tuple[str, ...] = ("Proposed", "Implemented")) -> str:
    rows = "\n".join(f"| {status} | meaning |" for status in statuses)
    body = "\n".join(items)
    return f"""# Backlog

- `engine-NNN` — shared substrate

## Work status legend

| Marker | Meaning |
|---|---|
{rows}

## Gap legend

| Marker | Meaning |
|---|---|
| `gap-impl` | no code |

## Items

{body}
"""


def test_a_consistent_backlog_passes(gate) -> None:
    assert gate.audit(backlog("**[engine-001] A thing — Proposed — v1.0**")) == []


def test_a_status_outside_the_legend_fails(gate) -> None:
    failures = gate.audit(backlog("**[engine-001] A thing — Invented — v1.0**"))
    assert any("status 'Invented' is not in the status legend" in f for f in failures)


def test_adding_the_status_to_the_legend_is_what_permits_it(gate) -> None:
    """The vocabulary lives in the document, not in the checker. This is the
    property that stops the legend and its usage drifting apart."""
    item = "**[engine-001] A thing — Obsolete — v1.0**"
    assert gate.audit(backlog(item)) != []
    assert gate.audit(backlog(item, statuses=("Proposed", "Implemented", "Obsolete"))) == []


def test_a_gap_marker_outside_the_gap_legend_fails(gate) -> None:
    failures = gate.audit(backlog("**[engine-001] A thing — Proposed; `gap-vibes` — v1.0**"))
    assert any("gap marker 'gap-vibes' is not in the gap legend" in f for f in failures)


def test_a_known_gap_marker_passes(gate) -> None:
    assert gate.audit(backlog("**[engine-001] A thing — Proposed; `gap-impl` — v1.0**")) == []


def test_an_undocumented_id_prefix_fails(gate) -> None:
    failures = gate.audit(backlog("**[wildcat-001] A thing — Proposed — v1.0**"))
    assert any("prefix 'wildcat' is not one of the documented id prefixes" in f for f in failures)


def test_a_duplicate_item_id_fails(gate) -> None:
    failures = gate.audit(
        backlog(
            "**[engine-001] A thing — Proposed — v1.0**",
            "**[engine-001] Another thing — Proposed — v1.0**",
        )
    )
    assert "engine-001: duplicate item id" in failures


def test_a_dangling_decision_citation_fails(gate) -> None:
    failures = gate.audit(backlog("**[engine-001] A thing — Proposed — v1.0**\n- Per `ADR-9991`"))
    assert any("cites ADR-9991" in f for f in failures)


def test_a_real_decision_citation_passes(gate) -> None:
    assert gate.audit(backlog("**[engine-001] A thing — Proposed — v1.0**\n- Per `ADR-019`")) == []


def test_an_unparsable_item_header_fails(gate) -> None:
    failures = gate.audit(backlog("**[engine-001] no status separator here**"))
    assert any("unparsable item header" in f for f in failures)


def test_the_range_id_form_parses(gate) -> None:
    """`[engine-030..034]` batches sibling items under one entry — the real file
    uses this for five property tests, and it must not read as unparsable."""
    assert gate.audit(backlog("**[engine-030..034] Five property tests — Proposed — v1.0**")) == []


# --- item cross-references resolve (#30) ---------------------------------
#
# The `sh-` header's claim is that where an item has a prerequisite this
# repository owns, it names it. A reference to an id that does not exist reads
# as a recorded prerequisite while pointing at nothing — worse than recording
# none, because it asserts the dependency is known and tracked.


def test_a_dangling_item_reference_fails(gate) -> None:
    failures = gate.audit(
        backlog("**[engine-001] A thing — Proposed — v1.0**\n- Blocked-by: `[engine-999]`")
    )

    assert any("[engine-999]" in f and "not an item defined" in f for f in failures)


def test_a_reference_to_a_defined_item_passes(gate) -> None:
    failures = gate.audit(
        backlog(
            "**[engine-001] A thing — Proposed — v1.0**",
            "**[engine-002] Another — Proposed — v1.0**\n- Blocked-by: `[engine-001]`",
        )
    )

    assert failures == []


def test_a_reference_into_a_range_form_passes(gate) -> None:
    """`[engine-030..034]` defines five ids; naming any one of them is legitimate.

    Without expanding the range, every such reference would read as dangling —
    the check would fail the file it is meant to protect.
    """
    failures = gate.audit(
        backlog(
            "**[engine-030..034] Five property tests — Proposed — v1.0**",
            "**[engine-001] A thing — Proposed — v1.0**\n- Substrate: `[engine-032]`",
        )
    )

    assert failures == []


def test_a_reference_outside_a_range_still_fails(gate) -> None:
    """The expansion must be bounded, or it would launder any id near a range."""
    failures = gate.audit(
        backlog(
            "**[engine-030..034] Five property tests — Proposed — v1.0**",
            "**[engine-001] A thing — Proposed — v1.0**\n- Substrate: `[engine-035]`",
        )
    )

    assert any("[engine-035]" in f for f in failures)


def test_the_sh_header_states_a_disposition(gate) -> None:
    """AC-4 of #30: every remaining item has one canonical owner/disposition.

    Stated once for the whole `sh-` family rather than repeated per item, since
    the disposition is identical for all 36 and a per-item marker would be 36
    copies of one fact, drifting independently.
    """
    text = (ROOT / "BACKLOG.md").read_text()
    bullet = text.split("- `sh-NNN`", 1)[1].split("\n\n", 1)[0]

    assert "deferred-downstream" in bullet
    assert "owned by Stronghold" in bullet


def test_the_shipped_backlog_is_consistent(gate) -> None:
    assert gate.main() == 0
