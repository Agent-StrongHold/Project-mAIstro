"""CONTRIBUTING and pytest configuration enumerate the same markers (#391).

CONTRIBUTING documented two registered markers while three existed: the
omitted `ac` marker carries 1300+ uses and drives the acceptance-state /
design-coverage gate. Nothing compared the two lists, so the omission was
invisible. These tests make the marker set a checked contract: a marker
added or removed from `pyproject.toml` without matching documentation (or
vice versa) fails here, in the same PR.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

#: A marker-table row: `| `@pytest.mark.<name>(...)` | ... |`
_ROW_RE = re.compile(r"^\| `@pytest\.mark\.(?P<name>\w+)\(")

#: A `scripts/...` path named inside a table row's consumer cell.
_SCRIPT_RE = re.compile(r"`(scripts/[\w./-]+)`")

#: The axis values each marker accepts, as documented in pyproject itself —
#: the marker description is the single source the doc must not contradict.
_AXIS_VALUES = {
    "contract": {"boundary", "behavioral", "cross-service"},
    "scope": {"unit", "integration", "e2e", "property"},
}


def registered_markers() -> dict[str, str]:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    out: dict[str, str] = {}
    for entry in markers:
        name, _, description = entry.partition(":")
        out[name.strip()] = description.strip()
    return out


def documented_markers() -> dict[str, list[str]]:
    """`name -> consumer script paths`, from CONTRIBUTING's marker table."""
    out: dict[str, list[str]] = {}
    for line in CONTRIBUTING.read_text().splitlines():
        row = _ROW_RE.match(line)
        if row is None:
            continue
        out.setdefault(row["name"], []).extend(_SCRIPT_RE.findall(line))
    return out


# --- the two lists are the same list ---------------------------------------


def test_every_registered_marker_is_documented() -> None:
    """The #391 defect: `ac` registered, 1300+ uses, absent from the docs."""
    missing = sorted(set(registered_markers()) - set(documented_markers()))
    assert not missing, (
        f"pyproject.toml registers {missing} but CONTRIBUTING's marker table "
        "does not document them — same-PR documentation is the rule (#391)."
    )


def test_every_documented_marker_is_registered() -> None:
    ghost = sorted(set(documented_markers()) - set(registered_markers()))
    assert not ghost, (
        f"CONTRIBUTING documents {ghost} but pyproject.toml does not register "
        "them — with --strict-markers such a marker fails collection."
    )


def test_each_marker_row_documents_meaning_consumer_and_ci_effect() -> None:
    """Semantics, owner/consumer, and effect on CI — the issue's requirement.

    Four cells per row: marker, meaning, consumer, CI effect. A row missing a
    cell reads as documentation while answering none of the three questions.
    """
    lines = [
        line for line in CONTRIBUTING.read_text().splitlines() if _ROW_RE.match(line) is not None
    ]
    assert lines, "CONTRIBUTING has no marker table rows"
    for line in lines:
        assert line.count("|") >= 5, f"marker row lacks a column: {line[:60]!r}"


def test_the_consumer_scripts_named_in_the_table_exist() -> None:
    """A documented consumer that does not exist documents nothing.

    A gate-consumed marker must name its script (`scripts/...`); a selection
    axis marker instead names the `pytest -m` selection that consumes it.
    Either way the row has to say who reads the marker — the #391 omission
    was invisible partly because nothing asked that question.
    """
    text = CONTRIBUTING.read_text()
    for name, scripts in documented_markers().items():
        if scripts:
            for script in scripts:
                assert (ROOT / script).is_file(), f"{name} consumer {script} missing"
        else:
            assert f'pytest -m "{name}"' in text or f"pytest -m {name}" in text, (
                f"marker {name} names neither a consumer script nor a "
                "pytest -m selection that consumes it"
            )


# --- unknown markers fail, per the strictness the docs now claim -----------


def test_pytest_runs_with_strict_markers() -> None:
    """The docs say unknown markers fail; addopts must make that true."""
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--strict-markers" in addopts, "CONTRIBUTING promises --strict-markers"


@pytest.mark.parametrize("name", sorted(registered_markers()))
def test_axis_markers_document_only_their_registered_values(name: str) -> None:
    """The example block must use values the marker actually accepts."""
    if name not in _AXIS_VALUES:
        pytest.skip(f"{name} takes free-form ids, not a fixed axis")
    examples = re.findall(rf"@pytest\.mark\.{name}\(\"([^\"]+)\"\)", CONTRIBUTING.read_text())
    assert examples, f"no {name} example in CONTRIBUTING"
    for value in examples:
        assert value in _AXIS_VALUES[name], (
            f"CONTRIBUTING example {name}({value!r}) is not one of {sorted(_AXIS_VALUES[name])}"
        )
