"""Tests for the SECURITY.md gate (#157).

The gate exists because three specific failures happened, so the tests are
organised around them rather than around the functions:

1. Known Limitation #1 named three files as having no SSRF guard; all three
   had one, and a second SSRF implementation got written because of it.
2. The replacement text said "three of eleven outbound surfaces". It was three
   of twenty-five — an unmeasured number in the very change whose purpose was
   that this document carried unmeasured numbers.
3. Two inventory line citations had drifted: the constant had moved, the line
   number had not.

Each gets a case that fails on a synthetic document reproducing it, so a
regression is caught rather than rediscovered. A gate that only passed on the
real document would prove nothing — passing is the state a gate spends its life
in, and the property that matters is which documents it *rejects*.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-security-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_security_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _limitations(body: str) -> str:
    return f"## Known Limitations (honest assessment)\n\n{textwrap.dedent(body).strip()}\n"


def _inventory(rows: str) -> str:
    return (
        "## Resource-limits inventory\n\n"
        "| Limit | Value | Source | Notes |\n"
        "|---|---|---|---|\n"
        f"{textwrap.dedent(rows).strip()}\n"
    )


# --------------------------------------------------------------------------
# Failure 1: a control claimed absent from a file that has it
# --------------------------------------------------------------------------


def test_the_original_ssrf_falsehood_is_rejected(gate):
    """Verbatim shape of the text that shipped: three real files, named as
    having no guard, all three of which call one."""
    text = _limitations(
        """
        1. **No SSRF blocklist for outbound HTTP.** Skills, connectors, and the browser tool
           all make outbound HTTP calls (`skills/marketplace.py`, `skills/import_pipeline.py`,
           `tools/browser/client.py`). Nothing blocks a request to `169.254.169.254`.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    named = " ".join(findings.contradicted_absences)
    assert "skills/marketplace.py" in named
    assert "skills/import_pipeline.py" in named
    assert "tools/browser/client.py" in named


def test_a_file_that_genuinely_lacks_the_control_is_not_flagged(gate):
    """The check must be able to say yes. `skills/connectors.py` opens outbound
    HTTP and calls no guard, so naming it is accurate, not drift."""
    text = _limitations(
        """
        1. **No SSRF guard on the registry fetches.** `skills/connectors.py` reaches
           outbound hosts with no SSRF check of any kind.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert findings.contradicted_absences == []


def test_a_negation_elsewhere_in_the_bullet_does_not_condemn_the_citation(gate):
    """The bullet-scoped first version failed here, and the failure was
    unfixable in code: the document says these files *are* guarded, and says
    "no" about something else entirely. Only vaguer prose would have passed."""
    text = _limitations(
        """
        1. **Two divergent SSRF guards.** Every outbound fetch is guarded today —
           `skills/marketplace.py` and `tools/browser/client.py` both call one.
           Nothing requires a new caller to invoke either, and no gate enforces it.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert findings.contradicted_absences == []


def test_the_negation_still_binds_when_it_shares_the_sentence(gate):
    """Sentence scoping must not become no scoping."""
    text = _limitations(
        """
        1. **Gaps.** The browser tool has no SSRF guard at all (`tools/browser/client.py`).
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert len(findings.contradicted_absences) == 1
    assert "tools/browser/client.py" in findings.contradicted_absences[0]


def test_naming_the_guard_next_to_the_file_exonerates_it(gate):
    """ "the import pipeline calls `marketplace.py::_block_ssrf`" is not a claim
    that the guard is absent, whatever else the sentence says. This is the
    citation style the gate wants, so it must not be the style it punishes."""
    text = _limitations(
        """
        1. **Two divergent SSRF guards, and nothing makes a new caller use either.** The
           import pipeline calls `skills/marketplace.py::_block_ssrf` and the browser tool
           calls `tools/net_guard.py::validate_outbound_url`.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert findings.contradicted_absences == []


def test_citing_the_guards_own_module_is_not_naming_the_guard(gate):
    """Otherwise "`tools/net_guard.py` has no SSRF guard" exonerates itself,
    because the path text spells the symbol. The evidence has to be prose."""
    text = _limitations(
        """
        1. **Gaps.** There is no SSRF guard in `tools/net_guard.py` at all.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert len(findings.contradicted_absences) == 1
    assert "tools/net_guard.py" in findings.contradicted_absences[0]


def test_an_unseeded_control_class_is_not_guessed_at(gate):
    """`_ABSENCE_CLAIMS` is the whole vocabulary. A fuzzy English-to-symbol
    match would produce findings nobody could act on."""
    text = _limitations(
        """
        1. **No rate limiting.** `security/sentinel/validator.py` applies no rate limit.
        """
    )
    findings = gate.Findings()
    gate.check_absence_claims(text, findings)

    assert findings.contradicted_absences == []


# --------------------------------------------------------------------------
# Failure 2: a number written into a security document without counting
# --------------------------------------------------------------------------


def test_a_tagged_count_that_disagrees_with_the_code_fails(gate, monkeypatch):
    monkeypatch.setitem(gate.__dict__, "_http_client_modules", lambda: 25)
    monkeypatch.setitem(gate.__dict__, "_ssrf_guard_call_sites", lambda: 3)

    text = _limitations(
        """
        1. **SSRF coverage.** Measured (`measured-outbound-http`) — **11** modules import an
           HTTP client and **3** call sites invoke a guard.
        """
    )
    findings = gate.Findings()
    gate.check_counted_claims(text, findings)

    assert len(findings.drifted_counts) == 1
    assert "(11, 3)" in findings.drifted_counts[0]
    assert "(25, 3)" in findings.drifted_counts[0]


def test_a_tagged_count_that_matches_the_code_passes(gate, monkeypatch):
    monkeypatch.setitem(gate.__dict__, "_http_client_modules", lambda: 25)
    monkeypatch.setitem(gate.__dict__, "_ssrf_guard_call_sites", lambda: 3)

    text = _limitations(
        """
        1. **SSRF coverage.** Measured (`measured-outbound-http`) — **25** modules import an
           HTTP client and **3** call sites invoke a guard.
        """
    )
    findings = gate.Findings()
    gate.check_counted_claims(text, findings)

    assert findings.drifted_counts == []


def test_deleting_the_marker_fails_rather_than_silently_unchecking(gate):
    """Otherwise the cheapest way to fix a wrong number is to stop checking it,
    which is the failure mode a ratchet exists to prevent."""
    findings = gate.Findings()
    gate.check_counted_claims(_limitations("1. **SSRF coverage.** It is fine.\n"), findings)

    assert len(findings.drifted_counts) == 1
    assert "marker is gone" in findings.drifted_counts[0]


def test_an_untagged_number_is_left_alone(gate):
    """Bold is the marking. Without a tag the gate has no query to run, and
    guessing would be the laundering it exists to stop."""
    findings = gate.Findings()
    gate.check_counted_claims(
        _limitations("1. **Scope.** **Eleven** of **25** surfaces, tagged nowhere.\n"),
        findings,
    )

    assert [f for f in findings.drifted_counts if "marker is gone" not in f] == []


def test_guard_call_sites_are_counted_as_calls_not_as_text(gate):
    """A grep matches the two `def` lines and every docstring mention, which is
    how a document ends up claiming more coverage than exists."""
    assert gate._ssrf_guard_call_sites() == 3


def test_the_http_client_census_finds_the_modules_that_open_connections(gate):
    """A census that returned zero would make every count trivially checkable
    and completely uninformative."""
    assert gate._http_client_modules() > 20


# --------------------------------------------------------------------------
# Failure 3: a drifted inventory citation
# --------------------------------------------------------------------------


def test_a_drifted_value_fails(gate):
    text = _inventory(
        "| Pattern timeout | 99 s | `security/warden/detector.py` (`_PATTERN_TIMEOUT_S`) | — |"
    )
    findings = gate.Findings()
    gate.check_inventory(text, findings)

    assert findings.drifted_values, "a value the code contradicts must fail"
    assert "_PATTERN_TIMEOUT_S" in findings.drifted_values[0]


def test_a_constant_that_no_longer_exists_fails(gate):
    text = _inventory(
        "| Pattern timeout | 5 s | `security/warden/detector.py` (`_RENAMED_AWAY`) | — |"
    )
    findings = gate.Findings()
    gate.check_inventory(text, findings)

    assert findings.missing_constants == ["security/warden/detector.py: _RENAMED_AWAY"]


def test_a_line_number_citation_fails(gate):
    """`detector.py:27` rots the moment anything above line 27 moves, silently.
    Two rows had already drifted that way before the gate existed."""
    text = _inventory(
        "| Pattern timeout | 5 s | `security/warden/detector.py:27` (`_PATTERN_TIMEOUT_S`) | — |"
    )
    findings = gate.Findings()
    gate.check_inventory(text, findings)

    assert findings.line_citations == ["security/warden/detector.py:27"]


def test_a_symbol_citation_is_not_mistaken_for_a_line_citation(gate):
    """`file.py::name` is the style the gate is enforcing; flagging it would
    reject the fix."""
    assert gate._CITATION.findall("`skills/parser.py::security_scan`") == [("skills/parser.py", "")]


def test_symbol_citations_are_path_checked_too(gate):
    """The line-only pattern skipped `file.py::name` entirely, so those paths
    were never verified to exist at all."""
    findings = gate.Findings()
    gate.check_paths("`skills/does_not_exist.py::security_scan`", findings)

    assert findings.unresolved_paths == ["skills/does_not_exist.py"]


# --------------------------------------------------------------------------
# Paths, and the document as it actually ships
# --------------------------------------------------------------------------


def test_a_renamed_file_is_caught(gate):
    findings = gate.Findings()
    gate.check_paths("prose citing `security/warden/detector_renamed.py` here", findings)

    assert findings.unresolved_paths == ["security/warden/detector_renamed.py"]


def test_a_bare_filename_resolves_recursively(gate):
    """SECURITY.md writes "Warden (`detector.py`, `heuristics.py`)" — the
    sentence supplies the directory, so a bare name must not be a failure."""
    findings = gate.Findings()
    gate.check_paths("Warden (`detector.py`, `heuristics.py`)", findings)

    assert findings.unresolved_paths == []


def test_the_shipped_document_passes(gate):
    """The gate is only worth wiring into CI if the document it guards is
    currently in the state it demands."""
    assert gate.main() == 0
