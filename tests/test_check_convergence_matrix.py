"""Tests for the Architecture Convergence Matrix gate (#28).

The matrix is a planning surface, so the only property that matters is that the
gate *fails* when the document and the code disagree. A gate that passes on a
stale row would launder an out-of-date plan as current architecture — worse than
having no matrix, because the staleness would be invisible.

The audit is exercised on synthetic matrices so the tests stay hermetic; one test
runs the real document to prove the shipped matrix is in the state the gate wants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-convergence-matrix.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_convergence_matrix", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULES = ["pkg.a", "pkg.a.deep", "pkg.b", "other"]
UNREACHABLE = {"pkg.a.deep"}


def matrix(
    *,
    ownership: list[tuple[str, str]] | None = None,
    disposition: list[tuple[str, str, str, str]] | None = None,
) -> str:
    ownership = ownership or [("Pkg", "`pkg`"), ("Other", "`other`")]
    disposition = disposition or [
        ("Pkg", "`1/3`", "KEEP", "ADR-019"),
        ("Other", "`0/1`", "RETIRE", "—"),
    ]
    own = "\n".join(f"| {name} | {mods} | c | l | p | a |" for name, mods in ownership)
    dis = "\n".join(
        f"| {name} | entry | {count} | {verdict} | {adr} | evidence | — |"
        for name, count, verdict, adr in disposition
    )
    return (
        "<!-- matrix:ownership -->\n"
        "| Subsystem | Modules | Canonical concept | Lifecycle owner | "
        "Persistence owner | Authorization owner |\n"
        "|---|---|---|---|---|---|\n"
        f"{own}\n\n"
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | "
        "Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{dis}\n"
    )


def audit(gate, text: str) -> list[str]:
    return gate.audit(text, MODULES, UNREACHABLE, decision_exists=lambda _: True)


def test_a_consistent_matrix_passes(gate) -> None:
    assert audit(gate, matrix()) == []


def test_an_unclassified_module_fails_by_name(gate) -> None:
    """The partition rule is what makes 'covers every subsystem' checkable: a new
    package that no row claims must fail, not be silently excluded."""
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`")],
            disposition=[("Pkg", "`1/3`", "KEEP", "ADR-019")],
        ),
    )
    assert any("other" in failure and "match no matrix row" in failure for failure in failures)


def test_a_stale_reachability_count_fails_with_both_numbers(gate) -> None:
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`0/3`", "KEEP", "ADR-019"),
                ("Other", "`0/1`", "RETIRE", "—"),
            ]
        ),
    )
    assert failures == ["Pkg: Unreachable says 0/3, code says 1/3"]


def test_a_wrong_total_fails_even_when_the_unreachable_count_is_right(gate) -> None:
    """A subsystem that grew modules is drift too — the row no longer describes
    the same thing it did when it was reviewed."""
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`1/2`", "KEEP", "ADR-019"),
                ("Other", "`0/1`", "RETIRE", "—"),
            ]
        ),
    )
    assert failures == ["Pkg: Unreachable says 1/2, code says 1/3"]


def test_a_prefix_matching_nothing_fails(gate) -> None:
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Other", "`other`"), ("Ghost", "`ghost`")],
            disposition=[
                ("Pkg", "`1/3`", "KEEP", "ADR-019"),
                ("Other", "`0/1`", "RETIRE", "—"),
                ("Ghost", "`0/0`", "RETIRE", "—"),
            ],
        ),
    )
    assert any("`ghost` matches no production module" in failure for failure in failures)


def test_rows_present_in_only_one_table_are_named(gate) -> None:
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Other", "`other`")],
            disposition=[("Pkg", "`1/3`", "KEEP", "ADR-019")],
        ),
    )
    assert "rows in the ownership table only: Other" in failures


def test_an_invented_disposition_fails(gate) -> None:
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`1/3`", "PROBABLY-FINE", "ADR-019"),
                ("Other", "`0/1`", "RETIRE", "—"),
            ]
        ),
    )
    assert any("'PROBABLY-FINE' is not one of" in failure for failure in failures)


def test_a_citation_with_no_file_fails(gate) -> None:
    text = matrix(
        disposition=[
            ("Pkg", "`1/3`", "KEEP", "ADR-999"),
            ("Other", "`0/1`", "RETIRE", "—"),
        ]
    )
    failures = gate.audit(text, MODULES, UNREACHABLE, decision_exists=lambda _: False)
    assert any("cites ADR-999" in failure for failure in failures)


def test_longest_prefix_wins_so_a_narrow_row_takes_its_modules(gate) -> None:
    """`pkg.a` must be owned by the row that names it, not by the broader `pkg`
    row — otherwise adding a subsystem row would silently re-parent modules."""
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Deep", "`pkg.a`"), ("Other", "`other`")],
            disposition=[
                ("Pkg", "`0/1`", "KEEP", "ADR-019"),
                ("Deep", "`1/2`", "MIGRATE", "ADR-019"),
                ("Other", "`0/1`", "RETIRE", "—"),
            ],
        ),
    )
    assert failures == []


def test_a_module_claimed_twice_at_equal_specificity_is_rejected(gate) -> None:
    text = matrix(
        ownership=[("Pkg", "`pkg`"), ("Twin", "`pkg`"), ("Other", "`other`")],
        disposition=[
            ("Pkg", "`1/3`", "KEEP", "ADR-019"),
            ("Twin", "`0/0`", "KEEP", "ADR-019"),
            ("Other", "`0/1`", "RETIRE", "—"),
        ],
    )
    failures = audit(gate, text)
    assert any("claimed by both Pkg and Twin" in failure for failure in failures)


def test_the_shipped_matrix_matches_the_shipped_code(gate) -> None:
    assert gate.main() == 0
