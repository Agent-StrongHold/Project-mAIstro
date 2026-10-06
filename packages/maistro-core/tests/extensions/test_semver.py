"""Strict semantic-version parsing and range matching (M9-C2, #956).

The parser is the determinism foundation of dependency resolution: every
ordering and satisfaction decision reduces to it. These tests pin the strict
``MAJOR.MINOR.PATCH`` grammar, numeric (not lexicographic) ordering, every
comparator operator, and the loud failures for anything outside the grammar.
"""

from __future__ import annotations

import pytest

from maistro.extensions.semver import (
    InvalidSemanticVersion,
    InvalidVersionRange,
    SemVer,
    parse_range,
)


def test_parse_accepts_strict_versions() -> None:
    assert SemVer.parse("1.2.3") == SemVer(1, 2, 3)
    assert SemVer.parse("  0.0.0  ") == SemVer(0, 0, 0)
    assert SemVer.parse("10.20.30") == SemVer(10, 20, 30)


@pytest.mark.parametrize(
    "text",
    [
        "1.2",
        "1",
        "v1.2.3",
        "1.2.3-rc1",
        "1.2.3+build",
        "01.2.3",
        "1.2.x",
        "-1.2.3",
        "1.2.3.4",
        "",
        "one.two.three",
    ],
)
def test_parse_rejects_everything_outside_the_contract(text: str) -> None:
    with pytest.raises(InvalidSemanticVersion):
        SemVer.parse(text)


def test_ordering_is_numeric_not_lexicographic() -> None:
    assert SemVer.parse("1.2.3") < SemVer.parse("1.10.0")
    assert SemVer.parse("1.10.0") < SemVer.parse("2.0.0")
    assert SemVer.parse("2.0.0") < SemVer.parse("10.0.0")
    assert SemVer.parse("1.2.3") == SemVer.parse("1.2.3")
    assert sorted(map(SemVer.parse, ["1.9.0", "1.10.0", "1.2.0"])) == [
        SemVer(1, 2, 0),
        SemVer(1, 9, 0),
        SemVer(1, 10, 0),
    ]


def test_str_round_trips_the_version() -> None:
    assert str(SemVer.parse("1.2.3")) == "1.2.3"


@pytest.mark.parametrize(
    ("range_text", "version", "expected"),
    [
        ("*", "0.0.1", True),
        ("*", "99.9.9", True),
        ("1.2.3", "1.2.3", True),  # bare version is an exact pin
        ("1.2.3", "1.2.4", False),
        ("==1.2.3", "1.2.3", True),
        ("!=1.2.3", "1.2.4", True),
        ("!=1.2.3", "1.2.3", False),
        (">1.2.3", "1.2.4", True),
        (">1.2.3", "1.2.3", False),
        (">=1.2.3", "1.2.3", True),
        (">=1.2.3", "1.2.2", False),
        ("<2.0.0", "1.9.9", True),
        ("<2.0.0", "2.0.0", False),
        ("<=2.0.0", "2.0.0", True),
        ("<=2.0.0", "2.0.1", False),
        # The documented contract-pin form: AND across comma clauses.
        (">=1.0.0,<2.0.0", "1.0.0", True),
        (">=1.0.0,<2.0.0", "1.9.9", True),
        (">=1.0.0,<2.0.0", "2.0.0", False),
        (">=1.0.0,<2.0.0", "0.9.0", False),
        (">=1.0.0,<2.0.0,!=1.5.0", "1.5.0", False),
        (">=1.0.0,<2.0.0,!=1.5.0", "1.4.0", True),
    ],
)
def test_range_satisfaction_truth_table(range_text: str, version: str, expected: bool) -> None:
    assert parse_range(range_text).satisfied_by(SemVer.parse(version)) is expected


def test_range_keeps_the_declared_text_verbatim() -> None:
    assert str(parse_range(">=1.0.0, <2.0.0")) == ">=1.0.0, <2.0.0"


def test_first_violation_is_stable_in_declaration_order() -> None:
    # Both clauses fail for 0.5.0; the first declared clause is reported.
    violation = parse_range(">=1.0.0,<2.0.0").violated_by_reason(SemVer.parse("0.5.0"))
    assert violation == "fails '>=1.0.0'"
    assert parse_range(">=1.0.0,<2.0.0").violated_by_reason(SemVer.parse("2.5.0")) == (
        "fails '<2.0.0'"
    )
    assert parse_range(">=1.0.0").violated_by_reason(SemVer.parse("1.2.0")) is None


@pytest.mark.parametrize(
    "range_text",
    [
        "",
        "   ",
        ">=1.2",
        ">= 1.2",
        "~1.2.3",
        "^1.2.3",
        "1.2.3,",
        ">=1.0.0,<2.0",
        ">=1.0.0,,<2.0.0",
        "=>1.0.0",
        "latest",
    ],
)
def test_invalid_ranges_fail_loudly(range_text: str) -> None:
    with pytest.raises(InvalidVersionRange):
        parse_range(range_text)
