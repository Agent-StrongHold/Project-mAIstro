"""Matched same-model comparisons: the model x harness lift matrix (SPEC-281 §1).

Epic #104 (M4-G) requires "matched same-model comparisons" as published
evidence. A benchmark score alone cannot express the product claim — "a weak
model inside this harness performs close to a frontier model inside a plain
one" is a statement about a *difference between configurations*, so the unit
of measurement has to change: a cell in a model x harness matrix, and derived
quantities computed from four matched cells.

::

                    | baseline harness | evolved harness |
    ----------------|------------------|-----------------|
    weak model      | ``W_base``       | ``W_evo``       |
    frontier model  | ``F_base``       | ``F_evo``       |

    lift        = W_evo - W_base          # what the harness added
    gap         = F_base - W_base         # what there was to close
    gap_closure = lift / gap  if gap > 0  # the headline claim
    transfer    = F_evo - F_base          # does it help the strong model too?
    inversion   = transfer < 0            # does it HURT the strong model?

"Matched" is enforced, not assumed
----------------------------------
Three structural rules make the four cells comparable, and violations raise
rather than produce a plausible-looking number:

* **Same model within a row.** The weak cells must name the same model id and
  the frontier cells must name the same model id — otherwise `lift`/`transfer`
  measure a model change wearing a harness costume.
* **Different models across rows.** The weak and frontier model ids must
  differ. `W_base == F_base` for one model is a degenerate matrix whose `gap`
  is noise; SPEC-281 §1a rule 3 ("the only difference between those two cells
  is the model id") presupposes two models.
* **Same harness within a column, and one pinned baseline for the whole
  report.** Both baseline cells must name the same harness id and the same
  `baseline_version`; the evolved cells must name the same harness id. The
  baseline is a frozen, checksum-pinned artifact (SPEC-281 §1a) — the loop may
  not edit its own denominator — and every cell in a report is denominated in
  exactly one version of it.

`gap <= 0` invalidates, it does not zero
----------------------------------------
If the weak model already matches or beats the frontier model on a benchmark,
that benchmark has nothing to say about harness lift. `gap_closure` is then
``None`` — never ``0.0`` (which reads as "the harness did nothing") and never
``1.0`` (which reads as "fully closed"). Callers must carry the ``None`` all
the way to published evidence; :mod:`maistro_evolve.evidence_manifest`
refuses to publish a numeric `gap_closure` produced from a non-positive gap.

Version discipline (AC-10)
--------------------------
Comparisons never cross baseline versions. :func:`combine_gap_closures` raises
:class:`BaselineVersionMismatchError` rather than averaging numbers computed
against different denominators — changing the baseline reprices every
historical claim, so a silent mix is not a caveat, it is an error.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ModelRole = Literal["weak", "frontier"]

#: Which column of the matrix a cell sits in. Deliberately *not* called
#: ``HarnessKind``: ``maistro.graph.harness.HarnessKind`` is a different
#: concept in another package, and two unrelated types sharing a name in one
#: monorepo is a collision that costs reading time (and confuses
#: name-based tooling).
HarnessColumn = Literal["baseline", "evolved"]

#: Noise tolerance for calling a transfer an inversion (SPEC-281 §2). A genome
#: whose transfer sits below ``-TRANSFER_EPSILON`` is disqualified from
#: breeding regardless of lift — see :func:`transfer_gate_failure` and
#: ``fitness._check_transfer_inversion``.
TRANSFER_EPSILON = 0.02


class LiftMatrixError(ValueError):
    """The four cells do not form a matched model x harness matrix."""


class UnmatchedCellsError(LiftMatrixError):
    """A structural matching rule failed (model/harness axes inconsistent)."""


class BaselineVersionMismatchError(LiftMatrixError):
    """Measurements from different baseline versions were combined (AC-10)."""


class MatrixCell(BaseModel):
    """One measured cell: (model, harness) → score, on one benchmark.

    ``baseline_version`` is mandatory on every cell — including evolved-harness
    cells — because a score is only interpretable against the baseline it was
    compared to. Reporting a ``gap_closure`` without its ``baseline_version``
    is "not a partial result — it is an uninterpretable one" (SPEC-281 §1a).
    """

    benchmark: str
    model_role: ModelRole
    model_id: str
    harness_kind: HarnessColumn
    harness_id: str
    score: float = Field(ge=0.0, le=1.0)
    baseline_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiftReport(BaseModel):
    """The four matched cells plus every derived quantity, none inferred."""

    benchmark: str
    baseline_version: str
    w_base: float
    w_evo: float
    f_base: float
    f_evo: float
    lift: float
    gap: float
    gap_closure: float | None
    transfer: float
    inversion: bool
    # SPEC-281 §2: transfer is sampled, not run every cycle. A carried-forward
    # measurement is still evidence, but it must not be published as fresh.
    transfer_stale: bool = False


def _cell_key(cell: MatrixCell) -> tuple[str, str]:
    return (cell.model_role, cell.harness_kind)


#: How a table position names its model role and its harness kind.
_POSITION_ROLE = {"w": "weak", "f": "frontier"}
_POSITION_KIND = {"base": "baseline", "evo": "evolved"}
_POSITIONS = ("w_base", "w_evo", "f_base", "f_evo")


def _by_position(cells: list[MatrixCell] | dict[str, MatrixCell]) -> dict[str, MatrixCell]:
    """Address the four cells by their table position.

    Accepts either a 4-item list or a mapping keyed by ``"<role>_<kind>"`` —
    the table cell names (``w_base``, ``w_evo``, ``f_base``, ``f_evo``) — so
    callers can address cells individually (AC-1) without positional puzzles.
    """
    if isinstance(cells, dict):
        missing = [pos for pos in _POSITIONS if pos not in cells]
        if missing:
            raise UnmatchedCellsError(
                f"missing cell for position {missing[0]!r} — a lift matrix "
                "needs exactly 4 cells (w_base, w_evo, f_base, f_evo)"
            )
        return {pos: cells[pos] for pos in _POSITIONS}
    keyed: dict[tuple[str, str], MatrixCell] = {}
    for cell in cells:
        key = _cell_key(cell)
        if key in keyed:
            raise UnmatchedCellsError(f"duplicate cell for {key}")
        keyed[key] = cell
    by_position: dict[str, MatrixCell] = {}
    for pos in _POSITIONS:
        role = _POSITION_ROLE[pos[0]]
        kind = _POSITION_KIND[pos.split("_")[1]]
        cell = keyed.get((role, kind))
        if cell is None:
            raise UnmatchedCellsError(
                f"missing cell for position {pos!r} — a lift matrix needs "
                "exactly 4 cells (w_base, w_evo, f_base, f_evo)"
            )
        by_position[pos] = cell
    return by_position


def _check_one_denominator(by_position: dict[str, MatrixCell]) -> None:
    """One benchmark per report; one baseline version denominating every cell."""
    benchmarks = {c.benchmark for c in by_position.values()}
    if len(benchmarks) != 1:
        raise UnmatchedCellsError(
            f"cells span {len(benchmarks)} benchmarks ({sorted(benchmarks)}); "
            "a lift report is per-benchmark"
        )
    versions = {c.baseline_version for c in by_position.values()}
    if len(versions) != 1:
        raise BaselineVersionMismatchError(
            f"cells carry {len(versions)} baseline versions ({sorted(versions)}); "
            "a lift report must be denominated in exactly one pinned baseline "
            "(SPEC-281 §1a rule 2)"
        )


def _check_model_axis(
    w_base: MatrixCell, w_evo: MatrixCell, f_base: MatrixCell, f_evo: MatrixCell
) -> None:
    """Same model within a row, and two different models across the rows."""
    if w_base.model_id != w_evo.model_id:
        raise UnmatchedCellsError(
            f"weak row spans two models ({w_base.model_id!r} vs {w_evo.model_id!r}); "
            "lift would measure a model change, not a harness change"
        )
    if f_base.model_id != f_evo.model_id:
        raise UnmatchedCellsError(
            f"frontier row spans two models ({f_base.model_id!r} vs "
            f"{f_evo.model_id!r}); transfer would measure a model change"
        )
    if w_base.model_id == f_base.model_id:
        raise UnmatchedCellsError(
            f"weak and frontier cells name the same model {w_base.model_id!r}; "
            "the matrix compares two models, and a degenerate one-model matrix "
            "cannot measure harness lift"
        )


def _check_harness_axis(
    w_base: MatrixCell, w_evo: MatrixCell, f_base: MatrixCell, f_evo: MatrixCell
) -> None:
    """A cell must sit in the column it claims, and each column is one harness."""
    for cell in (w_base, f_base):
        if cell.harness_kind != "baseline":
            raise UnmatchedCellsError(
                f"cell {cell.model_role}/base has harness_kind {cell.harness_kind!r}"
            )
    for cell in (w_evo, f_evo):
        if cell.harness_kind != "evolved":
            raise UnmatchedCellsError(
                f"cell {cell.model_role}/evo has harness_kind {cell.harness_kind!r}"
            )
    if w_base.harness_id != f_base.harness_id:
        raise UnmatchedCellsError(
            f"baseline cells name two harnesses ({w_base.harness_id!r} vs "
            f"{f_base.harness_id!r}); W_base and F_base must use the identical "
            "baseline genome (SPEC-281 §1a rule 3)"
        )
    if w_evo.harness_id != f_evo.harness_id:
        raise UnmatchedCellsError(
            f"evolved cells name two harnesses ({w_evo.harness_id!r} vs "
            f"{f_evo.harness_id!r}); W_evo and F_evo must be the same genome"
        )


def build_lift_report(cells: list[MatrixCell] | dict[str, MatrixCell]) -> LiftReport:
    """Validate the four cells as a matched matrix and derive the report."""
    by_position = _by_position(cells)
    _check_one_denominator(by_position)
    w_base, w_evo, f_base, f_evo = (by_position[pos] for pos in _POSITIONS)
    _check_model_axis(w_base, w_evo, f_base, f_evo)
    _check_harness_axis(w_base, w_evo, f_base, f_evo)

    lift = w_evo.score - w_base.score
    gap = f_base.score - w_base.score
    gap_closure = (lift / gap) if gap > 0 else None
    transfer = f_evo.score - f_base.score
    return LiftReport(
        benchmark=next(iter({c.benchmark for c in by_position.values()})),
        baseline_version=next(iter({c.baseline_version for c in by_position.values()})),
        w_base=w_base.score,
        w_evo=w_evo.score,
        f_base=f_base.score,
        f_evo=f_evo.score,
        lift=lift,
        gap=gap,
        gap_closure=gap_closure,
        transfer=transfer,
        inversion=transfer < -TRANSFER_EPSILON,
        transfer_stale=bool(f_evo.metadata.get("transfer_stale", False)),
    )


def combine_gap_closures(reports: list[LiftReport]) -> list[float | None]:
    """Collect the headline numbers, refusing to mix baseline versions (AC-10).

    Averaging or otherwise aggregating ``gap_closure`` values computed under
    different pinned baselines is an error, not a caveat: changing the baseline
    reprices every historical claim, so a mix silently compares numbers with
    different denominators.
    """
    if not reports:
        return []
    versions = {r.baseline_version for r in reports}
    if len(versions) > 1:
        raise BaselineVersionMismatchError(
            f"cannot combine gap_closure values across baseline versions "
            f"({sorted(versions)}); re-measure under one pinned baseline"
        )
    return [r.gap_closure for r in reports]


def transfer_gate_failure(report: LiftReport, *, epsilon: float = TRANSFER_EPSILON) -> str | None:
    """The `gate_failures` entry for an inverting genome, or None (AC-3).

    Inversion is a hard gate, not a penalty: a harness that damages the
    frontier model is disqualified from breeding no matter how large its lift
    is. The caller (``fitness._check_transfer_inversion``) appends this entry
    verbatim, so the reason surfaces in ``FitnessComponents.gate_failures``
    alongside every other disqualification.
    """
    if report.transfer < -epsilon:
        return (
            f"{report.benchmark} transfer {report.transfer:.3f} < -{epsilon:.2f}: "
            "harness inverts on the frontier model (F_evo < F_base) — disqualified"
        )
    return None


__all__ = [
    "TRANSFER_EPSILON",
    "BaselineVersionMismatchError",
    "LiftMatrixError",
    "LiftReport",
    "MatrixCell",
    "UnmatchedCellsError",
    "build_lift_report",
    "combine_gap_closures",
    "transfer_gate_failure",
]
