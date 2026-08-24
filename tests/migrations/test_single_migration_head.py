"""The migration chain must have exactly one head (#182).

Two branches that each add a revision with the same `down_revision` produce a
*branched* history. Alembic does not merge them for you: `upgrade head` fails
with "Multiple head revisions are present", and it fails on every deployment at
once, after both PRs have already merged and looked fine in isolation.

That is the shape this repository has already been bitten by for ADR ids — the
`adr` skill froze sequential numbering precisely because "two PRs open at once
both grab the next number" is not hypothetical here (PR #156/#157 both took
`ADR-100`). Migrations have the same race and a worse failure: the ADR collision
is a duplicate id, this one stops the database from being migrated at all.

So it is checked rather than remembered. This needs no server and no
`MAISTRO_TEST_DATABASE_URL`: it reads the revision graph off the files.

When it fails, the fix is not to delete a revision. Pick the one that should run
second and point its `down_revision` at the other, so the chain is linear again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "alembic" / "versions"


def _declared_revisions() -> list[tuple[Path, str]]:
    """Every revision id declared on disk, read from the file that declares it.

    Not from the filename. `004_task_run_id.py` declares `004_task_run_id`
    while its stem's first underscore-delimited field is `004` — a *different*
    revision, in a *different* file. Deriving the id from the name therefore
    resolved two files to one revision and would have let the stranded one pass
    unnoticed, which is the exact defect the caller is checking for.
    """
    pattern = re.compile(r"^revision\s*[:=]", re.MULTILINE)
    found = []
    for path in sorted(VERSIONS.glob("*.py")):
        if path.name.startswith("__"):
            continue
        for line in path.read_text().splitlines():
            if pattern.match(line):
                found.append((path, line.split("=", 1)[1].strip().strip("\"'")))
                break
        else:  # pragma: no cover - a versions file with no revision id
            raise AssertionError(f"{path.name} declares no revision id")
    return found


@pytest.fixture(scope="module")
def script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_there_is_exactly_one_head(script_directory):
    heads = script_directory.get_heads()
    assert len(heads) == 1, (
        f"the migration chain has branched into {len(heads)} heads: {sorted(heads)}. "
        "Two revisions share a down_revision — point the one that should run "
        "second at the other so the chain is linear again."
    )


def test_every_revision_is_reachable_from_the_head(script_directory):
    """A revision nothing points at is a file that will never run — the quiet
    half of the same defect, where the chain is linear but incomplete."""
    head = script_directory.get_current_head()
    walked = {revision.revision for revision in script_directory.walk_revisions("base", head)}
    on_disk = {revision for _path, revision in _declared_revisions()}

    assert on_disk <= walked, f"revisions off the chain: {sorted(on_disk - walked)}"


def test_the_guard_is_not_vacuous(script_directory):
    """A repository with no migrations would pass both tests above without
    checking anything."""
    assert len(list(script_directory.walk_revisions())) >= 4
