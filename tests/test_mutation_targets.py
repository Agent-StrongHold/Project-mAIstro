"""The mutation job's file→tests mapping, tested rather than trusted.

This logic used to not exist: the PR mutation job mutated the whole package
against the whole test suite, hit its 30-minute wall, and reported "cancelled"
on every PR that triggered it. Scoping is what makes the gate finishable, so
the scoping itself needs to be correct — and the one outcome that must never
happen silently is "fell back to the entire suite", which is the behavior that
caused the timeout.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import ClassVar

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "mutation_targets.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("_mutation_targets", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    yield mod
    del sys.modules[spec.name]


def test_exact_mirror_is_preferred(module):
    got = module.resolve_tests("packages/maistro-core/src/maistro/router/scorer.py")
    assert got == Path("packages/maistro-core/tests/router/test_scorer.py")


def test_nested_mirror_resolves(module):
    got = module.resolve_tests("packages/maistro-core/src/maistro/security/warden/detector.py")
    assert got == Path("packages/maistro-core/tests/security/warden/test_detector.py")


def test_falls_back_to_nearest_test_directory(module):
    """No mirror file exists for harness_executor.py; the package's test dir is
    the most specific thing that does."""
    got = module.resolve_tests("packages/maistro-core/src/maistro/graph/harness_executor.py")
    assert got == Path("packages/maistro-core/tests/graph")


def test_never_falls_back_to_the_whole_suite(module):
    """The critical property. Returning bare `tests/` would restore exactly the
    unscoped run that made this job time out — so an unresolvable file must be
    skipped (None), never widened to everything."""
    got = module.resolve_tests("packages/maistro-core/src/maistro/nonexistent_subsystem/mod.py")
    assert got != Path("packages/maistro-core/tests")
    assert got is None


def test_files_outside_core_are_not_mapped(module):
    assert module.resolve_tests("packages/maistro-rsi/src/maistro_rsi/runner.py") is None
    assert module.resolve_tests("README.md") is None


def test_full_codebase_resolver_maps_sibling_package(module):
    got = module.resolve_package_tests("packages/maistro-rsi/src/maistro_rsi/runner.py")
    assert got == Path("packages/maistro-rsi/tests/test_runner.py")


def test_full_codebase_resolver_maps_external_registry_tests(module):
    got = module.resolve_package_tests(
        "packages/maistro-registry/src/maistro_registry/validator.py"
    )
    assert got == Path("tests/tools/registry/test_validator.py")


def test_full_codebase_resolver_maps_hive_nonbackend_to_unit_tests(module):
    got = module.resolve_package_tests("packages/hive-conductor/cage/permission_boundary.py")

    assert got == Path("tests/hive_conductor")


def test_every_production_source_has_a_mutation_test_scope(module):
    sources = module.production_sources()
    assert len(sources) >= 800
    unresolved = [source for source in sources if module.resolve_package_tests(source) is None]
    assert unresolved == []


def test_every_resolved_path_exists_on_disk(module):
    """A mapping that points at a path pytest can't collect would make every
    mutant 'killed' by usage error — the same vacuous-pass failure mode as the
    missing pytest-timeout plugin."""
    for src in (
        "packages/maistro-core/src/maistro/router/scorer.py",
        "packages/maistro-core/src/maistro/security/warden/detector.py",
        "packages/maistro-core/src/maistro/graph/harness_executor.py",
    ):
        resolved = module.resolve_tests(src)
        assert resolved is not None
        assert (REPO / resolved).exists(), resolved


class TestBudgetPrioritisation:
    """When the budget is partial, it is spent where a survivor is worst — and
    what got dropped is always named.

    The tiering: feature -> develop caps the file count for fast feedback,
    develop -> main runs a full sweep as the release gate.
    """

    ALL: ClassVar[list[str]] = [
        "packages/maistro-core/src/maistro/graph/harness_executor.py",
        "packages/maistro-core/src/maistro/router/scorer.py",
        "packages/maistro-core/src/maistro/security/warden/detector.py",
        "packages/maistro-core/src/maistro/memory/outcomes.py",
    ]

    def test_security_outranks_router_outranks_graph(self, module):
        ranks = [module.priority(p) for p in self.ALL]
        graph, router, security, other = ranks
        assert security < router < graph < other

    def test_limit_keeps_the_highest_priority_files(self, module, capsys):
        module.main(["--limit", "2", "\n".join(self.ALL)])
        out = capsys.readouterr()
        kept = [line.split("\t")[0] for line in out.out.strip().splitlines()]
        assert "security/warden/detector.py" in kept[0]
        assert "router/scorer.py" in kept[1]
        assert len(kept) == 2

    def test_dropped_files_are_named_not_silently_skipped(self, module, capsys):
        """The load-bearing property. A gate that quietly covers less than it
        claims is exactly the phantom-gate failure this workflow was rewritten
        to remove, so truncation must be loud and itemised."""
        module.main(["--limit", "1", "\n".join(self.ALL)])
        err = capsys.readouterr().err
        assert "::warning::" in err
        assert "NOT mutated" in err
        for dropped in ("router/scorer.py", "graph/harness_executor.py"):
            assert dropped in err, dropped

    def test_zero_limit_means_full_sweep(self, module, capsys):
        """The develop -> main release gate passes --limit 0."""
        module.main(["--limit", "0", "\n".join(self.ALL)])
        out = capsys.readouterr()
        assert len(out.out.strip().splitlines()) == len(self.ALL)
        assert "NOT mutated" not in out.err


class TestDeletedSourcesAreNotTargets:
    """Codex review of #267 (P2): every check in `resolve_tests` validates a
    TEST path, none validated the source. A module deleted by the PR keeps its
    test directory, so it resolved, consumed a capped slot ahead of a live
    modified file, and handed cosmic-ray a `module-path` pointing at nothing.
    """

    DELETED: ClassVar[str] = "packages/maistro-core/src/maistro/security/warden/removed_rules.py"

    def test_a_deleted_source_resolves_to_nothing(self, module):
        """The deleted file's test directory (`tests/security/warden/`) exists
        and would have satisfied the ancestor walk — the source check is the
        only thing standing between it and a wasted budget slot."""
        assert (REPO / "packages/maistro-core/tests/security/warden").is_dir()
        assert not (REPO / self.DELETED).exists()
        assert module.resolve_tests(self.DELETED) is None

    def test_a_deleted_file_cannot_displace_a_live_one(self, module):
        """A deleted source is reported, while the live source remains targetable."""
        live = "packages/maistro-core/src/maistro/router/scorer.py"
        targets, unresolved = module._resolve_targets([self.DELETED, live])
        assert unresolved == [self.DELETED]
        assert [source for source, _ in targets] == [live]
        assert targets[0][1] == Path("packages/maistro-core/tests/router/test_scorer.py")

    def test_live_sources_are_unaffected(self, module):
        """The check must not become a filter that quietly drops real work."""
        assert (
            module.resolve_tests("packages/maistro-core/src/maistro/router/scorer.py") is not None
        )


class TestPolicyPriorityIsReachable:
    """Codex review of #267 (P2): `policy/` ranked second in the priority table
    while the workflow's `paths:` filter and diff pathspec both omitted it, so
    a policy-only PR never started the job and the ranking was unreachable —
    a coverage claim nothing delivered.
    """

    WORKFLOW: ClassVar[Path] = REPO / ".github" / "workflows" / "mutation.yml"

    def test_the_policy_subtree_actually_exists(self, module):
        """If it did not, the honest fix would be deleting the priority entry
        rather than adding a path filter for nothing."""
        assert (REPO / "packages/maistro-core/src/maistro/policy").is_dir()

    def test_every_package_source_is_in_the_workflow_scope(self, module):
        """The property, not the example. Any future priority entry that the
        workflow cannot see is unreachable ranking — this fails on the next one
        too, without anyone remembering to add a test."""
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        assert "'packages/**/*.py'" in workflow
        assert "-- packages" in workflow


class TestWorkflowDiffsAgainstItsOwnBase:
    """Codex review of #267 (P1). The changed-files step diffed
    `origin/main...HEAD` on a workflow that also runs for PRs into
    develop/integration, so it attributed everything the base branch carries
    beyond main to the PR. Measured on #267 itself: 0 files under the
    load-bearing subtrees vs origin/develop, 13 vs origin/main — the entire
    4-file budget spent on inherited code, passing a gate that said nothing
    about the change under review.
    """

    WORKFLOW: ClassVar[Path] = REPO / ".github" / "workflows" / "mutation.yml"

    @staticmethod
    def _code_lines(text: str) -> str:
        """Executable YAML/shell only. The fix's own comment quotes the broken
        `origin/main...HEAD` to explain what it replaced, and a naive substring
        check over the whole file fails on that prose — which it did, on the
        first run of this test."""
        return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    def test_no_hardcoded_main_in_the_changed_files_diff(self):
        code = self._code_lines(self.WORKFLOW.read_text(encoding="utf-8"))
        assert "origin/main...HEAD" not in code
        assert "origin/$BASE_REF...HEAD" in code

    def test_base_ref_is_passed_through_env_not_interpolated_into_shell(self):
        """A branch name inlined into a run script is an injection seam, and it
        is attacker-influenced on fork PRs."""
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        assert "BASE_REF: ${{ github.base_ref }}" in workflow
        assert "${{ github.base_ref }}...HEAD" not in workflow

    def test_deletions_are_filtered_out_of_the_diff(self):
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        assert "--diff-filter=ACMR" in workflow


# --- the inverse mapping: changed tests -> the sources they cover ------------
#
# A PR that only adds tests was invisible to the mutation gate: the workflow's
# paths filter omitted the test subtrees and its changed-files filter stripped
# `/tests/`, so the one kind of PR whose purpose is killing surviving mutants
# never started the job that measures them.


def test_a_mirror_test_maps_back_to_exactly_one_source(module):
    got = module.sources_for_test("packages/maistro-core/tests/router/test_scorer.py")
    assert got == ["packages/maistro-core/src/maistro/router/scorer.py"]


def test_a_non_mirror_test_maps_to_its_whole_package(module):
    """The case that actually occurs, and the reason a mirror-only inverse
    would have been useless.

    The file that motivated this is `test_executor_mutants.py`, which mirrors
    to `executor_mutants.py` — a module that does not exist. Falling back to
    the package the test directory covers is what makes the real PR resolve.
    """
    got = module.sources_for_test(
        "packages/maistro-core/tests/graph/durable_runs/test_executor_mutants.py"
    )

    assert "packages/maistro-core/src/maistro/graph/durable_runs/executor.py" in got
    assert len(got) > 1, "a non-mirror test should widen to its package"


def test_dunder_init_is_never_a_target(module):
    """`__init__.py` sorts ahead of every real module in its package.

    Targets are ranked by (priority, path) and truncated at the cap, so
    including it would spend a capped slot on re-exports while the module the
    tests were written for went unmutated.
    """
    got = module.sources_for_test(
        "packages/maistro-core/tests/graph/durable_runs/test_executor_mutants.py"
    )

    assert not any(p.endswith("__init__.py") for p in got)


def test_a_source_and_its_tests_collapse_to_one_target(module):
    """Changing both must not mutate the same file twice and burn two slots."""
    got = module.expand(
        [
            "packages/maistro-core/src/maistro/graph/durable_runs/executor.py",
            "packages/maistro-core/tests/graph/durable_runs/test_executor_mutants.py",
        ]
    )

    executor = "packages/maistro-core/src/maistro/graph/durable_runs/executor.py"
    assert got.count(executor) == 1
    assert got[0] == executor, "the directly-changed source should keep its position"


def test_a_non_core_path_passes_through_unchanged(module):
    assert module.expand(["packages/maistro-server/src/x.py"]) == [
        "packages/maistro-server/src/x.py"
    ]


def test_an_unknown_test_directory_resolves_to_nothing(module):
    """Fail closed: an unmappable test path must not widen to a whole package
    that happens to exist further up."""
    assert module.sources_for_test("packages/maistro-core/tests/nope/test_x.py") == []


def test_the_motivating_pr_now_produces_a_target(module):
    """End-to-end regression for PR #320, which changed only a test file and
    produced zero targets before this mapping existed."""
    targets = module.expand(
        ["packages/maistro-core/tests/graph/durable_runs/test_executor_mutants.py"]
    )

    resolved = [(s, module.resolve_tests(s)) for s in targets]
    assert any(s.endswith("durable_runs/executor.py") and t is not None for s, t in resolved), (
        "a test-only change still resolves to no mutatable target"
    )


class TestGateScriptsAreTargetable:
    """#419. `mutation_targets.py` resolved only paths under `packages/`, so
    every gate in `scripts/` — the code that decides whether anything else may
    merge — was the one body of Python mutation could not reach. The same blind
    spot #257 closed for diff coverage, one instrument later."""

    def test_a_gate_script_resolves_to_its_mirror_test(self, module):
        assert module.resolve_script_tests("scripts/check-ac-state.py") == Path(
            "tests/test_check_ac_state.py"
        )

    def test_a_dashed_name_maps_to_an_underscored_test(self, module):
        """Every gate here is `check-thing.py` tested by `test_check_thing.py`;
        a resolver that did not translate the separator would resolve none."""
        assert module.resolve_script_tests("scripts/check-cross-package-imports.py") == Path(
            "tests/test_check_cross_package_imports.py"
        )

    def test_a_script_without_a_mirror_test_is_skipped_not_widened(self, module):
        """There is no ancestor to widen to — `tests/` is the whole root suite,
        and mutating one script against all of it is exactly the unbounded
        scope that produced the original 30-minute timeout."""
        assert module.resolve_script_tests("scripts/mutation_packet.py") is None

    def test_a_nested_path_is_not_treated_as_a_gate_script(self, module):
        """Only `scripts/<name>.py` directly. A nested file has no mirror
        convention, so inventing one resolves to a test that is not its."""
        assert module.resolve_script_tests("scripts/sub/thing.py") is None

    def test_a_package_source_is_left_to_the_package_resolver(self, module):
        source = "packages/maistro-core/src/maistro/router/scorer.py"
        assert module.resolve_script_tests(source) is None

    def test_the_dispatch_tries_scripts_before_packages(self, module):
        """`resolve_package_tests` returns None for everything in `scripts/`,
        so a gate script resolves only if the dispatch tries scripts first."""
        targets, unresolved = module._resolve_targets(["scripts/check-ac-state.py"])
        assert unresolved == []
        assert targets == [("scripts/check-ac-state.py", Path("tests/test_check_ac_state.py"))]
