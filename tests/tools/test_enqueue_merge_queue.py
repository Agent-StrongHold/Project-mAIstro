from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "check-enqueue-merge-queue.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_enqueue_merge_queue", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def enqueue() -> ModuleType:
    return load_module()


def candidate(enqueue: ModuleType, **overrides: object):
    values = {
        "number": 568,
        "head_sha": "abc123",
        "base_ref": "develop",
        "state": "open",
        "draft": False,
    }
    values.update(overrides)
    return enqueue.Candidate(**values)


def green_statuses() -> list[dict[str, str]]:
    return [
        {
            "context": "gates-ran",
            "state": "success",
            "created_at": "2026-08-28T23:59:00Z",
        }
    ]


def green_checks() -> list[dict[str, str]]:
    return [
        {
            "name": "autonomous-merge-admissibility",
            "conclusion": "success",
            "completed_at": "2026-08-28T23:58:00Z",
        }
    ]


def test_admissible_requires_both_exact_head_signals(enqueue: ModuleType) -> None:
    assert enqueue.is_admissible(candidate(enqueue), green_statuses(), green_checks())

    assert not enqueue.is_admissible(candidate(enqueue), [], green_checks())
    assert not enqueue.is_admissible(candidate(enqueue), green_statuses(), [])


def test_latest_signal_wins(enqueue: ModuleType) -> None:
    statuses = [
        *green_statuses(),
        {
            "context": "gates-ran",
            "state": "failure",
            "created_at": "2026-08-29T00:01:00Z",
        },
    ]
    checks = [
        *green_checks(),
        {
            "name": "autonomous-merge-admissibility",
            "conclusion": "failure",
            "completed_at": "2026-08-29T00:02:00Z",
        },
    ]

    assert not enqueue.is_admissible(candidate(enqueue), statuses, green_checks())
    assert not enqueue.is_admissible(candidate(enqueue), green_statuses(), checks)


def test_wrong_base_draft_and_closed_are_refused(enqueue: ModuleType) -> None:
    for pr in (
        candidate(enqueue, base_ref="main"),
        candidate(enqueue, draft=True),
        candidate(enqueue, state="closed"),
    ):
        assert not enqueue.is_admissible(pr, green_statuses(), green_checks())


def test_queue_request_is_sha_bound_squash_only(enqueue: ModuleType) -> None:
    payload = enqueue.merge_async_payload(candidate(enqueue, head_sha="deadbeef"))

    assert payload == {
        "sha": "deadbeef",
        "merge_method": "squash",
        "merge_action": "merge_queue",
    }
    assert "direct_merge" not in payload.values()


def test_candidate_uses_current_pr_head(enqueue: ModuleType) -> None:
    parsed = enqueue.candidate_from_pr(
        {
            "number": 17,
            "state": "open",
            "draft": False,
            "head": {"sha": "current-head"},
            "base": {"ref": "develop"},
        }
    )

    assert parsed.number == 17
    assert parsed.head_sha == "current-head"

    class RetargetedApi:
        def __init__(self) -> None:
            self.enqueued = False

        def open_develop_prs(self):
            return [
                {
                    "number": 17,
                    "state": "open",
                    "draft": False,
                    "head": {"sha": "current-head"},
                    "base": {"ref": "develop"},
                }
            ]

        def pull_request(self, number: int):
            assert number == 17
            return {
                "number": 17,
                "state": "open",
                "draft": False,
                "head": {"sha": "current-head"},
                "base": {"ref": "main"},
            }

        def statuses(self, sha: str):
            assert sha == "current-head"
            return green_statuses()

        def admission_checks(self, sha: str):
            assert sha == "current-head"
            return green_checks()

        def enqueue(self, candidate):
            self.enqueued = True
            return "accepted"

    api = RetargetedApi()
    assert enqueue.run(api) == 0
    assert not api.enqueued
