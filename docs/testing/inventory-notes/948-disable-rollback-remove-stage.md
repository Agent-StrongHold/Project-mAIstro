---
inventory-delta:
  packages/maistro-core/tests: +2
---

# #948 (EPIC M9-J) — the #954 post-install lifecycle stage (disable/rollback/remove)

`scripts/extension_lifecycle_proof.py` gains the `disable-rollback-remove`
stage (schema v2, 13 stages), closing the epic acceptance link that the
previous round could only pin as properties: the #954 operator verbs
(`disable`/`resume`/`rollback`/`remove`) are now driven end to end on the
production `ExtensionInstallService` seam —

- **disable** clears the active pointer structurally (resolution answers
  nothing) while the record keeps its frozen grant, manifest snapshot, and
  one audited ACTIVE→DISABLED trail event;
- **resume** presents the same bound artifact, re-enters through INSTALLING
  so the loader seam runs again, and restores the pointer to the same
  record without re-deciding the grant;
- **rollback** restores the superseded 1.1.0 and truthfully narrows
  authority back to that version's frozen (empty) grant — the pure 1.x
  artifacts now expose `probe_undeclared`, the same deliberate
  storage-authority reach the greeter artifact has, so the denial is an
  *observed* invocation, not an assertion about types — and a rollback that
  would smuggle the broader 2.0.0 frozen grant back is refused
  (`RollbackRefused`) before anything is touched;
- **remove** is terminal for the record's authority, idempotent on retry,
  and preserves the record's digest, frozen grant, manifest snapshot, and
  full audited trail as historical evidence — proven first for the
  already-superseded 2.0.0 while the active 1.1.0 keeps running, then for
  the 1.1.0 record that *is* the active pointer, whose uninstall exercises
  the production active-pointer cleanup path and leaves the scope with no
  active version at all (`remove-active-record-clears-the-active-pointer`).

**+2 `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`**
(collect verified; module total 15 → 17):

- `TestPostInstallLifecycle.test_disable_rollback_remove_stage_proves` —
  the stage proves all ten checks and its evidence names the rolled-back
  1.1.0 and the terminally removed 2.0.0;
- `TestPostInstallLifecycle.test_removed_record_keeps_evidence_and_grant_narrowed`
  — re-derives the end state from the store rather than the stage's own
  claims: both removed records (the 2.0.0 and the active-pointer 1.1.0)
  keep their artifact digests and frozen grants with REMOVED-terminated
  trails; the run ends with no active notary record; and the rolled-back
  artifact's storage reach is an observed `denied:undeclared-capability`
  invocation.

Pre-existing pins updated in place: `EXPECTED_STAGES` gains
`disable-rollback-remove` (12 → 13 stages); `docs/extensions/lifecycle-proof.md`
now maps the rollback/disable/remove epic criterion to this stage and states
the remaining boundary (activation-pointer restart durability, marked on
`durable-restart`) instead of deferring the whole surface.

Validation on this head: `uv run pytest
packages/maistro-core/tests/extensions/test_lifecycle_proof.py -x -q` →
17 passed; script standalone `PROVED: 13/13 stages, 61/61 checks` with an
identical `deterministic_core_sha256` across two runs.
