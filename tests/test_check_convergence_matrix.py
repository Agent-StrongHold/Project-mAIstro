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


#: Owner cells default to a declared absence, so a test that says nothing about
#: ownership exercises only the rule it is about.
ABSENT = ("—", "—", "—")


def _census(ownership: list[tuple[str, ...]]) -> tuple[int, int, int]:
    """Classify owner cells the way the doc's grammar reads, by hand.

    Deliberately not the gate's own classifier: a helper that called the code
    under test would make the census assertion agree with itself no matter what
    the code did.
    """
    claims = declared = prose = 0
    for row in ownership:
        for cell in row[2:5] if len(row) > 2 else ABSENT:
            if "`" in cell and "." in cell.split("`")[1]:
                claims += 1
            elif cell.startswith(("—", "n/a", "none", "itself")):
                declared += 1
            else:
                prose += 1
    return claims, declared, prose


def matrix(
    *,
    ownership: list[tuple[str, ...]] | None = None,
    disposition: list[tuple[str, str, str, str]] | None = None,
    census: tuple[int, int, int] | None = None,
) -> str:
    """A synthetic matrix.

    An ownership entry is `(subsystem, modules)` — owners default to declared
    absences — or `(subsystem, modules, lifecycle, persistence, authorization)`
    when the test is about an owner cell.
    """
    ownership = ownership or [("Pkg", "`pkg`"), ("Other", "`other`")]
    disposition = disposition or [
        ("Pkg", "`some`", "KEEP", "ADR-019"),
        ("Other", "`none`", "RETIRE", "—"),
    ]
    rows = [(row[0], row[1], *(row[2:5] if len(row) > 2 else ABSENT)) for row in ownership]
    own = "\n".join(
        f"| {name} | {mods} | c | {life} | {store} | {auth} |"
        for name, mods, life, store, auth in rows
    )
    dis = "\n".join(
        f"| {name} | entry | {count} | {verdict} | {adr} | evidence | — |"
        for name, count, verdict, adr in disposition
    )
    claims, declared, prose = census or _census(rows)
    return (
        f"<!-- matrix:ownership-census claims={claims} declared={declared} prose={prose} -->\n"
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


def audit(gate, text: str, modules: list[str] | None = None) -> list[str]:
    return gate.audit(text, modules or MODULES, UNREACHABLE, decision_exists=lambda _: True)


def test_a_consistent_matrix_passes(gate) -> None:
    assert audit(gate, matrix()) == []


def test_an_unclassified_module_fails_by_name(gate) -> None:
    """The partition rule is what makes 'covers every subsystem' checkable: a new
    package that no row claims must fail, not be silently excluded."""
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`")],
            disposition=[("Pkg", "`some`", "KEEP", "ADR-019")],
        ),
    )
    assert any("other" in failure and "match no matrix row" in failure for failure in failures)


@pytest.mark.ac("SPEC-082926-061d/AC-6")
def test_a_stale_share_fails_with_both_words_and_the_exact_counts(gate) -> None:
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`none`", "KEEP", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
            ]
        ),
    )
    assert failures == ["Pkg: Unreachable says `none`, code says `some` (1 of 3 modules, 33.3%)"]


@pytest.mark.ac("SPEC-082926-061d/AC-6")
def test_a_word_outside_the_vocabulary_lists_the_five(gate) -> None:
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`quite a lot`", "KEEP", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
            ]
        ),
    )
    assert failures == ["Pkg: Unreachable cell must be one of `none`, `few`, `some`, `most`, `all`"]


def test_a_prefix_matching_nothing_fails(gate) -> None:
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Other", "`other`"), ("Ghost", "`ghost`")],
            disposition=[
                ("Pkg", "`some`", "KEEP", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
                ("Ghost", "`none`", "RETIRE", "—"),
            ],
        ),
    )
    assert any("`ghost` matches no production module" in failure for failure in failures)


def test_rows_present_in_only_one_table_are_named(gate) -> None:
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Other", "`other`")],
            disposition=[("Pkg", "`some`", "KEEP", "ADR-019")],
        ),
    )
    assert "rows in the ownership table only: Other" in failures


def test_an_invented_disposition_fails(gate) -> None:
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`some`", "PROBABLY-FINE", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
            ]
        ),
    )
    assert any("'PROBABLY-FINE' is not one of" in failure for failure in failures)


def test_a_citation_with_no_file_fails(gate) -> None:
    text = matrix(
        disposition=[
            ("Pkg", "`some`", "KEEP", "ADR-999"),
            ("Other", "`none`", "RETIRE", "—"),
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
                ("Pkg", "`none`", "KEEP", "ADR-019"),
                ("Deep", "`some`", "MIGRATE", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
            ],
        ),
    )
    assert failures == []


def test_a_module_claimed_twice_at_equal_specificity_is_rejected(gate) -> None:
    text = matrix(
        ownership=[("Pkg", "`pkg`"), ("Twin", "`pkg`"), ("Other", "`other`")],
        disposition=[
            ("Pkg", "`some`", "KEEP", "ADR-019"),
            ("Twin", "`none`", "KEEP", "ADR-019"),
            ("Other", "`none`", "RETIRE", "—"),
        ],
    )
    failures = audit(gate, text)
    assert any("claimed by both Pkg and Twin" in failure for failure in failures)


# --- ownership claims (#378) -------------------------------------------------
#
# Reachability counts were checked; the sentence beside them was not, so the
# table could name a current owner that no product path reaches — which is the
# one thing an "who owns this today" column must not get wrong. Each column is
# mutated on its own below, because a gate that only ever saw one of them could
# be reading the wrong cell and every test would still pass.


def owned(life: str = "—", store: str = "—", auth: str = "—") -> list[tuple[str, ...]]:
    return [("Pkg", "`pkg`", life, store, auth), ("Other", "`other`")]


#: Pkg as MIGRATE, so a test about one rule does not also trip the KEEP rule.
MIGRATING = [("Pkg", "`some`", "MIGRATE", "ADR-019"), ("Other", "`none`", "RETIRE", "—")]


def test_a_lifecycle_owner_that_nothing_reaches_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(life="`pkg.a.deep`"), disposition=MIGRATING))

    assert failures == [
        "Pkg: Lifecycle owner `pkg.a.deep` as a current owner, but no product path reaches "
        "pkg.a.deep; mark it `(unreachable)` or `(planned)`, or wire it"
    ]


def test_a_persistence_owner_that_nothing_reaches_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(store="`pkg.a.deep`"), disposition=MIGRATING))

    assert [f.split(":")[1].strip().split()[0] for f in failures] == ["Persistence"]


def test_an_authorization_owner_that_nothing_reaches_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(auth="`pkg.a.deep`"), disposition=MIGRATING))

    assert [f.split(":")[1].strip().split()[0] for f in failures] == ["Authorization"]


def test_a_reached_owner_passes(gate) -> None:
    assert audit(gate, matrix(ownership=owned(life="`pkg.a`"))) == []


def test_an_unreachable_annotation_licenses_the_claim(gate) -> None:
    """The matrix may say 'designed, not wired' — it may not say it silently."""
    assert (
        audit(
            gate, matrix(ownership=owned(life="`pkg.a.deep` (unreachable)"), disposition=MIGRATING)
        )
        == []
    )


def test_an_unreachable_annotation_on_a_wired_module_fails(gate) -> None:
    """The other direction. An annotation that outlives the wiring it described
    is the same defect as the claim it was added to correct."""
    failures = audit(gate, matrix(ownership=owned(life="`pkg.a` (unreachable)")))

    assert any("is reached; drop the annotation" in failure for failure in failures)


def test_an_owner_that_is_no_production_module_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(store="`pkg.invented`")))

    assert failures == [
        "Pkg: Persistence owner names `pkg.invented`, which is not a production module"
    ]


def test_an_abbreviation_that_names_two_modules_fails(gate) -> None:
    """Cells abbreviate, so resolution has to be checked, not assumed. A name
    that lands on two modules leaves the reader guessing which one is meant."""
    modules = ["pkg.a.deep", "two.a.deep", "other"]
    text = matrix(
        ownership=[
            ("Pkg", "`pkg`, `two`", "`a.deep` (unreachable)", "—", "—"),
            ("Other", "`other`"),
        ],
        disposition=[("Pkg", "`0/2`", "MIGRATE", "ADR-019"), ("Other", "`none`", "RETIRE", "—")],
    )
    failures = gate.audit(text, modules, {"pkg.a.deep"}, decision_exists=lambda _: True)

    assert any("names 2 production modules" in failure for failure in failures)


def test_an_abbreviated_owner_resolves_against_the_rows_own_prefixes(gate) -> None:
    """`a` under the `pkg` row means `pkg.a`, the way the real table writes
    `runs.pg_store` for `maistro.runs.pg_store`."""
    assert audit(gate, matrix(ownership=owned(store="`a`"))) == []


def test_a_planned_owner_is_not_a_claim_about_today(gate) -> None:
    text = matrix(
        ownership=owned(life="`pkg.a.deep` (planned)"),
        disposition=[("Pkg", "`some`", "CONNECT", "ADR-019"), ("Other", "`none`", "RETIRE", "—")],
    )

    assert audit(gate, text) == []


def test_a_planned_owner_on_a_keep_row_fails(gate) -> None:
    """KEEP asserts the owner is in place. A row still waiting for one is
    CONNECT or MIGRATE, and saying KEEP hides exactly that gap."""
    failures = audit(gate, matrix(ownership=owned(life="`pkg.a.deep` (planned)")))

    assert any("is `(planned)` on a KEEP row" in failure for failure in failures)


def test_a_keep_column_whose_every_owner_is_unreachable_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(auth="`pkg.a.deep` (unreachable)")))

    assert failures == [
        "Pkg: Authorization owner is KEEP but every owner it names is unreachable or planned"
    ]


def test_one_unreachable_owner_beside_a_reached_one_is_not_that_failure(gate) -> None:
    """A column with a wired owner and a designed-but-unwired one still owns
    something today; only a column with nothing behind it is the KEEP lie."""
    text = matrix(ownership=owned(auth="`pkg.a`, `pkg.a.deep` (unreachable)"))

    assert audit(gate, text) == []


def test_two_subsystems_cannot_own_one_lifecycle(gate) -> None:
    text = matrix(
        ownership=[
            ("Pkg", "`pkg`", "`pkg.a`", "—", "—"),
            ("Other", "`other`", "`pkg.a`", "—", "—"),
        ],
    )
    failures = audit(gate, text)

    assert any("is the lifecycle owner of 2 subsystems" in failure for failure in failures)


def test_a_delegated_lifecycle_owner_is_allowed(gate) -> None:
    """maistro-server hands work to the task queue; it does not own the queue's
    work state. Saying so is the difference between a second owner and a reader."""
    text = matrix(
        ownership=[
            ("Pkg", "`pkg`", "`pkg.a`", "—", "—"),
            ("Other", "`other`", "`pkg.a` (delegated)", "—", "—"),
        ],
    )

    assert audit(gate, text) == []


def test_a_cell_that_declares_no_owner_may_not_also_name_one(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(life="none — `pkg.a` decides")))

    assert any("declares no owner but names" in failure for failure in failures)


def test_an_empty_owner_cell_fails(gate) -> None:
    failures = audit(gate, matrix(ownership=owned(life="")))

    assert any("is empty; say `—` if there is no owner" in failure for failure in failures)


def test_prose_owners_are_counted_rather_than_rejected(gate) -> None:
    """'OS file permissions' is an honest answer no import graph can settle.
    Rejecting it would push writers toward a plausible module name instead."""
    assert audit(gate, matrix(ownership=owned(auth="OS file permissions"))) == []


def test_a_stale_ownership_census_fails(gate) -> None:
    """The unverifiable residue is itself a number, so it can go stale like any
    other. Checking it is what keeps the stated limitation true."""
    text = matrix(ownership=owned(auth="OS file permissions"), census=(0, 6, 0))
    failures = audit(gate, text)

    assert any("the ownership census is stale" in failure for failure in failures)


def test_rows_present_only_in_the_disposition_table_are_named(gate) -> None:
    failures = audit(
        gate,
        matrix(
            ownership=[("Pkg", "`pkg`"), ("Other", "`other`")],
            disposition=[
                ("Pkg", "`some`", "KEEP", "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
                ("Ghost", "`none`", "RETIRE", "—"),
            ],
        ),
    )

    assert "rows in the disposition table only: Ghost" in failures


def test_the_same_rows_in_a_different_order_fails(gate) -> None:
    """Order is how a reader pairs the two tables by eye; swapped rows would
    put each subsystem's disposition beside another subsystem's owners."""
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Other", "`none`", "RETIRE", "—"),
                ("Pkg", "`some`", "KEEP", "ADR-019"),
            ]
        ),
    )

    assert "both tables list the same subsystems in a different order" in failures


def test_a_matrix_with_no_census_marker_fails(gate) -> None:
    text = "\n".join(line for line in matrix().splitlines() if "ownership-census" not in line)
    failures = audit(gate, text)

    assert any("ownership census marker is missing" in failure for failure in failures)


def test_an_ownership_table_without_an_owner_column_fails(gate) -> None:
    """The grammar is checked per column, so a table that dropped one would
    otherwise pass by having nothing left to disagree with."""
    text = matrix().replace("| Persistence owner ", "| Storage ")
    failures = audit(gate, text)

    assert any("ownership table is missing column(s): Persistence owner" in f for f in failures)


def test_the_shipped_matrix_matches_the_shipped_code(gate) -> None:
    assert gate.main([]) == 0


# --- the share is derived, so two branches do not collide (#605) --------------
#
# The defect this replaced was not a wrong number; it was a *shared line*. The
# denominator was the subsystem's module count, so any PR that added a module
# anywhere rewrote a cell every other open PR also carried. These tests are the
# pair from the issue, run rather than described.

#: A subsystem the size of a real one: eight modules, three of them unreachable
#: (37.5%, `some`). Two branches each add one reached module — the pair from the
#: issue. The eight is not decoration: the defect is invisible at three modules,
#: because every share word is a boundary away.
_BASE = [f"pkg.m{n}" for n in range(8)] + ["other"]
_UNREACHABLE_BASE = {"pkg.m0", "pkg.m1", "pkg.m2"}
_BRANCH_A = "pkg.added_by_a"
_BRANCH_B = "pkg.added_by_b"

_PAIR_MATRIX = matrix(
    disposition=[
        ("Pkg", "`some`", "KEEP", "ADR-019"),
        ("Other", "`none`", "RETIRE", "—"),
    ]
)


@pytest.mark.ac("SPEC-082926-061d/AC-1")
@pytest.mark.parametrize(
    "added",
    [
        pytest.param((), id="base"),
        pytest.param((_BRANCH_A,), id="branch-a-alone"),
        pytest.param((_BRANCH_B,), id="branch-b-alone"),
        pytest.param((_BRANCH_A, _BRANCH_B), id="both-merged"),
    ],
)
def test_two_branches_adding_a_module_to_one_subsystem_do_not_collide(
    gate, added: tuple[str, ...]
) -> None:
    """Neither branch edits the row, and the row is right in all four worlds.

    3 of 8, 3 of 9, 3 of 10 — 37.5%, 33.3%, 30.0% — and every one is `some`.
    Nothing to write means nothing to conflict on.
    """
    failures = gate.audit(
        _PAIR_MATRIX,
        sorted([*_BASE, *added]),
        _UNREACHABLE_BASE,
        decision_exists=lambda _: True,
    )
    assert failures == []


@pytest.mark.ac("SPEC-082926-061d/AC-1")
def test_the_transcribed_count_would_have_failed_that_same_pair(gate) -> None:
    """The counterfactual, so the fix is measured against the defect it replaced.

    Under the old grammar the cell held `3/8`. Each branch alone makes it `3/9`
    and the merge makes it `3/10`, so both branches had to edit the same line —
    and whichever value the merge kept, it was wrong.
    """

    def old_cell(added: tuple[str, ...]) -> tuple[int, int]:
        modules = [*_BASE, *added]
        owned = [m for m in modules if m.startswith("pkg.")]
        return len(_UNREACHABLE_BASE), len(owned)

    base = old_cell(())
    assert base == (3, 8)
    assert old_cell((_BRANCH_A,)) != base
    assert old_cell((_BRANCH_B,)) != base
    assert old_cell((_BRANCH_A, _BRANCH_B)) != base

    # And the share, over the same four worlds, does not move at all.
    assert {
        gate.share_word(*old_cell(added))
        for added in ((), (_BRANCH_A,), (_BRANCH_B,), (_BRANCH_A, _BRANCH_B))
    } == {"some"}


@pytest.mark.ac("SPEC-082926-061d/AC-4")
def test_the_share_is_computed_from_the_reachability_baseline(gate) -> None:
    """The unreachable set is the gate's only source for what is unreachable.

    Marking `pkg.b` unreachable — nothing else changed — must move `pkg` from
    `some` to `most`, because 2 of 3 is more than half.
    """
    text = matrix(
        disposition=[
            ("Pkg", "`some`", "KEEP", "ADR-019"),
            ("Other", "`none`", "RETIRE", "—"),
        ]
    )
    failures = gate.audit(text, MODULES, {"pkg.a.deep", "pkg.b"}, decision_exists=lambda _: True)
    assert failures == ["Pkg: Unreachable says `some`, code says `most` (2 of 3 modules, 66.7%)"]


@pytest.mark.ac("SPEC-082926-061d/AC-4")
@pytest.mark.parametrize(
    ("unreachable", "total", "word"),
    [
        (0, 10, "none"),
        (1, 10, "few"),
        (2, 10, "few"),
        (3, 10, "some"),
        (5, 10, "some"),
        (6, 10, "most"),
        (9, 10, "most"),
        (10, 10, "all"),
        (1, 1, "all"),
        (0, 0, "none"),
    ],
)
def test_the_vocabulary_boundaries_are_inclusive_at_the_top(
    gate, unreachable: int, total: int, word: str
) -> None:
    assert gate.share_word(unreachable, total) == word


@pytest.mark.ac("SPEC-082926-061d/AC-5")
def test_the_census_names_the_counts_the_matrix_no_longer_carries(gate) -> None:
    owners = {"pkg.a": "Pkg", "pkg.a.deep": "Pkg", "pkg.b": "Pkg", "other": "Other"}
    lines = gate.census(MODULES, UNREACHABLE, owners)

    assert lines[0].split() == ["subsystem", "unreachable", "/", "total", "share", "word"]
    body = {line.split()[0]: line for line in lines[1:]}
    assert body["Pkg"].split()[1:] == ["1", "/", "3", "33.3%", "some"]
    assert body["Other"].split()[1:] == ["0", "/", "1", "0.0%", "none"]


@pytest.mark.ac("SPEC-082926-061d/AC-5")
def test_the_census_puts_the_worst_subsystem_first(gate) -> None:
    owners = {"pkg.a": "Pkg", "pkg.a.deep": "Pkg", "pkg.b": "Pkg", "other": "Other"}
    lines = gate.census(MODULES, UNREACHABLE, owners)
    assert [line.split()[0] for line in lines[1:]] == ["Pkg", "Other"]


@pytest.mark.ac("SPEC-082926-061d/AC-6")
def test_the_failure_message_names_the_census_command(gate) -> None:
    """The gate's own output has to say where the exact numbers went."""
    assert "--census" in gate.CENSUS_COMMAND


@pytest.mark.ac("SPEC-082926-061d/AC-3")
def test_the_disposition_prose_is_read_only_for_its_verdict_and_citations(gate) -> None:
    """#378's hand-written rationale must survive the derived column beside it."""
    prose = "KEEP — the 43 rooted scripts are the gate set, per ADR-019, and stay so"
    failures = audit(
        gate,
        matrix(
            disposition=[
                ("Pkg", "`some`", prose, "ADR-019"),
                ("Other", "`none`", "RETIRE", "—"),
            ]
        ),
    )
    assert failures == []


@pytest.mark.ac("SPEC-082926-061d/AC-5")
def test_the_census_skips_a_module_no_row_owns(gate) -> None:
    """The partition check owns that failure; the census must not divide by it."""
    owners = {"pkg.a": "Pkg", "pkg.a.deep": "Pkg", "pkg.b": "Pkg"}
    lines = gate.census([*MODULES, "orphan"], UNREACHABLE, owners)

    assert [line.split()[0] for line in lines[1:]] == ["Pkg"]


@pytest.mark.ac("SPEC-082926-061d/AC-5")
def test_a_subsystem_owning_nothing_reports_no_share_rather_than_dividing(gate) -> None:
    assert gate._percent(0, 0) == "0.0%"
    assert gate.share_word(0, 0) == "none"


@pytest.mark.ac("SPEC-082926-061d/AC-5")
def test_the_census_command_runs_against_the_shipped_matrix(gate, capsys) -> None:
    assert gate.main(["--census"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["subsystem", "unreachable", "/", "total", "share", "word"]
    assert any(line.split()[-1] in gate.SHARE_WORDS for line in lines[1:])


@pytest.mark.ac("SPEC-082926-061d/AC-6")
def test_an_unknown_flag_is_refused_rather_than_ignored(gate, capsys) -> None:
    """Silently auditing on a typo'd flag would report a pass nobody asked for."""
    assert gate.main(["--sensus"]) == 2
    assert "--census" in capsys.readouterr().err


@pytest.mark.ac("SPEC-082926-061d/AC-6")
def test_a_failing_run_prints_the_census_command_beside_the_failures(
    gate, tmp_path, monkeypatch, capsys
) -> None:
    """The gate's own output, not just the docstring, has to say where to look.

    Pointed at a synthetic matrix: it cannot partition the real repository's
    modules, so `main` takes its failure path against real inputs.
    """
    stand_in = tmp_path / "CONVERGENCE-MATRIX.md"
    stand_in.write_text(matrix())
    monkeypatch.setattr(gate, "MATRIX", stand_in)

    assert gate.main([]) == 1

    out = capsys.readouterr().out
    assert "does not match the code it describes" in out
    assert gate.CENSUS_COMMAND in out


def test_a_missing_matrix_fails_rather_than_passing_vacuously(
    gate, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(gate, "MATRIX", tmp_path / "gone.md")

    assert gate.main([]) == 1
    assert "is missing" in capsys.readouterr().err
