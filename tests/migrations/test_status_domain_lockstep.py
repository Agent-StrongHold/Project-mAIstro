"""The Run-spine status domains, the partial-index predicates, and the model
must move together (#863).

`canonical_runs.status`, `canonical_node_runs.status`, `canonical_attempts.status`
and `graph_continuations.status` were unconstrained `text` for the spine's whole
life, and every correctness-critical scan of them rides a partial index whose
predicate names constant statuses: `ix_canonical_runs_live` (012, `NOT IN` the
terminal set), `ix_canonical_runs_retention` (013, `IN` the terminal set),
`ix_canonical_runs_archive_candidates` (017, same). The failure mode of an
unconstrained status column is not an error — it is silence. Add
`RunStatus.RETIRED` to the model and:

- live Runs with that status keep being indexed by `ix_canonical_runs_live`
  (`NOT IN` covers newcomers) and so stay visible to recovery — but nothing
  else knows the status exists;
- a *terminal* addition is worse: it escapes the retention and archive
  predicates entirely, so every Run that reaches it stays in the table forever
  while every sweep reports an empty backlog. No error, no log line, just a
  table that grows.

Migration 054 closes the front door with CHECK constraints pinned to the model
enums — a status outside the domain cannot be *written*, so the gap between
"model" and "database" can only be closed by a migration, and that migration is
the one place the predicates get revised. This suite holds the pairing shut
with no server at all: it reads the revision files and the model in the same
process and refuses any drift. When it fails, the fix is a migration that
extends the domain (and revises 012/013/017's predicates in the same revision),
not a wider `IN` list pasted into the test.

The back door is held too: every `sa.Column("status", sa.Text)` in the chain
must belong either to the constrained spine set or to the enumerated non-spine
tables (memory, durable events, capability invocations), each of which carries
its own domain with its own owner. A new status-bearing table therefore has to
be *declared* here — added to one of the two sets, with a constraint if it is
spine — rather than silently joining the class of columns this issue is about.
"""

from __future__ import annotations

import re
from importlib import util as importlib_util
from pathlib import Path

import pytest

from maistro.runs.model import TERMINAL_RUN_STATUSES, AttemptStatus, RunStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "alembic" / "versions"

#: The four tables whose status column is the Run spine's — every one of them
#: is written through `PgRunStore`/`PgGraphContinuationStore` and scanned by
#: the retention sweep, the recovery scan or the queue cursor.
SPINE_TABLES = frozenset(
    {"canonical_runs", "canonical_node_runs", "canonical_attempts", "graph_continuations"}
)

#: Status-bearing tables that are *not* the Run spine, with the revision that
#: owns them. Each carries a domain with its own owner and its own migration;
#: the lockstep test refuses to guess at them, and refuses to let one pass
#: unexamined either.
NON_SPINE_STATUS_TABLES = frozenset(
    {
        ("001_initial_memory_schema", "memories"),
        ("001_initial_memory_schema", "memory_sessions"),
        ("004_durable_events", "durable_events"),
        ("004_durable_events", "handler_invocations"),
        ("035_capability_invocations", "capability_invocations"),
    }
)

RUN_DOMAIN = frozenset(status.value for status in RunStatus)
ATTEMPT_DOMAIN = frozenset(status.value for status in AttemptStatus)
TERMINAL_DOMAIN = frozenset(status.value for status in TERMINAL_RUN_STATUSES)


def _load_revision(stem: str):
    """Import an alembic revision by file stem, the way alembic itself does."""
    path = VERSIONS / f"{stem}.py"
    spec = importlib_util.spec_from_file_location(stem, path)
    assert spec is not None and spec.loader is not None, f"{path} is not importable"
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def revision_054():
    return _load_revision("058_run_store_planner_stability")


class TestMigrationDomainsMatchTheModel:
    def test_the_run_domain_is_the_model_enum(self, revision_054) -> None:
        """A migration cannot import the model — it must keep meaning what it
        meant on the day it ran — so the pairing is held by this test instead:
        if the enum grows, this file fails until a revision extends the DDL."""
        assert set(revision_054._RUN_STATUS_VALUES) == RUN_DOMAIN

    def test_the_attempt_domain_is_the_model_enum(self, revision_054) -> None:
        assert set(revision_054._ATTEMPT_STATUS_VALUES) == ATTEMPT_DOMAIN

    def test_the_check_constraints_pin_each_spine_table_to_its_domain(self, revision_054) -> None:
        """Both Run-status tables and the continuation table share the Run
        domain (continuations store a `RunStatus` — `pg_continuation` writes
        `status.value` straight from the model). Attempts have their own.
        The DDL strings must also follow the model's *declaration* order: the
        revision is hand-written to mirror the enum, and an exact comparison
        is what turns a reordered or half-copied domain into a failure."""
        assert [status.value for status in RunStatus] == list(revision_054._RUN_STATUS_VALUES)
        assert [status.value for status in AttemptStatus] == list(
            revision_054._ATTEMPT_STATUS_VALUES
        )
        assert (
            "status IN ({})".format(", ".join(f"'{status.value}'" for status in RunStatus))
            == revision_054._RUN_STATUS_CHECK
        )
        assert (
            "status IN ({})".format(", ".join(f"'{status.value}'" for status in AttemptStatus))
            == revision_054._ATTEMPT_STATUS_CHECK
        )
        source = (VERSIONS / "058_run_store_planner_stability.py").read_text(encoding="utf-8")
        # The constrained add rides 054's guarded helper (the adoption-safe
        # form the chain's re-application contract needs), so the spelling
        # this greps for is the helper call with the same constant the
        # assertions above pin to the model.
        for table in ("canonical_runs", "canonical_node_runs", "graph_continuations"):
            assert re.search(
                rf'_add_check_constraint_if_absent\(\s*"ck_{table}_status",\s*"{table}",\s*'
                rf"_RUN_STATUS_CHECK",
                source,
            ), f"{table} must be CHECK-constrained to the Run domain"
        assert re.search(
            r'_add_check_constraint_if_absent\(\s*"ck_canonical_attempts_status",\s*'
            r'"canonical_attempts",\s*_ATTEMPT_STATUS_CHECK',
            source,
        ), "canonical_attempts must be CHECK-constrained to the Attempt domain"


class TestPartialIndexPredicatesStayInsideTheDomain:
    """The indexes whose predicates name constant statuses must name a subset
    of the model's domain — and the terminal ones must name *exactly* the
    model's terminal set, or a new terminal status silently escapes the sweeps
    (the failure this issue exists to close)."""

    def test_the_retention_predicate_is_exactly_the_terminal_set(self) -> None:
        migration_013 = _load_revision("013_run_retention_deadline")
        assert set(re.findall(r"'([a-z_]+)'", migration_013._TERMINAL)) == TERMINAL_DOMAIN

    def test_the_archive_predicate_is_exactly_the_terminal_set(self) -> None:
        migration_017 = _load_revision("017_archive_cold_runs")
        assert set(re.findall(r"'([a-z_]+)'", migration_017._TERMINAL)) == TERMINAL_DOMAIN

    def test_the_live_predicate_excludes_exactly_the_terminal_set(self) -> None:
        """`NOT IN` covers future statuses automatically — that is what keeps
        recovery safe for free — but the excluded set itself must stay the
        terminal set: excluding anything terminal-but-unlisted would index a
        dead Run as live, and excluding a status the model calls terminal
        elsewhere would split the definition of "live" across two files."""
        source = (VERSIONS / "012_canonical_execution_spine.py").read_text(encoding="utf-8")
        match = re.search(r"status NOT IN \(([^)]*)\)", source)
        assert match is not None, "012's live index predicate is missing"
        assert set(re.findall(r"'([a-z_]+)'", match.group(1))) == TERMINAL_DOMAIN

    def test_the_store_derives_its_terminal_set_from_the_model(self) -> None:
        from maistro.runs.pg_store import _TERMINAL_RUN_STATUS_VALUES

        assert set(_TERMINAL_RUN_STATUS_VALUES) == TERMINAL_DOMAIN


class TestNoStatusColumnEscapesTheLedger:
    def test_every_text_status_column_in_the_chain_is_accounted_for(self) -> None:
        """The tripwire: any new `sa.Column("status", sa.Text)` in the chain
        must be spine (and therefore CHECK-constrained from migration 054 on)
        or declared non-spine here, with a domain and an owner of its own."""
        declared: dict[str, set[str]] = {}
        column = re.compile(r'sa\.Column\("status",\s*sa\.Text')
        table = re.compile(r'op\.create_table\(\s*\n\s*"([a-z_]+)"')
        for path in sorted(VERSIONS.glob("*.py")):
            if path.name.startswith("__"):
                continue
            source = path.read_text(encoding="utf-8")
            for match in table.finditer(source):
                declared.setdefault(match.group(1), set()).add(path.stem)
                # create_table bodies span to the next `op.` call; a status
                # column anywhere inside that span belongs to this table.
                span = source[match.end() : source.find("\n    op.", match.end())]
                if column.search(span):
                    declared[match.group(1)].add(f"{path.stem}:status")

        spine_with_status = set()
        non_spine_with_status = set()
        for name, revisions in declared.items():
            markers = {r for r in revisions if r.endswith(":status")}
            if not markers:
                continue
            (spine_with_status if name in SPINE_TABLES else non_spine_with_status).add(name)

        assert spine_with_status == set(SPINE_TABLES), (
            "spine tables with a text status column must be exactly the four "
            f"migration 054 constrains; got {sorted(spine_with_status)}"
        )
        accounted = {name for _, name in NON_SPINE_STATUS_TABLES}
        assert non_spine_with_status <= accounted, (
            f"unaccounted status-bearing tables {sorted(non_spine_with_status - accounted)}: "
            "declare them in NON_SPINE_STATUS_TABLES with an owner, or constrain them "
            "in a revision and add them to SPINE_TABLES"
        )
