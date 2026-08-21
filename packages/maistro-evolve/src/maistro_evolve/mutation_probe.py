"""Diff-scoped mutation testing: do the candidate's own tests actually *pin* the
behavior its source change introduced, or would an overfit / gamed implementation
pass just as well?

This is the missing half of the anti-gaming battery. The loop already proves a
changed test *depends* on the change (``tdd_gate`` red/green and
``candidate_fitness``' ``test_exercises_change`` gate — revert the source, the
test must fail). Mutation testing proves the converse the reward-hacking
literature warns about: a change that satisfies the observed tests without
implementing the intended semantics robustly. We perturb ONLY the lines the diff
introduced, one mutation at a time, and re-run the candidate's OWN changed tests.
A mutation the tests fail to catch (a "survivor") is a hole an overfit fix could
have been driven through; too many survivors withholds promotion.

Design contract (mirrors the rest of the gate battery):

  - **Scoped to the diff's new source lines**, never the whole file — bounded,
    and it targets exactly what THIS candidate wrote.
  - **Deterministic** operator set and traversal order, a **capped** mutant
    count, and a **per-run timeout** so a probe is cheap enough to gate every
    promotion and reproducible across runs (no randomness).
  - **Missing prerequisites yield an UNAVAILABLE probe, never a false
    rejection** — no changed tests, or no mutable new source lines (a docstring
    or pure-formatting diff), means there is nothing to pin, so no gate fires.

Each mutation is applied to a fresh parse of the source, unparsed, written, the
selected tests are run, and the original source is always restored in a
``finally`` — the worktree is left exactly as it was found.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from maistro_evolve.tdd_gate import run_test_selection

# Semantics-changing swaps. Comparisons map to their negation-style counterpart
# (Lt<->GtE, Gt<->LtE, Eq<->NotEq, Is<->IsNot) so every swap is guaranteed to
# change the truth value, not merely tweak a boundary — a boundary-only swap
# (Lt->LtE) is frequently equivalent on the test's actual inputs and would
# inflate the survivor count with false "weak test" signals.
_COMPARE_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}

_BINOP_SWAP: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Add,
}


@dataclass
class _Site:
    """One mutable AST location on a diff-introduced line: a human-readable label
    and a closure that mutates the bound node in place."""

    lineno: int
    label: str
    apply: Callable[[], None]


def _compare_site(node: ast.AST, lineno: int) -> _Site | None:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
        return None
    op = type(node.ops[0])
    swapped = _COMPARE_SWAP.get(op)
    if swapped is None:
        return None

    def _mut() -> None:
        node.ops[0] = swapped()

    return _Site(lineno, f"compare {op.__name__}->{swapped.__name__}", _mut)


def _boolop_site(node: ast.AST, lineno: int) -> _Site | None:
    if not isinstance(node, ast.BoolOp):
        return None
    is_and = isinstance(node.op, ast.And)

    def _mut() -> None:
        node.op = ast.Or() if is_and else ast.And()

    return _Site(lineno, f"boolop {'and->or' if is_and else 'or->and'}", _mut)


def _binop_site(node: ast.AST, lineno: int) -> _Site | None:
    if not isinstance(node, ast.BinOp):
        return None
    op = type(node.op)
    swapped = _BINOP_SWAP.get(op)
    if swapped is None:
        return None

    def _mut() -> None:
        node.op = swapped()

    return _Site(lineno, f"binop {op.__name__}->{swapped.__name__}", _mut)


def _const_site(node: ast.AST, lineno: int) -> _Site | None:
    if not isinstance(node, ast.Constant):
        return None
    if isinstance(node.value, bool):
        flipped = not node.value

        def _mut_bool() -> None:
            node.value = flipped

        return _Site(lineno, f"const {node.value}->{flipped}", _mut_bool)
    # bool is a subclass of int — the check above already claimed it.
    if isinstance(node.value, int | float):
        bumped = node.value + 1

        def _mut_num() -> None:
            node.value = bumped

        return _Site(lineno, f"const {node.value}->{bumped}", _mut_num)
    return None


# Dispatch order is stable, so a node's canonical mutation is deterministic.
_SITE_BUILDERS = (_compare_site, _boolop_site, _binop_site, _const_site)


def _site_for(node: ast.AST, lineno: int) -> _Site | None:
    """Return the single canonical mutation for ``node``, or None if it is not a
    mutable site. One node yields at most one mutation so the site count is a
    stable, well-defined budget."""
    for builder in _SITE_BUILDERS:
        site = builder(node, lineno)
        if site is not None:
            return site
    return None


def _sites(tree: ast.AST, target_lines: set[int]) -> list[_Site]:
    """Every mutable site whose line is one the diff introduced, in a
    deterministic ``ast.walk`` order (stable for identical source)."""
    found: list[_Site] = []
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is None or lineno not in target_lines:
            continue
        site = _site_for(node, lineno)
        if site is not None:
            found.append(site)
    return found


def _mutants(source: str, target_lines: set[int]) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, mutated_source)`` for each single-site mutation of
    ``source`` restricted to ``target_lines``, in deterministic order.

    Each mutant is applied to a fresh parse so sites never interfere; a mutant
    that unparses to the original (or fails to unparse) is skipped by the caller.
    """
    try:
        base_tree = ast.parse(source)
    except SyntaxError:
        return
    count = len(_sites(base_tree, target_lines))
    for which in range(count):
        tree = ast.parse(source)
        site = _sites(tree, target_lines)[which]
        site.apply()
        ast.fix_missing_locations(tree)
        try:
            yield site.lineno, ast.unparse(tree)
        except Exception:  # unparse can choke on exotic trees — skip, don't crash
            continue


@dataclass
class MutationProbe:
    """Result of a diff-scoped mutation probe.

    ``available`` is False when there was nothing to measure (no changed tests,
    or no mutable new source lines) — a genuinely unmeasurable candidate, which
    the gate treats as *unavailable* (skipped), never as a failure.
    """

    available: bool
    total: int = 0
    killed: int = 0
    survived: int = 0
    survivors: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Fraction of introduced-behavior mutations the candidate's tests catch."""
        return round(self.killed / self.total, 4) if self.total else 0.0

    def summary(self) -> str:
        if not self.available:
            return "mutation probe unavailable (no changed tests or no mutable new lines)"
        detail = f"{self.killed}/{self.total} mutants killed (score={self.score})"
        if self.survivors:
            detail += "; survived: " + ", ".join(self.survivors[:5])
        return detail


def _build_plan(
    root: Path, new_source_lines: dict[str, set[int]], max_mutants: int
) -> list[tuple[str, int, str]]:
    """A deterministic, capped list of ``(file, lineno, mutant_source)`` — the
    prefix of diff-scoped mutations to actually run. Files are visited in sorted
    order; a no-op mutation (unparses to the original) is dropped."""
    plan: list[tuple[str, int, str]] = []
    for rel, lines in sorted(new_source_lines.items()):
        if len(plan) >= max_mutants:
            break
        try:
            source = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, mutant in _mutants(source, lines):
            if mutant == source:
                continue  # a no-op mutation pins nothing — not a real site
            plan.append((rel, lineno, mutant))
            if len(plan) >= max_mutants:
                break
    return plan


def probe_diff_mutations(
    cwd: str | Path,
    new_source_lines: dict[str, set[int]],
    test_selectors: list[str],
    *,
    timeout: int = 120,
    max_mutants: int = 6,
) -> MutationProbe:
    """Mutate the diff's new source lines one at a time and check the candidate's
    changed tests catch each mutation.

    ``new_source_lines`` maps a changed source file to the set of line numbers
    the diff ADDED (see ``coverage_gate.new_source_lines``). ``test_selectors``
    are the candidate's changed test files (see ``tdd_gate.changed_test_paths``).

    A mutant is *killed* when the tests fail with it in place, *survived* when
    they still pass. The original source is always restored. At most
    ``max_mutants`` mutations run (a deterministic prefix across files) so the
    probe stays cheap; if that budget truncates the site list, the omitted sites
    simply do not count toward the score.
    """
    root = Path(cwd)
    if not test_selectors:
        return MutationProbe(available=False)

    plan = _build_plan(root, new_source_lines, max_mutants)
    if not plan:
        return MutationProbe(available=False)

    killed = 0
    survived = 0
    survivors: list[str] = []
    for rel, lineno, mutant in plan:
        path = root / rel
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(mutant, encoding="utf-8")
            rc, _ = run_test_selection(root, test_selectors, timeout=timeout)
        finally:
            path.write_text(original, encoding="utf-8")
        if rc == 0:
            survived += 1
            survivors.append(f"{rel}:{lineno}")
        else:
            killed += 1

    return MutationProbe(
        available=True,
        total=killed + survived,
        killed=killed,
        survived=survived,
        survivors=survivors,
    )
