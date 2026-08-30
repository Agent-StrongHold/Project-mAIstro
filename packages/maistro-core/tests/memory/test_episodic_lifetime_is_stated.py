"""No document claims a durability episodic memory does not have (#710).

Two false-or-absent statements were part of how this went unnoticed for as long
as it did. Migration 011's docstring listed `episodic_memories` among "the
tables `maistro.memory` actually reads and writes" -- untrue when written -- and
`InMemoryEpisodicStore` said nothing at all about its lifetime, so a reader had
to infer from the class name that the container wired it on every backend.

The scan is over the real files rather than a copy: a test asserting on a
transcribed docstring proves nothing about the docstring that ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.memory.episodic import store as episodic_store

pytestmark = [pytest.mark.contract("behavioral")]

_REPO = Path(__file__).resolve().parents[4]
_MIGRATIONS = _REPO / "alembic" / "versions"


class TestThePersistenceClaimsAreTrue:
    @pytest.mark.ac("SPEC-083026-ba26/AC-8")
    def test_the_in_memory_store_states_its_lifetime(self) -> None:
        doc = episodic_store.InMemoryEpisodicStore.__doc__ or ""

        assert "process" in doc.lower()
        assert "maistro.persistence.pg_episodic" in doc

    @pytest.mark.ac("SPEC-083026-ba26/AC-8")
    def test_no_migration_says_maistro_memory_reads_the_episodic_table(self) -> None:
        """The claim, not the table name: `episodic_memories` appears in four
        migrations that legitimately maintain it. What must not appear is a
        sentence asserting the code reads and writes it while presenting that as
        current fact."""
        offenders = [
            path.name
            for path in sorted(_MIGRATIONS.glob("*.py"))
            if _claims_the_code_reads_it(path.read_text())
        ]
        assert offenders == []

    def test_the_scan_has_a_corpus(self) -> None:
        """A guard that reads no files guards nothing."""
        assert len(list(_MIGRATIONS.glob("*.py"))) > 10


def _claims_the_code_reads_it(text: str) -> bool:
    """Whether `text` asserts, as present fact, that the memory code uses the table.

    The correction migration 011 now carries *quotes* the old sentence to
    explain why it was wrong, so a substring scan would flag the explanation of
    the fix. The paragraph that does so opens with "(This paragraph used to" --
    anything inside those parentheses is history, not a claim.
    """
    claim = "the tables `maistro.memory` actually reads and writes"
    return any(
        claim in paragraph and "used to" not in paragraph for paragraph in text.split("\n\n")
    )
