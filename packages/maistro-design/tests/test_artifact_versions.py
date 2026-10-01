"""Versioned human+AI artifact state, locks, guidance, branch control (#780).

These drive the real `PgArtifactVersionStore` against SQLite file databases —
including closing and reopening one — because the acceptance criteria are about
what *survives*: prior versions, locks, guidance, and control state across a
refresh/reconnect or process restart.

SPEC-092826-a780 owns the acceptance criteria.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from maistro.observability.correlation import bind_execution_context
from maistro.runs.model import RunStatus
from maistro_design.trust import TrustTier
from maistro_design.types import ArtifactKind, ArtifactNode, DesignOutput, OutputFormat
from maistro_design.version_store import PgArtifactVersionStore
from maistro_design.versions import (
    ArtifactLockConflict,
    ArtifactVersion,
    ArtifactVersionError,
    ArtifactVersionExistsError,
    ArtifactVersionNotFoundError,
    ChangeKind,
    ChangeOrigin,
    ControlMode,
    CreativeArtifactService,
    LockStateError,
    VersionState,
)

ORG = "org-1"
PROJECT = "proj-1"

# The store binds TIMESTAMPTZ columns with real datetime objects (asyncpg
# requires them). SQLite has no native datetime, and Python 3.12 deprecated
# the default sqlite3 adapters, so the tests register an explicit one.
sqlite3.register_adapter(datetime, lambda value: value.astimezone(UTC).isoformat())

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS design_artifact_versions (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        kind TEXT NOT NULL,
        origin TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        format TEXT,
        content TEXT NOT NULL DEFAULT '',
        url TEXT,
        trust_tier TEXT NOT NULL DEFAULT 't3',
        state TEXT NOT NULL DEFAULT 'draft',
        parent_version INTEGER,
        fork_lineage_id TEXT,
        fork_version INTEGER,
        brief_ref TEXT,
        decision_inputs_json TEXT,
        author TEXT NOT NULL DEFAULT '',
        run_id TEXT,
        node_run_id TEXT,
        attempt_id TEXT,
        content_sha TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (project_id, lineage_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS design_artifact_locks (
        lock_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        version INTEGER,
        address TEXT,
        decision_ref TEXT,
        decision_digest TEXT,
        reason TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        released_at TEXT,
        released_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS design_project_guidance (
        guidance_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        lineage_id TEXT,
        text TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        run_id TEXT,
        created_at TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        superseded_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS design_branch_controls (
        control_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        run_id TEXT,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, lineage_id)
    )
    """,
)


def _open_store(
    db_path: Path,
    ddl: tuple[str, ...] = _DDL,
    connect: tuple[str, ...] = (),
    seed: tuple[str, ...] = (),
) -> PgArtifactVersionStore:
    """A store over one SQLite file, as a fresh process would open it.

    `connect` statements run before the DDL (e.g. `PRAGMA foreign_keys=ON`,
    which SQLite requires per connection); `ddl` replaces the default schema
    so a test can add constraints the shared fixture omits; `seed` rows land
    after the DDL (e.g. a parent project a foreign key points at).
    """
    engine = create_engine(f"sqlite:///{db_path}")
    connection = engine.connect()
    for statement in (*connect, *ddl, *seed):
        connection.execute(text(statement))
    connection.commit()

    class Session:
        async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
            return connection.execute(statement, params or {})

        async def commit(self) -> None:
            connection.commit()

    @asynccontextmanager
    async def factory() -> Any:
        yield Session()

    return PgArtifactVersionStore(session_factory=factory)


def _agent_output(content: str, **provenance: str) -> DesignOutput:
    return DesignOutput(
        root=ArtifactNode(
            key="root", kind=ArtifactKind.FILE, format=OutputFormat.HTML, value=content
        ),
        trust_tier=TrustTier.T3,
        **provenance,
    )


async def _generate(
    service: CreativeArtifactService,
    lineage: str,
    content: str,
    *,
    run_id: str = "run-1",
    **extra: Any,
) -> ArtifactVersion:
    with bind_execution_context(
        run_id=run_id, node_run_id=f"{run_id}-nr", attempt_id=f"{run_id}-a"
    ):
        return await service.record_generation(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id=lineage,
            output=_agent_output(content),
            **extra,
        )


async def _refine(
    service: CreativeArtifactService,
    lineage: str,
    content: str,
    *,
    run_id: str = "run-2",
    **extra: Any,
) -> ArtifactVersion:
    with bind_execution_context(
        run_id=run_id, node_run_id=f"{run_id}-nr", attempt_id=f"{run_id}-a"
    ):
        return await service.record_refinement(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id=lineage,
            output=_agent_output(content),
            **extra,
        )


class TestOneArtifactThreeVersionsWithProvenance:
    """AC-1: AI generates, a person edits, an agent resumes — all inspectable."""

    @pytest.mark.ac("SPEC-092826-a780/AC-1")
    @pytest.mark.contract("behavioral")
    async def test_the_three_versions_remain_inspectable_with_correct_provenance(
        self, tmp_path: Path
    ) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))

        v1 = await _generate(service, "poster", "<main>v1</main>")
        v2 = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2 human</main>",
        )
        v3 = await _refine(service, "poster", "<main>v3 refined</main>", run_id="run-3")

        history = await service.versions(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert [(v.lineage_id, v.version) for v in history] == [
            ("poster", 1),
            ("poster", 2),
            ("poster", 3),
        ]
        assert (v1.parent_version, v2.parent_version, v3.parent_version) == (None, 1, 2)

        # Agent versions name their canonical producer and no human author.
        assert (v1.run_id, v1.node_run_id, v1.attempt_id) == ("run-1", "run-1-nr", "run-1-a")
        assert (v3.run_id, v3.node_run_id, v3.attempt_id) == ("run-3", "run-3-nr", "run-3-a")
        assert v1.author == "" and v3.author == ""
        assert v1.kind is ChangeKind.GENERATION and v3.kind is ChangeKind.REFINEMENT

        # The human edit names the person — never a run pretending to be them.
        assert v2.origin is ChangeOrigin.HUMAN and v2.author == "user-9"
        assert (v2.run_id, v2.node_run_id, v2.attempt_id) == ("", "", "")

        assert (await service.tip(org_id=ORG, project_id=PROJECT, lineage_id="poster")) == v3


class TestLockingAnAcceptedArtifact:
    """AC-2: a locked accepted version refuses autonomous replacement."""

    @pytest.mark.ac("SPEC-092826-a780/AC-2")
    @pytest.mark.contract("behavioral")
    async def test_locked_version_refuses_refinement_but_not_unrelated_branches(
        self, tmp_path: Path
    ) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>accepted</main>")
        await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1)
        lock = await service.lock_version(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            version=1,
            created_by="user-9",
            reason="approved copy",
        )

        with pytest.raises(ArtifactLockConflict) as conflict:
            await _refine(service, "poster", "<main>replace</main>")
        assert (lock.lock_id, "version") in conflict.value.conflicts

        # Unrelated branches continue while the lock holds.
        other = await _generate(service, "banner", "<banner>other</banner>", run_id="run-9")
        assert other.lineage_id == "banner"
        still = await _refine(service, "banner", "<banner>more</banner>")
        assert still.parent_version == other.version

        # The person may still edit explicitly — the accepted v1 itself is
        # untouched (append-only), the edit lands as a new version below it.
        manual = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>tweak</main>",
        )
        assert manual.version == 2
        locked_version = await service.get_version(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1
        )
        assert locked_version.content == "<main>accepted</main>"
        assert locked_version.state is VersionState.ACCEPTED


class TestExplicitRelease:
    @pytest.mark.ac("SPEC-092826-a780/AC-2")
    @pytest.mark.contract("behavioral")
    async def test_releasing_the_lock_allows_the_refinement(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1)
        lock = await service.lock_version(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1, created_by="user-9"
        )

        with pytest.raises(ArtifactLockConflict):
            await _refine(service, "poster", "<main>v2</main>")

        released = await service.release_lock(
            org_id=ORG, project_id=PROJECT, lock_id=lock.lock_id, released_by="user-9"
        )
        assert released.active is False and released.released_by == "user-9"
        v2 = await _refine(service, "poster", "<main>v2</main>")
        assert v2.version == 2

    @pytest.mark.contract("behavioral")
    async def test_a_release_must_name_who_released_it(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        lock = await service.lock_version(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1, created_by="user-9"
        )
        with pytest.raises(LockStateError):
            await service.release_lock(
                org_id=ORG, project_id=PROJECT, lock_id=lock.lock_id, released_by=""
            )


class TestLockingASharedDecision:
    """AC-3: a locked decision constrains the descendants that reference it."""

    @pytest.mark.ac("SPEC-092826-a780/AC-3")
    @pytest.mark.contract("behavioral")
    async def test_same_digest_passes_and_contradiction_is_refused(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(
            service,
            "poster",
            "<main>v1</main>",
            decision_inputs={"claim:tone": "sha256:aaa"},
        )
        await service.lock_decision(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            decision_ref="claim:tone",
            decision_digest="sha256:aaa",
            created_by="user-9",
            reason="tone agreed with client",
        )

        # Citing the locked decision with its locked content is fine.
        v2 = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2</main>",
            decision_inputs={"claim:tone": "sha256:aaa"},
        )
        assert v2.version == 2

        # A change citing a different content for the locked decision is not.
        with pytest.raises(ArtifactLockConflict) as conflict:
            await service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                author="user-9",
                content="<main>v3</main>",
                decision_inputs={"claim:tone": "sha256:bbb"},
            )
        assert conflict.value.conflicts[0][1] == "decision"

        # Work that does not reference the decision is unconstrained.
        v3 = await _refine(service, "poster", "<main>v3</main>")
        assert v3.version == 3


class TestRegionLocks:
    @pytest.mark.contract("behavioral")
    async def test_an_undeclared_change_set_is_refused_and_declared_safe_sets_pass(
        self, tmp_path: Path
    ) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        await service.lock_region(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            version=1,
            address="characters",
            created_by="user-9",
        )

        with pytest.raises(ArtifactLockConflict):
            await service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                author="user-9",
                content="<main>v2</main>",
            )

        v2 = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2</main>",
            changed_addresses=("copy.headline",),
        )
        assert v2.version == 2

        with pytest.raises(ArtifactLockConflict):
            await service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                author="user-9",
                content="<main>v3</main>",
                changed_addresses=("characters.joe-smith",),
            )


class TestGuidanceIsDurableProjectInput:
    """AC-4: guidance survives restart and reaches newly eligible work."""

    @pytest.mark.ac("SPEC-092826-a780/AC-4")
    @pytest.mark.contract("behavioral")
    async def test_guidance_survives_reopen_and_reroutes_new_work(self, tmp_path: Path) -> None:
        db = tmp_path / "a.sqlite3"
        service = CreativeArtifactService(_open_store(db))
        await _generate(service, "poster", "<main>v1</main>")
        branch_note = await service.add_guidance(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            text="drop the dark banner, keep the logo",
            author="user-9",
        )
        project_note = await service.add_guidance(
            org_id=ORG,
            project_id=PROJECT,
            text="client moved launch to the 4th",
            author="user-9",
        )

        # A new process: fresh store over the same database.
        reopened = CreativeArtifactService(_open_store(db))
        inputs = await reopened.agent_inputs(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert inputs.tip is not None and inputs.tip.version == 1
        assert sorted(g.guidance_id for g in inputs.guidance) == sorted(
            [project_note.guidance_id, branch_note.guidance_id]
        )
        assert inputs.active_locks == ()

        # Superseding guidance invalidates by supersession — nothing is deleted.
        replacement = await reopened.add_guidance(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            text="keep the banner after all",
            author="user-9",
        )
        await reopened.supersede_guidance(
            org_id=ORG,
            project_id=PROJECT,
            guidance_id=branch_note.guidance_id,
            by_guidance_id=replacement.guidance_id,
        )
        after = await reopened.agent_inputs(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert sorted(g.guidance_id for g in after.guidance) == sorted(
            [project_note.guidance_id, replacement.guidance_id]
        )
        history = await reopened.guidance_history(org_id=ORG, project_id=PROJECT)
        assert len(history) == 3
        superseded = next(g for g in history if g.guidance_id == branch_note.guidance_id)
        assert superseded.active is False
        assert superseded.superseded_by == replacement.guidance_id

    @pytest.mark.contract("behavioral")
    async def test_empty_guidance_is_refused(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        with pytest.raises(ArtifactVersionError):
            await service.add_guidance(org_id=ORG, project_id=PROJECT, text="   ")


class TestForkWithoutErasing:
    """AC-5: forking a creative direction preserves the original branch."""

    @pytest.mark.ac("SPEC-092826-a780/AC-5")
    @pytest.mark.contract("behavioral")
    async def test_fork_copies_content_and_keeps_the_source_intact(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        v1 = await _generate(service, "poster", "<main>v1</main>")
        v2 = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2</main>",
        )

        forked = await service.fork(
            org_id=ORG,
            project_id=PROJECT,
            source_lineage_id="poster",
            new_lineage_id="poster-alt",
            actor="user-9",
            title="Alternative direction",
        )

        assert (forked.lineage_id, forked.version) == ("poster-alt", 1)
        assert forked.kind is ChangeKind.FORK
        assert (forked.fork_lineage_id, forked.fork_version) == ("poster", 2)
        assert forked.content == v2.content and forked.content_sha == v2.content_sha
        assert forked.author == "user-9"

        # The original branch is untouched and still inspectable.
        source = await service.versions(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert [(v.version, v.content) for v in source] == [(1, v1.content), (2, v2.content)]
        assert (await service.tip(org_id=ORG, project_id=PROJECT, lineage_id="poster")) == v2

    @pytest.mark.contract("behavioral")
    async def test_a_branch_locked_pending_review_can_still_be_forked(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        await service.lock_branch(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", created_by="user-9"
        )
        forked = await service.fork(
            org_id=ORG,
            project_id=PROJECT,
            source_lineage_id="poster",
            new_lineage_id="poster-alt",
        )
        assert forked.fork_lineage_id == "poster"


class TestControlAndLocksSurviveRestart:
    """AC-6: durable control/lock rows projected onto canonical execution."""

    @pytest.mark.ac("SPEC-092826-a780/AC-6")
    @pytest.mark.contract("behavioral")
    async def test_state_survives_reopen_and_projects_canonical_status(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "a.sqlite3"
        service = CreativeArtifactService(_open_store(db))
        await _generate(service, "poster", "<main>v1</main>")
        await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1)
        await service.lock_version(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1, created_by="user-9"
        )
        await service.set_control(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            mode=ControlMode.AUTONOMOUS,
            run_id="run-42",
            updated_by="user-9",
        )

        reopened = CreativeArtifactService(_open_store(db))
        view = await reopened.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", run_status=RunStatus.PAUSED
        )
        assert view.mode is ControlMode.AUTONOMOUS
        assert view.control is not None and view.control.run_id == "run-42"
        assert view.locked is True and len(view.lock_ids) == 1
        assert view.execution is RunStatus.PAUSED and view.paused is True
        assert not view.awaiting_approval and not view.complete and not view.stopped

        waiting = await reopened.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", run_status=RunStatus.WAITING
        )
        assert waiting.awaiting_approval is True and waiting.paused is False

        done = await reopened.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", run_status=RunStatus.COMPLETED
        )
        assert done.complete is True and done.stopped is False

        cancelled = await reopened.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", run_status=RunStatus.CANCELLED
        )
        assert cancelled.stopped is True

        unattached = await reopened.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="never-controlled"
        )
        assert unattached.execution is None and not unattached.stopped
        # A branch with no control row defaults to direct human control.
        assert unattached.mode is ControlMode.DIRECT
        assert unattached.locked is False and unattached.lock_ids == ()

    @pytest.mark.contract("behavioral")
    async def test_a_collaborative_branch_sees_both_kinds_of_versions(self, tmp_path: Path) -> None:
        """The middle of the continuum: one lineage, person and agent alternating."""
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>", run_id="run-co")
        human = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2</main>",
        )
        agent = await _refine(service, "poster", "<main>v3</main>", run_id="run-co")
        await service.set_control(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            mode=ControlMode.COLLABORATIVE,
            run_id="run-co",
            updated_by="user-9",
        )

        view = await service.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", run_status=RunStatus.RUNNING
        )
        assert view.mode is ControlMode.COLLABORATIVE
        history = await service.versions(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert [v.origin for v in history] == [
            ChangeOrigin.AGENT,
            ChangeOrigin.HUMAN,
            ChangeOrigin.AGENT,
        ]
        assert human.author == "user-9" and agent.author == ""

    @pytest.mark.contract("behavioral")
    async def test_accept_is_terminal_and_one_way(self, tmp_path: Path) -> None:
        store = _open_store(tmp_path / "a.sqlite3")
        service = CreativeArtifactService(store)
        await _generate(service, "poster", "<main>v1</main>")
        await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1)
        with pytest.raises(ArtifactVersionNotFoundError):
            await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1)


class TestConflictsAreSurfacedNeverSilent:
    """AC-7: a locked branch names every lock it raises, and writes nothing."""

    @pytest.mark.ac("SPEC-092826-a780/AC-7")
    @pytest.mark.contract("behavioral")
    async def test_branch_lock_blocks_every_origin_and_names_itself(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        lock = await service.lock_branch(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            created_by="user-9",
            reason="pending client review",
        )

        for writer in (
            lambda: service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                author="user-9",
                content="<main>v2</main>",
            ),
            lambda: _refine(service, "poster", "<main>v2</main>"),
        ):
            with pytest.raises(ArtifactLockConflict) as conflict:
                await writer()
            assert (lock.lock_id, "branch") in conflict.value.conflicts

        # Nothing was written by the refused attempts.
        history = await service.versions(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert [v.version for v in history] == [1]

    @pytest.mark.contract("behavioral")
    async def test_agent_work_outside_any_run_is_refused(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        with pytest.raises(ArtifactVersionError):
            await service.record_refinement(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                output=_agent_output("<main>orphan</main>"),
            )
        with pytest.raises(ArtifactVersionError):
            await service.record_generation(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="fresh",
                output=_agent_output("<main>orphan</main>"),
            )

    @pytest.mark.contract("behavioral")
    async def test_a_missing_lineage_or_version_is_a_not_found(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        with pytest.raises(ArtifactVersionNotFoundError):
            await service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="nope",
                author="user-9",
                content="<main>x</main>",
            )
        with pytest.raises(ArtifactVersionNotFoundError):
            await service.record_manual_edit(
                org_id=ORG,
                project_id=PROJECT,
                lineage_id="poster",
                author="user-9",
                content="<main>x</main>",
                parent_version=7,
            )


class TestManualAndAgentShareOneRepresentation:
    """AC-8: one representation, one export path, correctly attributed."""

    @pytest.mark.ac("SPEC-092826-a780/AC-8")
    @pytest.mark.contract("behavioral")
    async def test_both_origins_export_the_same_key_set(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(service, "poster", "<main>v1</main>")
        human = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            author="user-9",
            content="<main>v2</main>",
        )
        agent = await _refine(service, "poster", "<main>v3</main>")

        human_export = human.to_dict()
        agent_export = agent.to_dict()
        assert set(human_export) == set(agent_export)
        assert human_export["origin"] == "human" and agent_export["origin"] == "agent"
        assert human_export["author"] == "user-9" and agent_export["author"] == ""
        assert human_export["content_sha"] and agent_export["content_sha"]
        assert human_export["content_sha"] != agent_export["content_sha"]
        # Neither pretends to be the other kind of producer.
        assert human_export["run_id"] is None
        assert agent_export["run_id"] == "run-2"


class TestTheStoreKeepsItsPromises:
    @pytest.mark.contract("behavioral")
    async def test_a_version_round_trips_every_field(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))
        await _generate(
            service,
            "poster",
            "<main>v1</main>",
            brief_ref="brief-lineage#3",
            decision_inputs={"claim:tone": "sha256:aaa"},
        )
        stored = await service.get_version(
            org_id=ORG, project_id=PROJECT, lineage_id="poster", version=1
        )
        assert stored.brief_ref == "brief-lineage#3"
        assert stored.decision_inputs == {"claim:tone": "sha256:aaa"}
        assert stored.state is VersionState.DRAFT
        assert stored.content_sha == stored.to_dict()["content_sha"]

    @pytest.mark.contract("behavioral")
    async def test_first_writer_wins_on_a_version_slot(self, tmp_path: Path) -> None:
        store = _open_store(tmp_path / "a.sqlite3")
        service = CreativeArtifactService(store)
        v1 = await _generate(service, "poster", "<main>v1</main>")
        with pytest.raises(ArtifactVersionExistsError):
            await store.append_version(
                ArtifactVersion(
                    org_id=ORG,
                    project_id=PROJECT,
                    lineage_id="poster",
                    version=1,
                    kind=ChangeKind.GENERATION,
                    origin=ChangeOrigin.AGENT,
                    content="racer",
                    format="html",
                )
            )
        history = await service.versions(org_id=ORG, project_id=PROJECT, lineage_id="poster")
        assert history[0].content == v1.content

    @pytest.mark.contract("behavioral")
    async def test_unique_hit_the_precheck_missed_still_reads_as_exists(
        self, tmp_path: Path
    ) -> None:
        """The UNIQUE key is (project_id, lineage_id, version) — org is not in it.

        An insert whose pre-check misses (different org, same slot) falls
        through to the constraint itself and must still surface as the
        supersession conflict, not a generic integrity error.
        """
        store = _open_store(tmp_path / "a.sqlite3")
        for org in ("org-a", "org-b"):
            version = ArtifactVersion(
                org_id=org,
                project_id=PROJECT,
                lineage_id="poster",
                version=1,
                kind=ChangeKind.GENERATION,
                origin=ChangeOrigin.AGENT,
                content=f"racer-{org}",
                format="html",
            )
            if org == "org-b":
                with pytest.raises(ArtifactVersionExistsError):
                    await store.append_version(version)
            else:
                await store.append_version(version)

    @pytest.mark.contract("behavioral")
    async def test_fk_violation_is_not_misread_as_version_exists(self, tmp_path: Path) -> None:
        """A missing parent `design_projects` row is SQLSTATE 23503, not 23505.

        The real schema (migration 047) foreign-keys project_id to
        design_projects; writing an orphan version must surface the integrity
        failure itself, never a false "version already exists" supersession
        conflict — and a false conflict would mask a broken reference.
        """
        versions_ddl = _DDL[0].replace(
            "UNIQUE (project_id, lineage_id, version)",
            "UNIQUE (project_id, lineage_id, version),\n"
            "        FOREIGN KEY (project_id) REFERENCES design_projects (id)",
        )
        store = _open_store(
            tmp_path / "fk.sqlite3",
            ddl=(
                "CREATE TABLE design_projects (id TEXT PRIMARY KEY)",
                versions_ddl,
                *_DDL[1:],
            ),
            connect=("PRAGMA foreign_keys=ON",),
            seed=(f"INSERT INTO design_projects (id) VALUES ('{PROJECT}')",),
        )
        orphan = ArtifactVersion(
            org_id=ORG,
            project_id="proj-missing",
            lineage_id="poster",
            version=1,
            kind=ChangeKind.GENERATION,
            origin=ChangeOrigin.AGENT,
            content="racer",
            format="html",
        )
        with pytest.raises(ArtifactVersionError) as excinfo:
            await store.append_version(orphan)
        assert not isinstance(excinfo.value, ArtifactVersionExistsError)
        assert "already exists" not in str(excinfo.value)
        assert "23503" in str(excinfo.value)
        # With the parent row in place the same version lands normally.
        grounded = ArtifactVersion(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="poster",
            version=1,
            kind=ChangeKind.GENERATION,
            origin=ChangeOrigin.AGENT,
            content="racer",
            format="html",
        )
        await store.append_version(grounded)
        stored = await store.get_version(ORG, PROJECT, "poster", 1)
        assert stored is not None and stored.content == "racer"


class TestOneMixedControlProject:
    """AC-9: direct, autonomous and locked branches active at the same moment."""

    @pytest.mark.ac("SPEC-092826-a780/AC-9")
    @pytest.mark.contract("behavioral")
    async def test_three_branches_with_three_control_states(self, tmp_path: Path) -> None:
        service = CreativeArtifactService(_open_store(tmp_path / "a.sqlite3"))

        # Branch 1 — direct: a person drives, editing by hand.
        await _generate(service, "direct", "<main>seed</main>", run_id="run-seed")
        direct_tip = await service.record_manual_edit(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="direct",
            author="user-9",
            content="<main>hand edit</main>",
        )
        await service.set_control(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="direct",
            mode=ControlMode.DIRECT,
            updated_by="user-9",
        )

        # Branch 2 — autonomous: a Run refines without another prompt.
        await _generate(service, "auto", "<main>seed</main>", run_id="run-auto")
        auto_tip = await _refine(service, "auto", "<main>refined</main>", run_id="run-auto")
        await service.set_control(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="auto",
            mode=ControlMode.AUTONOMOUS,
            run_id="run-auto",
            updated_by="user-9",
        )

        # Branch 3 — locked: accepted copy frozen pending review. It was an
        # autonomous branch until the person froze it mid-flight.
        await _generate(service, "locked", "<main>approved</main>", run_id="run-lock")
        await service.set_control(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="locked",
            mode=ControlMode.AUTONOMOUS,
            run_id="run-lock",
            updated_by="user-9",
        )
        await service.accept(org_id=ORG, project_id=PROJECT, lineage_id="locked", version=1)
        await service.lock_version(
            org_id=ORG,
            project_id=PROJECT,
            lineage_id="locked",
            version=1,
            created_by="user-9",
            reason="client-approved",
        )

        # The autonomous path tries the locked branch and is refused, by name.
        with pytest.raises(ArtifactLockConflict) as conflict:
            await _refine(service, "locked", "<main>replace</main>", run_id="run-auto")
        assert conflict.value.conflicts[0][1] == "version"

        # The other branches continued while the lock held.
        assert direct_tip.version == 2 and direct_tip.author == "user-9"
        assert auto_tip.run_id == "run-auto" and auto_tip.version == 2

        # Each branch projects its own simultaneous state.
        direct = await service.branch_state(org_id=ORG, project_id=PROJECT, lineage_id="direct")
        auto = await service.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="auto", run_status=RunStatus.RUNNING
        )
        locked = await service.branch_state(
            org_id=ORG, project_id=PROJECT, lineage_id="locked", run_status=RunStatus.PAUSED
        )
        assert (direct.mode, direct.locked) == (ControlMode.DIRECT, False)
        assert (auto.mode, auto.locked, auto.execution) == (
            ControlMode.AUTONOMOUS,
            False,
            RunStatus.RUNNING,
        )
        assert (locked.mode, locked.locked, locked.paused) == (ControlMode.AUTONOMOUS, True, True)

        # The locked branch is still exactly at its accepted version.
        locked_tip = await service.tip(org_id=ORG, project_id=PROJECT, lineage_id="locked")
        assert locked_tip is not None
        assert (locked_tip.version, locked_tip.state) == (1, VersionState.ACCEPTED)
