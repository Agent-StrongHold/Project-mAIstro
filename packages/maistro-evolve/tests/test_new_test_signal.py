"""The presence-gated new_test signal + net-new test counting."""

from __future__ import annotations

from maistro_evolve.tdd_gate import _count_test_functions, new_test_signal


def test_signal_fires_only_for_a_new_coverage_raising_test() -> None:
    # net-new test AND coverage rose → present, full score.
    s = new_test_signal(1, 0.8, 0.30)
    assert s is not None and s.score == 1.0 and s.weight == 0.30

    # no net-new test → absent (a docstring cycle can't earn it).
    assert new_test_signal(0, 5.0, 0.30) is None
    # a test added but coverage flat/dropped → absent (not substantive).
    assert new_test_signal(2, 0.0, 0.30) is None
    assert new_test_signal(2, -1.0, 0.30) is None
    assert new_test_signal(2, None, 0.30) is None


def test_signal_absent_when_new_source_lines_uncovered() -> None:
    # A net-new test raised the AGGREGATE coverage delta, but the diff also
    # added source lines that remain uncovered (an untested method riding on
    # an unrelated test's credit in the same candidate) — must not fire.
    s = new_test_signal(1, 0.8, 0.30, uncovered_new_lines={"tournament.py": [208, 209]})
    assert s is None


def test_signal_fires_when_no_uncovered_new_lines() -> None:
    # Explicit empty dict (the normal case: nothing new left uncovered).
    s = new_test_signal(1, 0.8, 0.30, uncovered_new_lines={})
    assert s is not None and s.score == 1.0


def test_count_test_functions() -> None:
    src = (
        "def test_a():\n    assert True\n\n"
        "async def test_b():\n    assert True\n\n"
        "def helper():\n    return 1\n\n"
        "class TestX:\n    def test_method(self):\n        assert True\n"
    )
    assert _count_test_functions(src) == 3  # test_a, test_b, test_method (not helper)
    assert _count_test_functions("def (broken syntax") == 0
