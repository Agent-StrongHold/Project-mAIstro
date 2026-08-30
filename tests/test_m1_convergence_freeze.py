"""Executable evidence for the M1 no-new-islands freeze (#460)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-m1-convergence-freeze.py"
MATRIX = ROOT / "docs" / "architecture" / "CONVERGENCE-MATRIX.md"
POLICY = ROOT / "quality" / "m1-convergence-freeze.json"
ONTOLOGY = ROOT / "quality" / "shared-interop-ontology-v1.json"
PR_TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m1_convergence_freeze", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix(*subsystems: str) -> str:
    rows = "\n".join(f"| {name} | `example.{index}` |" for index, name in enumerate(subsystems))
    return f"# matrix\n\n<!-- matrix:ownership -->\n| Subsystem | Modules |\n|---|---|\n{rows}\n"


def _policy() -> dict[str, object]:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _ontology() -> dict[str, object]:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _exception_plan() -> str:
    return "\n".join(
        (
            "Architecture rationale: the canonical owner cannot yet represent this reviewed extension",
            "Canonical owner: maistro.runs remains the execution authority",
            "Disposition owner: #460 follow-up owner",
            "Retirement/convergence path: retire the extension after the canonical seam supports it",
        )
    )


def test_new_subsystem_is_rejected_without_exception() -> None:
    checker = _module()
    current = _matrix("Canonical", "New island")
    base = _matrix("Canonical")

    failures = checker.check(current, base, exception=False)

    assert len(failures) == 1
    assert "New island" in failures[0]
    assert "m1-convergence-exception" in failures[0]


def test_exception_label_without_complete_plan_is_rejected() -> None:
    checker = _module()

    failures = checker.check(
        _matrix("Canonical", "Reviewed extension"),
        _matrix("Canonical"),
        exception=True,
        exception_plan="Architecture rationale: seems useful",
        policy=_policy(),
    )

    assert failures
    assert any("canonical_owner" in failure for failure in failures)
    assert any("disposition_owner" in failure for failure in failures)
    assert any("retirement_path" in failure for failure in failures)


def test_explicit_exception_allows_reviewed_new_subsystem() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical", "Reviewed extension"),
            _matrix("Canonical"),
            exception=True,
            exception_plan=_exception_plan(),
            policy=_policy(),
        )
        == []
    )


def test_shrinking_the_island_set_is_always_allowed() -> None:
    checker = _module()

    assert (
        checker.check(
            _matrix("Canonical"),
            _matrix("Canonical", "Legacy island"),
            exception=False,
        )
        == []
    )


def test_policy_reuses_the_existing_architecture_vocabulary() -> None:
    checker = _module()

    assert checker.validate_authoritative_gate_map(_policy()) == []


def test_second_run_lifecycle_is_seen_by_the_existing_lifecycle_detector() -> None:
    checker = _module()
    source = """
from enum import StrEnum

class ShadowRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
"""

    found = checker.lifecycle_candidates(source, "product.shadow")

    assert "product.shadow::ShadowRunStatus" in found
    assert found["product.shadow::ShadowRunStatus"] == {"PENDING", "RUNNING", "FAILED"}


def test_direct_model_egress_is_seen_by_the_existing_egress_detector() -> None:
    checker = _module()
    source = """
ENDPOINT = "/v1/chat/completions"
client.post(ENDPOINT)
"""

    assert checker.performs_model_egress(source)


def test_new_workspace_authority_outside_canonical_owner_is_rejected() -> None:
    checker = _module()

    failures = checker.new_shared_owner_violations(
        "class WorkspaceStore:\n    pass\n",
        "",
        module="maistro_canvas.shadow",
        policy=_policy(),
        ontology=_ontology(),
    )

    assert len(failures) == 1
    assert "Workspace" in failures[0]
    assert "maistro_canvas.shadow::WorkspaceStore" in failures[0]


def test_new_event_sequence_outside_canonical_owner_is_rejected() -> None:
    checker = _module()

    failures = checker.new_shared_owner_violations(
        "class ProductEventSequence:\n    pass\n",
        "",
        module="maistro_turing.shadow",
        policy=_policy(),
        ontology=_ontology(),
    )

    assert len(failures) == 1
    assert "Event" in failures[0]


def test_canonical_owner_may_extend_its_own_shared_concept() -> None:
    checker = _module()

    assert (
        checker.new_shared_owner_violations(
            "class WorkspaceStore:\n    pass\n",
            "",
            module="maistro.workspaces.store",
            policy=_policy(),
            ontology=_ontology(),
        )
        == []
    )


def test_product_local_projection_must_name_the_canonical_concept() -> None:
    checker = _module()
    source = '''class DagRunStore:
    """M1 product-local projection: Run"""
'''

    assert (
        checker.new_shared_owner_violations(
            source,
            "",
            module="services.dag_run_store",
            policy=_policy(),
            ontology=_ontology(),
        )
        == []
    )


def test_existing_legacy_owner_is_not_recharged_when_its_file_changes() -> None:
    checker = _module()
    source = "class WorkspaceStore:\n    pass\n"

    assert (
        checker.new_shared_owner_violations(
            source,
            source,
            module="legacy.product",
            policy=_policy(),
            ontology=_ontology(),
        )
        == []
    )


def test_new_checkpoint_store_uses_the_supplemental_canonical_owner_map() -> None:
    checker = _module()

    failures = checker.new_shared_owner_violations(
        "class CheckpointStore:\n    pass\n",
        "",
        module="new_product.recovery",
        policy=_policy(),
        ontology=_ontology(),
    )

    assert len(failures) == 1
    assert "Checkpoint" in failures[0]


def test_pr_template_asks_the_no_new_islands_review_question() -> None:
    template = PR_TEMPLATE.read_text(encoding="utf-8")

    assert "new universal execution/scope/event/effect/approval/recovery owner" in template
    for marker in (
        "Architecture rationale:",
        "Canonical owner:",
        "Disposition owner:",
        "Retirement/convergence path:",
    ):
        assert marker in template


def test_live_pull_request_does_not_add_unapproved_subsystem() -> None:
    """Make the freeze a real PR gate, not merely a unit-tested policy helper."""
    base_ref = os.environ.get("GITHUB_BASE_REF")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not base_ref or not event_path:
        # Local/push runs still execute the policy tests above. The live
        # comparison is meaningful only when Actions has checked out a PR and
        # fetched its base ref.
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request", {})
    labels = {
        item.get("name", "")
        for item in pull_request.get("labels", [])
        if isinstance(item, dict)
    }
    # `actions/checkout` clones one commit deep, so `origin/<base>` does not
    # exist in the `test` job and the checker died on `invalid object name`
    # (#497). Fetch it here rather than skipping when it is absent: guarding on
    # the ref's presence would turn a gate that never runs into a gate that
    # looks like it passed, which is the failure this whole freeze exists to
    # prevent one level up.
    base = _fetched_base(base_ref)
    command = [sys.executable, str(CHECKER), "--base", base]
    env = os.environ.copy()
    env["M1_CONVERGENCE_EXCEPTION_PLAN"] = str(pull_request.get("body") or "")
    if "m1-convergence-exception" in labels:
        command.append("--exception")

    subprocess.run(command, cwd=ROOT, check=True, env=env)


def _fetched_base(base_ref: str) -> str:
    """A revision naming the PR's base, fetched if the shallow clone lacks it.

    Returns whatever revision the checker should compare against: the existing
    remote-tracking ref when the clone is complete enough to have one, and the
    freshly fetched `FETCH_HEAD` otherwise.
    """
    remote_ref = f"origin/{base_ref}"
    if _rev_exists(remote_ref):
        return remote_ref

    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return "FETCH_HEAD"


def _rev_exists(revision: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


class TestTheBaseRevisionIsResolvedNotAssumed:
    """`actions/checkout` clones one commit deep, so the base ref the live
    comparison needs is simply absent in the `test` job (#497). These cover the
    resolution, because the alternative fix -- skipping when it is missing --
    would turn a gate that never runs into one that looks like it passed.
    """

    def test_an_existing_remote_ref_is_used_as_is(self, monkeypatch) -> None:
        """No fetch when the clone already has it: a network round trip on
        every local run would be a cost paid for nothing."""
        fetched: list[list[str]] = []
        module = sys.modules[__name__]
        monkeypatch.setattr(module, "_rev_exists", lambda revision: True)
        monkeypatch.setattr(module, "subprocess", _FakeSubprocess(fetched))

        assert module._fetched_base("develop") == "origin/develop"
        assert fetched == []

    def test_a_missing_ref_is_fetched_and_compared_against_FETCH_HEAD(self, monkeypatch) -> None:
        fetched: list[list[str]] = []
        module = sys.modules[__name__]
        monkeypatch.setattr(module, "_rev_exists", lambda revision: False)
        monkeypatch.setattr(module, "subprocess", _FakeSubprocess(fetched))

        assert module._fetched_base("develop") == "FETCH_HEAD"
        assert fetched == [["git", "fetch", "--no-tags", "--depth=1", "origin", "develop"]]

    def test_the_repositorys_own_base_resolves(self) -> None:
        """Against the real clone rather than a fake: the helper has to name a
        revision `git` will actually accept -- and it has to do it without a
        network call.

        Never `_fetched_base("HEAD")`: `origin/HEAD` is absent in plenty of
        checkouts, so that spelling sends an unconditional test down the fetch
        path, and the whole root suite then fails in any clone with no `origin`
        or an unreachable one -- while the live PR gate this belongs to is not
        even active.

        The earlier fix for that named whichever remote ref the clone happened
        to have and skipped when it had none. That worked, but a conditional
        skip is a test that stops running when the condition changes, and the
        condition here is "somebody's checkout". So the ref is *made* instead:
        one temporary remote-tracking ref, pointing at HEAD, deleted again in
        `finally`. The no-fetch branch is then covered in every clone, on every
        machine, with no network and nothing to skip.
        """
        ref = "m1-freeze-selftest"
        qualified = f"refs/remotes/origin/{ref}"
        subprocess.run(
            ["git", "update-ref", qualified, "HEAD"], cwd=ROOT, check=True, capture_output=True
        )
        try:
            assert _fetched_base(ref) == f"origin/{ref}"
            assert _rev_exists(f"origin/{ref}")
        finally:
            subprocess.run(
                ["git", "update-ref", "-d", qualified],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )


class _FakeSubprocess:
    """Records `run` calls instead of making them."""

    def __init__(self, calls: list[list[str]]) -> None:
        self._calls = calls

    def run(self, command: list[str], **_kwargs: object) -> object:
        self._calls.append(list(command))
        return object()
