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
    monkeypatch.setitem(gate.__dict__, "_outbound_fetch_modules", lambda: 25)
    monkeypatch.setitem(gate.__dict__, "_guarded_fetch_modules", lambda: 3)

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
    monkeypatch.setitem(gate.__dict__, "_outbound_fetch_modules", lambda: 25)
    monkeypatch.setitem(gate.__dict__, "_guarded_fetch_modules", lambda: 3)

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
    how a document ends up claiming more coverage than exists.

    Asserted as a property rather than as a literal. This test used to pin the
    number to `== 3`, which made it the same unmeasured figure the gate exists
    to catch: adding the async guard entry point moved the tree to 4 and the
    test failed for having been right. The invariant is that a *call* counts
    and a mention does not, and it holds at any total — `ssrf.py` defines all
    the guards and names each of them many times over in prose, so a
    text-matching census would score it highest of any module, while a
    call-counting one scores it zero.
    """
    census = dict(gate._outbound_fetch_census())
    guard_module = gate._CORE_SRC / "security" / "ssrf.py"

    assert gate._ssrf_guard_call_sites() > 0
    assert census.get(guard_module, 0) == 0
    assert gate._ssrf_guard_call_sites() == sum(census.values())


def test_the_outbound_fetch_census_finds_the_modules_that_open_connections(gate):
    """A census that returned zero would make every count trivially checkable
    and completely uninformative."""
    assert gate._outbound_fetch_modules() > 20


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


# --------------------------------------------------------------------------
# Review round: seven ways the gate could pass while the document was wrong.
# Five of them were holes in this gate itself, which is the failure mode a
# gate is least able to report on its own.
# --------------------------------------------------------------------------


class TestTheGateCannotPassWhileTheDocumentIsWrong:
    def test_a_falsehood_outside_known_limitations_is_still_caught(self, gate):
        """The first version read only `## Known Limitations` — and the same
        commit that corrected the limitation left the identical falsehood in the
        Stronghold gaps table, where the gate could not see it. A gate that
        chooses its scope by section heading is one heading away from being
        decorative."""
        text = (
            "### Gaps against Stronghold's inventory\n\n"
            "| Stronghold had | Engine has | Status |\n"
            "| SSRF blocklist | no URL/host SSRF blocklist was found in "
            "`tools/browser/client.py` | `gap-impl` |\n"
        )
        findings = gate.Findings()
        gate.check_absence_claims(text, findings)

        assert len(findings.contradicted_absences) == 1
        assert "tools/browser/client.py" in findings.contradicted_absences[0]

    def test_an_accurate_clause_does_not_clear_a_false_one(self, gate):
        """A sentence can make two claims at once. Skipping the whole sentence
        let the correctly-named browser guard exonerate the false marketplace
        claim before either path was inspected."""
        text = _limitations(
            """
            1. **Gaps.** `skills/marketplace.py` has no SSRF guard, while
               `tools/browser/client.py` calls `validate_outbound_url`.
            """
        )
        findings = gate.Findings()
        gate.check_absence_claims(text, findings)

        named = " ".join(findings.contradicted_absences)
        assert "skills/marketplace.py" in named
        assert "tools/browser/client.py" not in named

    def test_a_row_that_checks_nothing_fails(self, gate):
        """`_CONSTANT` matched only a bare identifier, so five of sixteen rows
        extracted no name — and a row that compares nothing still counted toward
        "16 inventory rows match the code"."""
        text = _inventory("| Something | 5 s | `security/warden/detector.py` (prose only) | — |")
        findings = gate.Findings()
        gate.check_inventory(text, findings)

        assert len(findings.unchecked_rows) == 1
        assert "cites no symbol" in findings.unchecked_rows[0]

    @pytest.mark.parametrize(
        ("citation", "name"),
        [
            ("`window_size = 50 * 1024`", "window_size"),
            ("`max_results: int = 10`", "max_results"),
            ("`self._window`", "_window"),
            ("`MAX_LEARNINGS`", "MAX_LEARNINGS"),
        ],
    )
    def test_every_cited_symbol_form_is_parsed(self, gate, citation: str, name: str):
        """All four forms appear in the shipped inventory and all four cite a
        real binding. The scan window, both learning-store defaults and both
        rate-limiter windows were the values not being checked, which is most of
        what a resource-limits inventory is for."""
        assert name in gate._CONSTANT.findall(citation)

    def test_a_scaled_value_is_only_admitted_for_a_binary_cell(self, gate):
        """Offering the scaled form unconditionally made every row accept two
        values, and the second was occasionally a real regression: a `0.5 s`
        timeout that drifted to `512` would have passed, because 0.5 * 1024 is
        512. A gate that accepts a thousandfold change in a security timeout is
        worse than no gate on that row."""
        assert 512.0 not in gate._documented_numbers("0.5 s")
        assert 51200.0 in gate._documented_numbers("50 KiB")

    @pytest.mark.parametrize(
        "citation",
        [
            "`packages/hive-conductor/backend/tests/test_auth_password_storage.py`",
            "`check-security-inventory.py`",
            "`security/patterns.py:BLOCKED_HOST_PATHS`",
        ],
    )
    def test_the_citation_forms_the_document_already_uses_are_matched(self, gate, citation: str):
        """Four cited paths went unchecked in the first version — hyphens were
        excluded from the path class and the single-colon symbol form matched
        neither alternative. Renaming any of those files would have left
        `check_paths` green, which is the one thing it exists to prevent."""
        assert gate._CITATION.findall(citation), f"{citation} is not recognised as a citation"

    def test_the_two_counted_figures_come_from_one_census(self, gate):
        """The first version compared modules importing an HTTP client against
        guard *call sites*, and those sets turned out to be disjoint: all three
        guarded modules fetch through an injected client or a browser. The ratio
        looked like coverage and measured nothing."""
        census = {path for path, _calls in gate._outbound_fetch_census()}
        guarded = {path for path, calls in gate._outbound_fetch_census() if calls}

        assert guarded, "a census with no guarded member cannot measure coverage"
        assert guarded <= census, "the numerator must be drawn from the denominator"
        assert gate._guarded_fetch_modules() == len(guarded)
        assert gate._outbound_fetch_modules() == len(census)

    def test_a_module_fetching_through_an_injected_client_is_in_the_census(self, gate):
        """`skills/marketplace.py` imports no HTTP library at all — it takes an
        `HTTPClient` protocol. Missing it is what made the two figures disjoint."""
        census = {path.name for path, _calls in gate._outbound_fetch_census()}

        assert {"marketplace.py", "import_pipeline.py", "client.py"} <= census
