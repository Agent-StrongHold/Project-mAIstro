"""Tests for the owned-store access gate (#312).

The gate exists because an unscoped store read is invisible on inspection: it
does the right thing to the wrong person's rows. So the tests are about what
the gate can and cannot see — a substring search for `chat_sessions` would
also flag a comment, a docstring and an unrelated local, and a gate that cries
wolf gets an `ALLOWED` entry rather than a fix.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-owned-store-access.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_owned_store_access", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestItFindsTheAccessThatMatters:
    def test_a_plain_read_is_reported_with_its_line(self, gate) -> None:
        source = "import stores\n\n\ndef handler():\n    return stores.chat_sessions.values()\n"

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == [(5, "chat_sessions")]

    def test_a_write_counts_too(self, gate) -> None:
        """Assignment is the more damaging half: it can overwrite another
        user's row, not merely read it."""
        source = "import stores\nstores.chat_sessions['x'] = row\n"

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == [(2, "chat_sessions")]

    def test_every_occurrence_is_listed_not_just_the_first(self, gate) -> None:
        """One report per module would let the second and third leak through a
        fix that addressed only the line the gate named."""
        source = (
            "import stores\na = stores.chat_sessions.get(k)\nb = stores.chat_sessions.values()\n"
        )

        assert [line for line, _ in gate.direct_accesses(source, frozenset({"chat_sessions"}))] == [
            2,
            3,
        ]

    def test_passing_the_raw_store_into_the_view_still_counts(self, gate) -> None:
        """The construction is where the raw store escapes. Allowing it because
        an `OwnedStore` appears on the same line is how the seam gets bypassed
        one caller at a time — the binding lives in `owned_records` instead."""
        source = "OwnedStore(stores.chat_sessions, owner)\n"

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == [(1, "chat_sessions")]


class TestItDoesNotCryWolf:
    def test_a_store_that_is_not_declared_owned_is_ignored(self, gate) -> None:
        source = "stores.missions.values()\n"

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == []

    def test_the_name_in_a_comment_or_string_is_not_an_access(self, gate) -> None:
        """A substring search would flag this module's own docstring, and the
        first false positive is what teaches people to reach for `ALLOWED`."""
        source = (
            '"""Explains stores.chat_sessions."""\n# stores.chat_sessions\nx = "chat_sessions"\n'
        )

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == []

    def test_the_same_attribute_on_something_else_is_not_an_access(self, gate) -> None:
        """`self.chat_sessions` on a store wrapper, or another module's
        attribute of the same name, is not the global dictionary."""
        source = "self.chat_sessions\nother.chat_sessions\n"

        assert gate.direct_accesses(source, frozenset({"chat_sessions"})) == []


class TestTheDeclarationsAreHonest:
    def test_the_repository_passes_its_own_gate(self, gate) -> None:
        assert gate.audit() == []

    def test_every_allowed_path_exists(self, gate) -> None:
        """A path that no longer exists is a permanent exemption for a file
        nobody can find, and it silently covers whatever takes its name next."""
        for path, _reason in gate.ALLOWED:
            assert (gate.BACKEND / path).is_file(), path

    def test_every_allowed_path_gives_a_reason(self, gate) -> None:
        for path, reason in gate.ALLOWED:
            assert reason.strip(), path

    def test_the_declared_stores_exist_on_the_stores_module(self, gate) -> None:
        """`OWNED_STORES` naming a store that was renamed away would report
        `ok` while governing nothing."""
        source = (gate.BACKEND / "stores.py").read_text(encoding="utf-8")

        for name in gate.OWNED_STORES:
            assert f"\n{name}: ModelStore" in source or f"\n{name}: JsonStore" in source, name

    def test_tests_may_reach_the_store_directly(self, gate) -> None:
        """A two-user test has to plant one user's row so the other can fail to
        read it, which means reaching past the scoped view on purpose."""
        assert gate._is_test(Path("tests/test_chat_session_ownership.py"))
        assert not gate._is_test(Path("routes/chat.py"))
