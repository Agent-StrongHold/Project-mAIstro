"""A design project's scope is a soft axis, not a reference (#326, ADR-083026-cdcb).

003 declared `design_projects.org_id` and `team_id` as foreign keys to `orgs`
and `teams`, tables no migration created. #177's repair created them inside 003
so the chain would apply. It did — and then nothing populated them, so on a
database freshly migrated to head the only `org_id` the Design Studio supplies
was rejected:

    ERROR:  insert or update on table "design_projects" violates foreign key
            constraint "design_projects_org_id_fkey"
    DETAIL:  Key (org_id)=(default-org) is not present in table "orgs".

"Cannot migrate" had become "migrates, but the product cannot write."

`org` and `team` are scope axes (ADR-068), and every other table in this schema
already treats them that way: `learnings`, `episodes` and `outcomes` in 001 and
the three canvas tables in 002 all declare `org_id` as plain text with a `''`
default and no key. `design_projects` was the exception. This drops the two
constraints and the two tables with them — leaving two empty tables standing is
an invitation for the next migration to reference them again.

The `CHECK` that replaces the keys asks a question the product can answer: did
the caller name a scope. The old one asked whether the scope was a row in a
table nothing writes, which refused every value rather than the wrong ones.

Revision ID: 024
Revises: 023
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF EXISTS on both: a database provisioned before #177's repair may have
    # had these created by hand under a different name, or not at all.
    op.execute("ALTER TABLE design_projects DROP CONSTRAINT IF EXISTS design_projects_org_id_fkey")
    op.execute("ALTER TABLE design_projects DROP CONSTRAINT IF EXISTS design_projects_team_id_fkey")

    # A scope-less project is still refused, by something a caller can satisfy.
    # `team_id` stays nullable and unchecked: a project need not have a team.
    op.execute(
        "ALTER TABLE design_projects "
        "ADD CONSTRAINT design_projects_org_id_not_blank CHECK (org_id <> '')"
    )

    # One spelling for "no team". `team_id` is nullable, so `NULL` already means
    # it; `''` meant the same thing and nothing rejected it, which left two
    # spellings of one fact. That is not cosmetic: the downgrade below has to
    # give every non-null `team_id` an anchor row before it can restore the
    # foreign key, and `''` is a value no sensible anchor row can carry — so a
    # single such project made the rollback abort (Codex, #326).
    op.execute("UPDATE design_projects SET team_id = NULL WHERE team_id = ''")

    # The placeholder anchors. Any row in them was written by hand to get past
    # the original failure -- no production path ever inserted one -- and
    # dropping them loses nothing a design project holds: `org_id` is a text
    # column and keeps its value.
    #
    # `teams` first: `teams.org_id` references `orgs.id`.
    op.execute("DROP TABLE IF EXISTS teams")
    op.execute("DROP TABLE IF EXISTS orgs")


def downgrade() -> None:
    """Restore the tables and the keys, backfilling anchors for existing rows.

    The backfill is what makes this reversible at all. Re-adding a foreign key
    over rows whose `org_id` names nothing fails, and every row in a database
    that reached this revision has exactly such an `org_id` -- so a downgrade
    that only recreated the tables would abort partway, which is why the old
    shape could not be round-tripped and so was never tested.
    """
    op.execute(
        "CREATE TABLE IF NOT EXISTS orgs (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '')"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS teams ("
        "id TEXT PRIMARY KEY, "
        "org_id TEXT REFERENCES orgs(id) ON DELETE CASCADE, "
        "name TEXT NOT NULL DEFAULT '')"
    )

    # Rows written between 024 and this rollback can carry `''` again -- the
    # column has no constraint against it, only the upgrade's one-time
    # normalization. Same reason, same fix, before the backfill reads it.
    op.execute("UPDATE design_projects SET team_id = NULL WHERE team_id = ''")

    op.execute(
        "INSERT INTO orgs (id, name) "
        "SELECT DISTINCT org_id, org_id FROM design_projects "
        "WHERE org_id <> '' ON CONFLICT (id) DO NOTHING"
    )
    # A team row needs an org row to point at, so its org comes from the same
    # project. Distinct on the pair: two orgs must not race for one team id.
    op.execute(
        "INSERT INTO teams (id, org_id, name) "
        "SELECT DISTINCT ON (team_id) team_id, org_id, team_id FROM design_projects "
        "WHERE team_id IS NOT NULL AND team_id <> '' ON CONFLICT (id) DO NOTHING"
    )

    op.execute(
        "ALTER TABLE design_projects DROP CONSTRAINT IF EXISTS design_projects_org_id_not_blank"
    )
    op.execute(
        "ALTER TABLE design_projects ADD CONSTRAINT design_projects_org_id_fkey "
        "FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE design_projects ADD CONSTRAINT design_projects_team_id_fkey "
        "FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL"
    )
