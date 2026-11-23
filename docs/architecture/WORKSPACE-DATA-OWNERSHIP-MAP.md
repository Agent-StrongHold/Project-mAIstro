# Workspace Data Ownership Map

**Status:** living document · requested by #1419 ("Map the four named representations to their current owner, fields, read/write consumers, retention and migration/recovery purpose")
**Authority spine:** [ADR-092326-97c4](../adr/ADR-092326-97c4-shared-postgres-workspace-owner.md) (Accepted) — shared PostgreSQL is the single owner of canonical Workspace identity · canonical-owner epic #37/#446
**Companions:** [CONVERGENCE-MATRIX.md](CONVERGENCE-MATRIX.md) ("Workspace / Project scope" row) · [CONDUCTOR-PERSISTENCE-MAP.md](CONDUCTOR-PERSISTENCE-MAP.md) (durability/ack contract per store family)
**Ground truth at this head:** `packages/hive-conductor/backend/services/workspace_authority.py`, `packages/hive-conductor/backend/models/workspace.py`, `packages/maistro-core/src/maistro/workspaces/store.py`

This map is an account of what is stored, where, by whom, and for how long. It
states retention as the code actually behaves; it invents no policy durations.
Each representation's role follows the #1419 boundary: canonical identity has
one write authority, presentation is a projection, and the journal/quarantine
and recovery mirror are bounded migration/recovery evidence. None of them is an
alternative authorization truth.

## The four representations at a glance

| # | Representation | Lives in | Owner | Role |
|---|---|---|---|---|
| 1 | Canonical Workspace identity/membership | `canonical_workspaces` + `canonical_workspace_memberships` (+ Root Project in `canonical_projects`) | `maistro.workspaces.WorkspaceStore` (maistro-core) over the shared PostgreSQL | **The only authority** for identity, name, membership, Root Project |
| 2 | Presentation projection | Hive store `workspace_presentations` (`WorkspacePresentation`) | Hive | Persona/UI choices attached to a canonical ID; a reference, not an identity namespace |
| 3 | Migration journal + quarantine | Hive JSON stores `workspace_convergence_journal`, `workspace_convergence_quarantine` | Hive | Import idempotency guard and crash-boundary evidence |
| 4 | Recovery mirror | Hive model store `stores.workspaces` (`Workspace`) | Hive | Restart-recovery evidence for the ephemeral dev-path canonical store only |

## 1. Canonical Workspace identity/membership — the authority

**Fields.** Workspace: `workspace_id`, `name`, `description`, `metadata`,
`created_at`, `updated_at`. Membership: `workspace_id`, `user_id`, `role`
(`owner`/`contributor`/`member`), `added_at`
(`packages/maistro-core/src/maistro/workspaces/model.py`). Both durable
backends persist these models through the same relational columns — identity,
role, and timestamps (`sqlite_store.py` schema; migration 019's
`canonical_workspaces` / `canonical_workspace_memberships`) — with the full
record, `description` and `metadata` included, serialized in the row's
`payload` column. `principal_id` is not stored state anywhere in this family —
it is the acting-principal keyword argument on store/authorization methods
(`get`, `update`, `delete`, `get_membership`) that is resolved against the
membership rows, never persisted as one of them.
The same `workspace_id` atomically provisions the immutable Root Project
(`project_store.create_root` inside `WorkspaceStore.create`,
`packages/maistro-core/src/maistro/workspaces/store.py`).

**Write consumers.** Hive's single write authority
`services/workspace_authority.py` (`create_workspace`, `set_member`,
`remove_member`, `delete_workspace` — the only functions Hive routes may mutate
through), maistro-server's `/v1/workspaces` API
(`packages/maistro-server/src/maistro_server/api/workspaces.py`), and the
one-time convergence import in `_migrate_one`. No Hive route writes name or
membership anywhere else.

**Read consumers.** Hive authorization (`is_member`, `member_role`,
`list_workspace_ids_for_user`), Hive view composition (`get_view`,
`list_views_for_user`, `visible_view`), maistro-server routes, and admission
paths that resolve Workspace scope.

**Retention.** Rows live exactly as long as the Workspace exists. Deletion
(`store.delete`) is the logical end of the identity and its memberships on both
durable and ephemeral backends; durable rows survive process restart.

## 2. `workspace_presentations` — a projection, not a second owner

**Fields.** `workspace_id` (a foreign reference to the canonical ID),
`persona_template_id`, `checklist`, `tool_bindings`, `theme_id`,
`voice_tone_override`, `active`, `updated_at`. Name, membership, and creation
time are deliberately absent — the record cannot restate identity, so it cannot
become a second identity namespace (`models/workspace.py::WorkspacePresentation`;
pinned by `test_presentation_fields_never_restate_canonical_identity`).

**Write consumers.** `create_workspace` and `update_presentation` (product
mutations), and `_presentation_from_legacy` during the one-time import.

**Read consumers.** View composition (`get_view`, `list_views_for_user`) and
`_sync_fallback_recovery_evidence` on the ephemeral path. **Authorization never
reads it**: a canonical Workspace without a presentation record authorizes fine
but is not listed in Hive's UI (documented ADR-092326-97c4 trade-off); a
presentation record without a canonical Workspace authorizes nothing and
composes no view
(`test_a_presentation_record_alone_cannot_authorize_or_compose_a_view`).

**Retention.** Held while the canonical Workspace exists; popped by
`delete_workspace`. A stale projection can make the *view* stale (UI choices),
never the *authority*.

## 3. Migration journal + quarantine — bounded migration evidence

**Journal fields** (`workspace_convergence_journal[workspace_id]`): `status`
(`importing`/`complete`), `mode` (`legacy_import`/`canonical_create`/
`fallback_recovery`), `updated_at`. **Quarantine fields**
(`workspace_convergence_quarantine[source_key]`): `workspace_id`, `reason`,
`quarantined_at`.

**Write consumers.** `_write_journal` (import lifecycle markers),
`_quarantine_source` (rows held out of migration: blank id/name, no owner,
blank or duplicate member ids, interrupted durable imports).

**Read consumers.** `_journal_status` and `_imported_into_durable_store` — the
idempotency guard that decides whether a mirror row still needs importing.
Reads never grant authority; the journal's only power is to *prevent* a
re-import, and quarantine's only power is to *hold* a row out.

**Retention and disposition.** On the durable path the journal is retained
indefinitely **by design**: its `complete` entry is what keeps a frozen legacy
mirror row from being imported again after a restart, so removing it would let
a deleted Workspace resurrect. Quarantined rows are retained until the
operational recovery owner reviews and disposes of them — there is no automatic
cleanup and no silent completion (`_migrate_one` raises
`LegacyWorkspaceQuarantined` rather than replaying). On the ephemeral dev path
the journal entry is popped when the Workspace is logically deleted, together
with its mirror row (`delete_workspace`).

## 4. `stores.workspaces` recovery mirror — dev-path restart evidence

**Fields.** The full legacy compatibility record (`Workspace`): `id`, `name`,
`members` (`user_id`, `role`), `persona_template_id`, `checklist`,
`tool_bindings`, `theme_id`, `voice_tone_override`, `active`, `created_at`,
`updated_at` — which is exactly why this record is dangerous if it were ever an
authority: it restates every canonical fact.

**Write consumers.** `_sync_fallback_recovery_evidence`, called on every
canonical mutation (`create_workspace`, `set_member`, `remove_member`,
`update_presentation`) — **only when the canonical store is ephemeral** (no
database, or an in-process database such as `memory://`/pathless `sqlite://`).
`_is_durable_store` is the guard: on the shipped durable path the mirror
receives no writes at all, and `_engine_workspace_store` raises
`EmbeddedRuntimeUnavailable` rather than falling back to it.

**Read consumers.** `_ensure_ready` at adapter start: on the durable path each
row is imported once, keeping exact id, roster, roles, and timestamps, guarded
by the journal; on the ephemeral path the mirror rebuilds the in-memory
canonical fallback. Nothing else reads it; routes and authorization never
consult it as authority (module contract,
`workspace_authority.py` docstring).

**Retention.** Durable path: pre-existing rows stay where history left them as
a frozen import source — the journal entry, not the row's absence, is the
import guard, so the row is never edited to "clean it up". Ephemeral path: kept
synchronized as restart-recovery evidence and removed on logical deletion. A
configured database with a missing canonical Container fails closed; the mirror
is never replayed to fill the gap
(`test_a_configured_database_without_a_container_refuses_the_mirror_fallback`).

## Stale records cannot override canonical authorization

Behavioral proof at this head (`packages/hive-conductor/backend/tests/`,
executed 2026-11-23 at commit `1c840790a1`). With `MAISTRO_TEST_PG_DSN`
pointed at a PostgreSQL 18 database migrated to alembic head
(`DATABASE_URL=postgresql+asyncpg://… uv run alembic upgrade head`, revision
068): both suites together report **35 passed, 0 skipped** —
`test_workspace_authority.py` 11 + `test_workspace_authority_durable.py` 24.
Without a DSN the same invocation reports 27 passed, 8 skipped: the 8
PostgreSQL-only legs all live in `test_workspace_authority_durable.py`, and
`MAISTRO_REQUIRE_PG_LEGS=1` turns that silent skip into an error:

| Claim | Test |
|---|---|
| Legacy membership edits never change live authorization | `test_workspace_authority.py::test_live_membership_authority_does_not_follow_legacy_store_mutation` |
| Pre-existing canonical state beats stale legacy membership | `test_workspace_authority.py::test_preexisting_canonical_workspace_wins_over_stale_legacy_membership` |
| Mirror rows import once and never resurrect | `test_workspace_authority_durable.py::test_legacy_mirror_rows_import_once_and_never_resurrect` |
| Revocations/deletions survive restart without mirror writes | `test_workspace_authority_durable.py::test_restart_keeps_revocations_and_deletions_without_any_mirror_writes` |
| No-database fallback still composes from journaled recovery evidence | `test_workspace_authority_durable.py::test_without_a_database_the_ephemeral_fallback_still_serves` |
| Presentation is a projection only (this map's pinned boundary) | `test_workspace_authority.py::test_a_presentation_record_alone_cannot_authorize_or_compose_a_view`, `::test_presentation_fields_never_restate_canonical_identity` |

## Reopen/restart and migration-failure dispositions

| Case | Disposition | Test |
|---|---|---|
| Restart, durable path | Canonical rows serve as-is; revocations/deletions kept; no mirror writes or replay | `test_restart_keeps_revocations_and_deletions_without_any_mirror_writes` |
| Restart, ephemeral dev path | Fallback rebuilt from synchronized mirror + journal (`fallback_recovery`) | `test_workspace_authority.py::test_fallback_created_workspace_survives_adapter_restart` |
| Import interrupted mid-roster-copy (ephemeral) | Resumes from the `importing` marker; members not dropped | `test_workspace_authority.py::test_interrupted_membership_import_resumes_instead_of_dropping_members` |
| Import interrupted after canonical `create` (durable) | Quarantined; never replays over later canonical deletion/revocation; source + marker preserved for the recovery owner | `test_workspace_authority_durable.py::test_interrupted_import_never_replays_over_canonical_changes` (#2258) |
| Import interrupted before `create` (durable) | Also quarantined — absence does not prove never-created | `test_workspace_authority_durable.py::test_interrupted_import_before_create_is_quarantined_without_blocking_fresh_rows` (#2258) |
| Malformed legacy row (blank id/name, no owner, blank/duplicate member) | Quarantined; other Workspaces migrate unaffected | `test_workspace_authority.py::test_ownerless_legacy_row_is_quarantined_without_blocking_valid_workspace` |
| Durable create fails | Canonical write rolled back; mirror untouched | `test_workspace_authority_durable.py::test_a_failed_durable_create_rolls_back_without_touching_the_mirror` |
| Delete | Canonical identity deleted; projection popped; durable: journal + frozen mirror row retained as the import guard; ephemeral: journal + mirror row removed | `test_workspace_authority.py::test_delete_workspace_retires_a_hive_projection_row_when_one_exists` |

## Explicitly open under the canonical-owner epic (not resolved by this map)

- maistro-server's `WorkspaceRoutingAdmitter.admitter_for` still provisions a
  Root Project for any non-empty Workspace id without canonical-existence
  verification, and `canonical_projects` lacks the
  `canonical_workspaces` foreign key (deferred by migration 019) — owned by
  #37/#38.
- The initial roster copy holds a Hive-process-local lock only; a concurrent
  revocation through maistro-server during that window remains an open
  transaction-boundary requirement under #37.
- The Turing backend's private per-process `InMemoryWorkspaceStore` is its own
  convergence item under #37.
- #1419's user-facing account: this document is the maintainer-facing account
  built from the verified ownership model. A product-surface rendering of it
  remains open; per the issue, a transparency page alone is insufficient for
  closure — closure cites #37/#446's implementation and the behavioral evidence
  above.
