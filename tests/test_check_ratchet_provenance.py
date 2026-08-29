"""The inventory that stops the next ratchet being written the old way (#542).

`ratchet_provenance.py` fixed the ratchets that were converted. Nothing stopped
a new one arriving candidate-authored — and seven did, between #542 being filed
against 13 such scripts and this gate finding 21.

The rules are asserted against synthetic trees in `tmp_path`, not against the
repository's own 21 scripts. Asserting over the real corpus would restate
today's inventory and go red as unrelated gates changed; what is under test is
what the *rules* do.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "scripts" / "check_ratchet_provenance_impl.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_ratchet_provenance_impl", IMPL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _script(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


#: A gate that reads its ledger straight out of the tree being judged.
_CANDIDATE_READ = (
    "from pathlib import Path\n"
    "ROOT = Path(__file__).resolve().parents[1]\n"
    'BASELINE = ROOT / "quality" / "thing-baseline.json"\n'
)

#: The same gate, converted.
_BASE_READ = (
    "from pathlib import Path\n"
    "import ratchet_provenance.py_stub  # noqa\n"
    "ROOT = Path(__file__).resolve().parents[1]\n"
    'BASELINE = ROOT / "quality" / "thing-baseline.json"\n'
    "def go(prov):\n"
    "    return prov.resolve_baseline(BASELINE)\n"
)


class TestWhatCountsAsReadingALedger:
    def test_a_path_expression_is_a_use(self, check, tmp_path) -> None:
        _script(tmp_path, "check-thing.py", _CANDIDATE_READ)

        (use,) = check.survey(tmp_path)

        assert use.script == "check-thing.py"
        assert use.ledgers == ("thing-baseline.json",)
        assert use.base_resolved is False

    def test_prose_about_a_ledger_is_not_a_use(self, check, tmp_path) -> None:
        """Half the `quality/` mentions under `scripts/` are docstrings. A
        textual gate would have to allowlist its way out of that, which is how
        a gate ends up measuring its own allowlist."""
        _script(
            tmp_path,
            "check-thing.py",
            '"""Compares against quality/thing-baseline.json, someday."""\n'
            "# see quality/other-baseline.json\n"
            'MESSAGE = "write quality/third-baseline.json"\n',
        )

        assert check.survey(tmp_path) == []

    def test_a_directory_of_ledgers_is_a_use(self, check, tmp_path) -> None:
        """`ac_state_notes.py` folds its bound from a directory, not a file."""
        _script(
            tmp_path,
            "notes.py",
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[1]\n"
            'NOTES = ROOT / "quality" / "thing-notes"\n',
        )

        (use,) = check.survey(tmp_path)

        assert use.ledgers == ("thing-notes",)

    def test_a_ledger_named_by_variable_still_counts_as_a_use(self, check, tmp_path) -> None:
        """The directory is the fact this gate is about. A name assembled at
        runtime must not read as "touches no ledger", which would be the one
        spelling that escapes the inventory entirely."""
        _script(
            tmp_path,
            "check-thing.py",
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[1]\n"
            "def ledger(name):\n"
            '    return ROOT / "quality" / name\n',
        )

        assert [use.script for use in check.survey(tmp_path)] == ["check-thing.py"]


class TestWhatCountsAsConverted:
    def test_resolving_through_the_helper_is_converted(self, check, tmp_path) -> None:
        _script(tmp_path, "check-thing.py", _BASE_READ)

        (use,) = check.survey(tmp_path)

        assert use.base_resolved is True

    def test_naming_the_helper_without_resolving_is_not(self, check, tmp_path) -> None:
        """A script that loads the helper for `Provenance.render` alone emits a
        provenance report over a candidate-read ledger. It looks converted in a
        diff and in the build log, and is not."""
        _script(
            tmp_path,
            "check-thing.py",
            _CANDIDATE_READ + "import ratchet_provenance.py_stub  # noqa\n"
            "def report(prov, baseline):\n"
            "    return prov.Provenance(baseline=baseline).render()\n",
        )

        (use,) = check.survey(tmp_path)

        assert use.base_resolved is False

    def test_the_helper_itself_reads_as_converted(self, check, tmp_path) -> None:
        """It defines the resolvers and calls one; it cannot name itself. A
        rule that required the filename would have put the helper on the
        unconverted list — false, and the kind of finding that gets an
        inventory row instead of a fix."""
        _script(
            tmp_path,
            "ratchet_provenance.py",
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[1]\n"
            'AUTHORIZATIONS = ROOT / "quality" / "ratchet-authorizations.json"\n'
            "def load_authorizations():\n"
            "    return resolve_baseline(AUTHORIZATIONS)\n"
            "def resolve_baseline(path):\n"
            "    return path\n",
        )

        (use,) = check.survey(tmp_path)

        assert use.base_resolved is True


def _entry(**over) -> dict[str, object]:
    base = {
        "decision": "CONVERT_PENDING",
        "owner": "#542",
        "reason": "x" * 60,
    }
    base.update(over)
    return base


class TestTheInventoryRules:
    def _audit(self, check, uses, recorded, trusted=None, authorized=None, seeded=False):
        return check.audit(
            uses,
            recorded,
            {} if trusted is None else trusted,
            {} if authorized is None else authorized,
            seeded=seeded,
        )

    def _use(self, check, name="check-thing.py", *, converted=False):
        return check.LedgerUse(script=name, ledgers=("thing.json",), base_resolved=converted)

    def test_an_unrecorded_candidate_read_fails(self, check) -> None:
        failures = self._audit(check, [self._use(check)], {})

        assert len(failures) == 1
        assert "no recorded decision" in failures[0]

    def test_a_recorded_candidate_read_passes_when_it_was_already_recorded(self, check) -> None:
        entry = _entry()

        assert (
            self._audit(
                check,
                [self._use(check)],
                {"check-thing.py": entry},
                trusted={"check-thing.py": entry},
            )
            == []
        )

    def test_a_newly_excused_script_needs_a_grant(self, check) -> None:
        """The gate's own rule, applied to itself: the base did not carry this
        row, so recording it on the branch is the candidate excusing itself."""
        failures = self._audit(check, [self._use(check)], {"check-thing.py": _entry()})

        assert any("newly excused" in f for f in failures)

    def test_a_grant_read_from_the_base_permits_it(self, check) -> None:
        failures = self._audit(
            check,
            [self._use(check)],
            {"check-thing.py": _entry()},
            authorized={"check-thing.py": "#542 -- owner: reason"},
        )

        assert failures == []

    def test_seeding_needs_no_grant(self, check) -> None:
        """Rows recording scripts that already read their ledger this way write
        the debt down; they do not create it. And grants are themselves read at
        the base, so a seed that demanded one could never be introduced."""
        assert (
            self._audit(check, [self._use(check)], {"check-thing.py": _entry()}, seeded=True) == []
        )

    def test_a_converted_script_must_be_pruned(self, check) -> None:
        """The list may only shrink. A stale row is slack the next unconverted
        ratchet slides into under someone else's name."""
        failures = self._audit(
            check, [self._use(check, converted=True)], {"check-thing.py": _entry()}
        )

        assert any("prune the inventory row" in f for f in failures)

    def test_a_row_for_a_script_that_reads_nothing_is_stale(self, check) -> None:
        failures = self._audit(check, [], {"gone.py": _entry()})

        assert any("reads no quality/ ledger" in f for f in failures)

    @pytest.mark.parametrize(
        "entry,fragment",
        [
            (_entry(decision="MAYBE"), "is not one of"),
            (_entry(owner=""), "requires a non-empty 'owner'"),
            (_entry(decision="CANDIDATE_AUTHORED", safeguard=""), "non-empty 'safeguard'"),
            (_entry(reason="too short"), "too vague"),
        ],
    )
    def test_a_malformed_row_fails(self, check, entry, fragment) -> None:
        failures = self._audit(
            check, [self._use(check)], {"check-thing.py": entry}, trusted={"check-thing.py": entry}
        )

        assert any(fragment in f for f in failures), failures

    def test_not_a_ratchet_needs_no_supporting_field(self, check) -> None:
        """It is an answer, not a deferral: the reason carries the whole claim."""
        entry = {"decision": "NOT_A_RATCHET", "reason": "y" * 60}

        assert (
            self._audit(
                check,
                [self._use(check)],
                {"check-thing.py": entry},
                trusted={"check-thing.py": entry},
            )
            == []
        )


class TestTheCommittedInventory:
    def test_every_recorded_script_still_reads_a_ledger(self, check) -> None:
        """Against the real tree, because this is the claim the file makes."""
        recorded = check.load_inventory()
        reading = {use.script for use in check.survey()}

        assert set(recorded) <= reading, sorted(set(recorded) - reading)

    def test_no_recorded_script_has_been_converted(self, check) -> None:
        converted = {use.script for use in check.survey() if use.base_resolved}

        assert not (set(check.load_inventory()) & converted)

    def test_every_candidate_read_is_recorded(self, check) -> None:
        recorded = set(check.load_inventory())
        unconverted = {use.script for use in check.survey() if not use.base_resolved}

        assert unconverted == recorded, sorted(unconverted ^ recorded)

    def test_every_row_is_well_formed(self, check) -> None:
        failures = [
            f
            for script, entry in check.load_inventory().items()
            for f in check._entry_failures(script, entry)
        ]

        assert failures == []
