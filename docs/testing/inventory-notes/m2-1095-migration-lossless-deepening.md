---
inventory-delta:
  tests/: 0
---

# m2-1095 — the 064 live leg pins losslessness where string checks cannot reach

No test count moves: the three scenarios in
`tests/migrations/test_legacy_principal_ownership_live.py` and the plan-shape
tests in `tests/test_legacy_principal_migration.py` keep their collections.
What moves is what those existing bodies can catch, all against a live
PostgreSQL 18 via the `MAISTRO_TEST_DATABASE_URL` gate:

- **User-model statement keys are re-keyed, not just re-owned.**
  `user_model_statement_keys.fact_key` is the owner-bound digest
  `fact_key(owner, normalize_statement(statement))` — the table's primary key —
  while 064's bulk update only retargets the descriptive `owner_user_id`
  column. A legacy row left under its `default`-hashed key would make runtime
  promotion under `conductor` compute a different digest and file a duplicate
  fact (or resurrect struck wording). The migration now recomputes the digest
  from the lineage's statement under the canonical owner and merges collisions:
  a clean re-key, a wording `conductor` already promoted (its lineage stays
  canonical), and a wording the legacy principal tombstoned (the strike keeps
  the key so re-promotion stays blocked). The seed computes its keys through the
  application's own `maistro.memory.user_model.types.fact_key` — the oracle the
  migration's inlined copy must stay byte-identical to — and the live assertions
  pin all three merge shapes.
- **Membership role merge honors the capability ladder.** A workspace where
  neither side is owner but the legacy row is `contributor` must merge to
  `contributor`, not `member`: `WorkspaceMembership.can_contribute` treats
  contributor as a distinct capability from member, so a member-only merge
  would silently drop it. Owner still wins; earliest `added_at` still survives.
- **Signed audit proofs stay byte-intact.** An `audit_log` row carrying an
  ADR-073 Ed25519 proof signs `canonical_audit_bytes`, which covers `user_id`
  and `org_id`; retargeting them under the unchanged signature makes
  `PgAuditLog.verify()` reject the row as tampered. The migration now skips
  signed rows (`signature <> ''`) — deliberately immutable historical evidence
  resolved through `principal_identity_mappings`, per the issue's own
  inventory rule — and the live assertions distinguish the migrated unsigned
  rows from the intact signed one.
- **Strike enforcement is re-derived, not just summed.** Summing counts while
  OR-ing flags leaves a merged 2+1 principal usable when neither surviving row
  was disabled. The merge now re-applies the runtime ladder
  (`security.strikes`: >=3 disables, 2 locks for `LOCKOUT_DURATION` = 8h from
  the later violation, 1 elevates) while keeping the stricter existing state;
  the live assertions pin scrutiny level, the preserved still-future lock, and
  the disable.

The plan-shape suite gains the same contract at the string level (the
statement-key re-key step must appear in the emitted plan) with an empty-table
bind stub so the pass through `upgrade()` stays on the same footing.

<!-- The count alone hides compensating changes; that is the case these notes
     exist for. Zero is a delta too. -->
