"""M7-A7 contract: Evolve/RSI consume the in-Run Rubric eval as evidence — never a second loop.

Issue #796 freezes one map and forbids the shapes that would bypass it:

    M7 in-Run Rubric eval (``maistro.personas.rubric``, scored on Run)  →  evidence object on Run
            ↓
    M4 #21 independent evaluation (``maistro_evolve``; hive evolution services)  →  may read
    those records as historical/held-out evidence
            ↓
    M5 #552 RSI (``maistro_rsi``)  →  not production-reachable until containment; if/when
    enabled, same evidence, same promotion contract

Forbidden, each with a tripwire below:

- the Design Studio loop importing RSI or Evolve as the in-Run critic (the critic is the
  Rubric eval scored in-Run, never a second loop);
- Evolve/RSI fitness reaching into the design Goal/Rubric domain to invent a
  design-quality score for the same Goal;
- a design-quality score for a Goal stored outside Run eval records + M4 candidate
  evaluation;
- a ``maistro_design`` private promotion path.

Ownership is explicitly *not* changed here: #21 keeps promotion, #552 keeps RSI. RSI's
activation invariant is owned by ``packages/maistro-rsi/tests/test_non_production_reachability.py``
— the M5 pin below ties this map to that suite instead of duplicating its scan. Product
identity, execution-lifecycle names and provider egress stay with the #990 suite
(``test_no_second_design_product.py``); this file owns only the *scoring* boundary.

The scans are static (AST imports/definitions) and deliberately shallow — tripwires
against the second-loop shapes reappearing, not style lint. The negative-control test
builds each forbidden shape in ``tmp_path`` so a green run proves a real scan, not a
vacuous one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACKAGES = _REPO_ROOT / "packages"
_DESIGN_SRC = _PACKAGES / "maistro-design" / "src"
_EVOLVE_SRC = _PACKAGES / "maistro-evolve" / "src"
_RSI_SRC = _PACKAGES / "maistro-rsi" / "src"
_HIVE_BACKEND = _PACKAGES / "hive-conductor" / "backend"
_RUBRIC_MODULE = _PACKAGES / "maistro-core" / "src" / "maistro" / "personas" / "rubric.py"
_RSI_REACHABILITY_TEST = _PACKAGES / "maistro-rsi" / "tests" / "test_non_production_reachability.py"

#: The one scoring engine the map names as the design-loop critic.
_RUBRIC_EVAL_CLASS = "RubricEval"

#: Import roots the Design Studio loop must never reach: RSI and Evolve are
#: consumers of in-Run eval records (#21/#552), never the loop's critic.
_LOOP_FORBIDDEN_IMPORT_ROOTS = ("maistro_rsi", "maistro_evolve")

#: Import roots Evolve/RSI must never reach back into: the design domain and the
#: Rubric vocabulary. A fitness function that scores design-Goal Rubric dimensions
#: is the "private metric" #796 forbids; reading *records* needs neither import.
_CONSUMER_FORBIDDEN_IMPORT_ROOTS = ("maistro_design", "maistro.personas")

#: Module basenames ``maistro_design`` may not add — a scoring/promotion surface
#: by any of these names is a second loop or a private promotion path.
_DESIGN_FORBIDDEN_MODULE_RE = re.compile(
    r"^(score|scoring|eval|evals|evaluation|evaluator|promote|promotion|fitness|"
    r"critic|judge|judgement|judgment)$",
    re.IGNORECASE,
)

#: Definition names ``maistro_design`` may not declare — a scorer/critic/judge/
#: promoter class or function is the loop standing up its own evaluation.
_DESIGN_FORBIDDEN_DEF_RE = re.compile(
    r"critic|judg\w*|scorer|evaluator|evaluat\w*|promot\w*|fitness", re.IGNORECASE
)

#: Definitions the def-name scan banks by exact ``(relative_path, name)``
#: identity, each reviewed against #796's forbidden list. The ``f72d4fc92``
#: merge brought #779's project-quality consistency evaluator into
#: ``maistro_design`` — #796 lists #779 as Related, and the evaluator is
#: deterministic, read-only ("no store access, no mutation, no model calls")
#: and explicitly "not a self-improvement authority", so it is neither a
#: second scoring loop nor the private promotion path. ``_evaluate_upgrade``
#: is a pack-upgrade *preflight*: it blocks on regressions and unauthorized
#: backends and promotes nothing. ``_evaluation_provenance`` was extracted from
#: the banked ``evaluate_project_snapshot`` by the #1663 complexity refactor
#: (#2204, ``d8675ac89``, merged here in ``638aeb4b8``): it cites the exact
#: brief/decision/artifact revisions the read-only evaluation saw — the same
#: provenance record the banked ``EvaluationProvenance`` class models, built by
#: pure construction from the frozen snapshot, with no I/O, no score and no
#: promotion — and was re-reviewed and re-banked in the PR that merged it.
#: The ``#987`` governed model-judge is a second reviewed exception. Its
#: ``model_judge`` dimensions are the canonical in-Run Rubric eval's
#: ``model_judge`` method (#791/#792), which #796's map names as the one
#: sanctioned scoring loop — not a second loop, and not promotion (#21 keeps
#: promotion). Every ``model_judge`` pair crosses the one governed model
#: boundary (``ModelChatEgress``), so each call persists a canonical
#: Invocation correlated to the Run/NodeRun/Attempt, and the eval record it
#: writes names that Invocation; the node persists through the canonical
#: ``RunStore`` and reads completeness back via ``maistro.runs.eval``.
#: ``deterministic`` dimensions score in-process like persona ``RubricEval``,
#: and ``human`` dimensions are refused loudly (they wait on #794). The
#: module is named ``model_judge`` — the canonical #791/#792 term — rather
#: than the bare ``judge`` the module-name scan forbids; the def names below
#: are banked by exact ``(path, name)`` identity. As with #779, banking is
#: not authorizing: a banked name at another path, or any new judge-like
#: name, still trips.
#:
#: Banking is path-pinned on purpose: the same
#: name in any other module still trips, and any *new* scorer/evaluator/critic
#: name anywhere in the package trips. A bank row whose file or definition
#: disappears is stale and fails the scan (banking is not authorizing — the
#: row must be re-reviewed in the PR that moved the code).
_DESIGN_SURFACE_BANK: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "packages/maistro-design/src/maistro_design/consistency.py",
            "EvaluationProvenance",
        ),
        (
            "packages/maistro-design/src/maistro_design/consistency.py",
            "ConsistencyEvaluation",
        ),
        (
            "packages/maistro-design/src/maistro_design/consistency.py",
            "_judge_allowed_claim",
        ),
        (
            "packages/maistro-design/src/maistro_design/consistency.py",
            "evaluate_project_snapshot",
        ),
        (
            "packages/maistro-design/src/maistro_design/consistency.py",
            "_evaluation_provenance",
        ),
        ("packages/maistro-design/src/maistro_design/packs/service.py", "_evaluate_upgrade"),
        # #987 governed model-judge: the canonical model_judge Rubric method
        # (#791/#792) on the governed Invocation path, not a second loop.
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "HumanJudgeNotResolvedError",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "DesignJudgeThesis",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "DesignJudgeDimension",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "DesignJudgeIn",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "DesignJudgeOut",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "DesignJudgeNode",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "_judge_prompt",
        ),
        (
            "packages/maistro-design/src/maistro_design/model_judge.py",
            "_model_judge_record",
        ),
    }
)

#: Identifier names for design-quality scores. A Goal's quality evidence lives in
#: Run eval records and M4 candidate evaluation — nowhere else (#796).
_SCORE_FIELD_RE = re.compile(
    r"^(design_(quality|fitness|loop)_score|(quality|fitness|evolve|rubric)_score)$",
    re.IGNORECASE,
)

_DYNAMIC_IMPORT_FUNCS = {"import_module", "__import__", "find_spec"}

_SKIP_DIR_PARTS = frozenset({"__pycache__", ".venv", "node_modules", "dist", "build", "mutants"})


# ---------------------------------------------------------------------------
# Helpers (parameterized by root/file list so the negative controls reuse them)
# ---------------------------------------------------------------------------


def _iter_py(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if not _SKIP_DIR_PARTS.intersection(p.parts))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(_read(path), filename=str(path))
    except SyntaxError:
        return None


def _design_loop_files() -> list[Path]:
    """The Design Studio loop: the ``maistro_design`` package plus the Hive
    backend's design surfaces (the matrix's "Open Design integration" row:
    ``routes.design``, ``services.design_service`` and its render/preview
    siblings). The ``design*.py`` globs keep future design surfaces in scope
    automatically."""
    files = _iter_py(_DESIGN_SRC)
    for subdir in ("routes", "services"):
        files.extend(sorted((_HIVE_BACKEND / subdir).glob("design*.py")))
    return files


def _consumer_files() -> list[Path]:
    """Evolve/RSI sources — the loops that may only *consume* eval records."""
    return [*_iter_py(_EVOLVE_SRC), *_iter_py(_RSI_SRC)]


def _relative(path: Path) -> str:
    try:
        return path.relative_to(_REPO_ROOT).as_posix()
    except ValueError:  # negative-control trees live in tmp_path, not the repo
        return path.as_posix()


def _is_forbidden_root(module: str, roots: tuple[str, ...]) -> bool:
    return any(module == root or module.startswith(f"{root}.") for root in roots)


def _static_import_offenders(tree: ast.Module, path: Path, roots: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"{_relative(path)}:{node.lineno} import {alias.name}"
                for alias in node.names
                if _is_forbidden_root(alias.name, roots)
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and _is_forbidden_root(node.module, roots)
        ):
            offenders.append(f"{_relative(path)}:{node.lineno} from {node.module}")
    return offenders


def _dynamic_import_offenders(tree: ast.Module, path: Path, roots: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _DYNAMIC_IMPORT_FUNCS or not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and _is_forbidden_root(first.value, roots)
        ):
            offenders.append(f"{_relative(path)}:{node.lineno} dynamic import {first.value!r}")
    return offenders


def _forbidden_imports(files: list[Path], roots: tuple[str, ...]) -> list[str]:
    """Static + dynamic imports of any forbidden root, with file:line evidence."""
    offenders: list[str] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        offenders.extend(_static_import_offenders(tree, path, roots))
        offenders.extend(_dynamic_import_offenders(tree, path, roots))
    return offenders


def _forbidden_definitions(
    files: list[Path],
    module_re: re.Pattern[str],
    def_re: re.Pattern[str],
    bank: frozenset[tuple[str, str]] = frozenset(),
) -> list[str]:
    """Forbidden module basenames and class/function definition names.

    ``bank`` exempts exact ``(relative_path, def_name)`` identities reviewed
    and allowed (``_DESIGN_SURFACE_BANK``). A banked name at any other path
    still trips, as does any unbanked name matching ``def_re``.
    """
    offenders: list[str] = []
    for path in files:
        if module_re.match(path.stem):
            offenders.append(f"{_relative(path)}:1 module name {path.stem!r}")
        tree = _parse(path)
        if tree is None:
            continue
        rel = _relative(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and def_re.search(node.name)
                and (rel, node.name) not in bank
            ):
                offenders.append(f"{rel}:{node.lineno} def {node.name}")
    return offenders


def _assign_target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    return []


def _other_score_names(node: ast.AST, path: Path) -> list[tuple[str, int]]:
    if isinstance(node, ast.arg):
        return [(node.arg, node.lineno)]
    if isinstance(node, ast.keyword) and node.arg:
        return [(node.arg, node.lineno)]
    if isinstance(node, ast.Dict):
        return [
            (key.value, key.lineno)
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
    return []


def _forbidden_score_fields(files: list[Path]) -> list[str]:
    """Identifiers that would store a design-quality score outside the canonical homes.

    Walks Assign/AnnAssign targets, annotations, parameters, keywords and dict
    keys via AST, so prose and docstrings never false-positive.
    """
    offenders: list[str] = []
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            names: list[tuple[str, int]] = []
            if isinstance(node, ast.Assign):
                names.extend(
                    (name, node.lineno) for t in node.targets for name in _assign_target_names(t)
                )
            elif isinstance(node, ast.AnnAssign):
                names.extend((name, node.lineno) for name in _assign_target_names(node.target))
            else:
                names.extend(_other_score_names(node, path))
            for name, lineno in names:
                if _SCORE_FIELD_RE.match(name):
                    offenders.append(f"{_relative(path)}:{lineno} score field {name!r}")
    return offenders


# ---------------------------------------------------------------------------
# 1. The Design Studio loop never imports RSI or Evolve as the critic
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_design_loop_does_not_import_rsi_or_evolve() -> None:
    """Design Studio/in-Run loop must not import ``maistro_rsi`` or ``maistro_evolve``.

    The in-Run critic is maistro-core's Rubric eval scored on the canonical
    Run/NodeRun/Attempt spine (#42, ADR-061's no-model DesignEngine). Reaching for
    RSI or Evolve from the loop would stand up a second scoring/promotion loop for
    design work (#796). Evolve/RSI may read Run eval *records* as evidence
    (#21/#552); the loop itself may not call them.
    """
    files = _design_loop_files()
    assert files, "design-loop surface inventory is empty — path drift broke this tripwire"
    offenders = _forbidden_imports(files, _LOOP_FORBIDDEN_IMPORT_ROOTS)
    assert not offenders, (
        "Design Studio loop imports RSI/Evolve as a critic — a second loop (#796). "
        f"The critic is the in-Run Rubric eval; Evolve/RSI consume its records as "
        f"evidence (#21/#552). Offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# 2. Evolve/RSI never reach back into the design Rubric domain
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_evolve_and_rsi_do_not_reach_the_design_rubric_domain() -> None:
    """No Evolve/RSI fitness function imports the design domain or Rubric vocabulary.

    #796 forbids "an Evolve fitness function that ignores Rubric records and
    invents a design-quality score for the same Goal". Scoring design-Goal Rubric
    dimensions requires importing ``maistro_design`` or ``maistro.personas``;
    consuming recorded evidence as history requires neither. (The scan is
    import-based on purpose: benchmark corpora embed design-package strings as
    data, and only an import would be a live scoring path.)
    """
    files = _consumer_files()
    assert files, "evolve/rsi source inventory is empty — path drift broke this tripwire"
    offenders = _forbidden_imports(files, _CONSUMER_FORBIDDEN_IMPORT_ROOTS)
    assert not offenders, (
        "Evolve/RSI reaches into the design Rubric domain — a private design-quality "
        f"score for the same Goal (#796). Consume Run eval records as evidence "
        f"instead (#21/#552). Offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# 3. maistro_design declares no scoring or promotion surface
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_maistro_design_declares_no_scoring_or_promotion_surface() -> None:
    """``maistro_design`` gains no scorer/critic/judge/promoter of its own.

    The design package builds prompts and renders artifacts (ADR-061); a scoring
    module, an evaluator/critic class, or a promotion path inside it is exactly
    the ``maistro-design`` private promotion path #796 forbids — promotion
    belongs to #21, not to the loop. The one acknowledged exception is #779's
    project-quality consistency evaluator (listed as Related in #796):
    deterministic, read-only, "not a self-improvement authority" — banked by
    exact ``(path, name)`` identity in ``_DESIGN_SURFACE_BANK``, never by
    name alone. #987's governed model-judge is the second reviewed exception:
    the canonical ``model_judge`` Rubric method on the governed Invocation
    path, banked the same way. Anything else matching the def-name net —
    including a banked name in a new module — trips here. Bank rows are kept
    live: a row whose code moved or vanished is stale and fails until
    re-reviewed in the PR that moved it.
    """
    files = _iter_py(_DESIGN_SRC)
    assert files, "maistro_design inventory is empty — path drift broke this tripwire"
    offenders = _forbidden_definitions(
        files, _DESIGN_FORBIDDEN_MODULE_RE, _DESIGN_FORBIDDEN_DEF_RE, _DESIGN_SURFACE_BANK
    )
    assert not offenders, (
        "maistro_design declares a scoring/promotion surface — a private design loop "
        f"(#796). Evaluation is the in-Run Rubric eval; promotion is #21's. "
        f"Offenders: {offenders}"
    )
    for rel_path, name in sorted(_DESIGN_SURFACE_BANK):
        path = _REPO_ROOT / rel_path
        assert path.is_file(), (
            f"banked file {rel_path} is gone — drop the stale bank row for {name!r}"
        )
        tree = _parse(path)
        assert tree is not None, f"banked file {rel_path} no longer parses"
        declared = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert name in declared, (
            f"banked def {name!r} no longer declared in {rel_path} — drop the stale "
            "bank row (re-bank only after re-reviewing it against #796)"
        )


# ---------------------------------------------------------------------------
# 4. Design-quality scores have exactly two homes
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_no_design_quality_scores_stored_outside_the_canonical_homes() -> None:
    """No design-quality score field appears in the Design Studio loop's own stores.

    A Goal's quality evidence may live only in (1) Run eval records — the M7
    in-Run Rubric eval — and (2) M4 candidate evaluation (#21). A
    ``design_quality_score`` column/field/key in ``maistro_design`` or the Hive
    design surfaces would be a third, private home bypassing both (#796).
    """
    files = _design_loop_files()
    assert files, "design-loop surface inventory is empty — path drift broke this tripwire"
    offenders = _forbidden_score_fields(files)
    assert not offenders, (
        "Design-quality score stored outside Run eval records + M4 candidate "
        f"evaluation (#796). Offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. The map's anchors: the one eval exists; the M5 pin holds
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_the_one_eval_is_rubric_eval_in_core() -> None:
    """``RubricEval`` still exists in ``maistro.personas.rubric``.

    The map's root node is maistro-core's Rubric eval scored in-Run. If that
    identity moves or is renamed, this map and the tripwires above drift — fix
    the map in the same PR that moves the engine.
    """
    tree = _parse(_RUBRIC_MODULE)
    assert tree is not None, f"{_relative(_RUBRIC_MODULE)} no longer parses"
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert _RUBRIC_EVAL_CLASS in classes, (
        f"{_RUBRIC_EVAL_CLASS} missing from {_relative(_RUBRIC_MODULE)} — the M7-A7 map "
        "names it as the one scoring engine; update the map with the move"
    )


@pytest.mark.contract("boundary")
def test_m5_rsi_nonproduction_pin_still_covers_the_design_loop() -> None:
    """The M5 non-production-reachability suite still fences RSI off from design.

    The map's leaf premise — RSI not production-reachable (#552) — is enforced by
    ``packages/maistro-rsi/tests/test_non_production_reachability.py``, which
    scans ``maistro-design`` as an engine product and allowlists exactly two
    Conductor surfaces. This pin fails if that suite stops covering the design
    loop (engine list trimmed, or a design surface allowlisted), which would
    quietly open the second loop #796 forbids.
    """
    assert _RSI_REACHABILITY_TEST.is_file(), (
        f"{_relative(_RSI_REACHABILITY_TEST)} is gone — the M5 invariant this map "
        "rests on has no enforcer"
    )
    source = _read(_RSI_REACHABILITY_TEST)

    engine_block = re.search(r"for package in \(([^)]*)\)", source, re.DOTALL)
    assert engine_block, "ENGINE_PACKAGE_ROOTS package list not found in the M5 pin"
    assert "maistro-design" in engine_block.group(1), (
        "maistro-design no longer in the M5 engine-package scan — RSI could become "
        "design-loop reachable without that suite failing (#552/#796)"
    )

    confined_block = re.search(
        r"CONFINED_RSI_PRODUCT_SURFACES\s*=\s*frozenset\(\s*\{(.*?)\}\)", source, re.DOTALL
    )
    assert confined_block, "CONFINED_RSI_PRODUCT_SURFACES not found in the M5 pin"
    assert "design" not in confined_block.group(1), (
        "a design surface was allowlisted as an RSI product surface — RSI wiring into "
        "the design loop is exactly the second loop #796 forbids"
    )


# ---------------------------------------------------------------------------
# 6. Negative controls: the tripwires actually trip
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_tripwires_catch_the_forbidden_shapes(tmp_path: Path) -> None:
    """Each scanner flags its forbidden shape in a synthetic tree.

    A green run over ``develop`` is only evidence if the scanners are live: these
    controls build every shape #796 forbids and assert each is caught.
    """
    design_pkg = tmp_path / "maistro_design"
    design_pkg.mkdir()

    loop_file = design_pkg / "engine.py"
    loop_file.write_text(
        "import maistro_evolve.cycle\n"
        "from maistro_rsi.local_loop import LocalRsiLoop\n"
        "import importlib\n\n"
        "def reload() -> None:\n"
        "    importlib.import_module('maistro_rsi.gateway')\n",
        encoding="utf-8",
    )
    caught = _forbidden_imports([loop_file], _LOOP_FORBIDDEN_IMPORT_ROOTS)
    assert len(caught) == 3, f"loop import scanner missed a forbidden shape: {caught}"

    consumer_file = design_pkg.parent / "somewhere" / "fitness.py"
    consumer_file.parent.mkdir()
    consumer_file.write_text(
        "from maistro_design.types import DesignOutput\n"
        "from maistro.personas.rubric import RubricEval\n",
        encoding="utf-8",
    )
    caught = _forbidden_imports([consumer_file], _CONSUMER_FORBIDDEN_IMPORT_ROOTS)
    assert len(caught) == 2, f"consumer import scanner missed a forbidden shape: {caught}"

    promoter = design_pkg / "promote.py"
    promoter.write_text(
        "class DesignCritic:\n    pass\n\n\ndef promote_candidate() -> None:\n    pass\n",
        encoding="utf-8",
    )
    caught = _forbidden_definitions(
        [promoter], _DESIGN_FORBIDDEN_MODULE_RE, _DESIGN_FORBIDDEN_DEF_RE
    )
    assert any("module name 'promote'" in line for line in caught), caught
    assert any("DesignCritic" in line for line in caught), caught
    assert any("promote_candidate" in line for line in caught), caught

    # The design-surface bank is path-pinned: a banked name in a different
    # module is not banked and must trip.
    impostor = design_pkg / "impostor.py"
    impostor.write_text(
        "def evaluate_project_snapshot() -> None:\n    pass\n",
        encoding="utf-8",
    )
    caught = _forbidden_definitions(
        [impostor], _DESIGN_FORBIDDEN_MODULE_RE, _DESIGN_FORBIDDEN_DEF_RE, _DESIGN_SURFACE_BANK
    )
    assert len(caught) == 1 and "evaluate_project_snapshot" in caught[0], (
        f"bank leaked a name outside its pinned path: {caught}"
    )

    score_store = design_pkg / "stores.py"
    score_store.write_text(
        "design_quality_score = 0.9\n"
        "record = {'fitness_score': 0.9}\n\n\n"
        "def store(quality_score: float = 0.0) -> None:\n"
        "    row.design_fitness_score = quality_score\n",
        encoding="utf-8",
    )
    caught = _forbidden_score_fields([score_store])
    assert len(caught) == 4, f"score-field scanner missed a forbidden shape: {caught}"
