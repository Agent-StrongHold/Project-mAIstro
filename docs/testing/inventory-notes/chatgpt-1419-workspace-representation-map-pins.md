---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# #1419 — Workspace representation ownership map pins

Two tests pinning the projection half of the verified Workspace
data-ownership map (`docs/architecture/WORKSPACE-DATA-OWNERSHIP-MAP.md`,
written for #1419's "map the four representations" criterion).

- `test_presentation_fields_never_restate_canonical_identity` pins the
  structural fact that keeps `workspace_presentations` a projection rather
  than a second identity namespace: its field set is exactly the
  persona/UI choice set, and `name`, `members`, and `created_at` are absent.
- `test_a_presentation_record_alone_cannot_authorize_or_compose_a_view`
  proves the behavioral consequence: a projection row whose canonical
  identity does not exist authenticates nobody (`is_member`/`member_role`),
  composes no view, and surfaces in no listing.

Existing authority tests already prove the mirror/journal/quarantine legs of
the same map; these two close the presentation leg, which no prior test
pinned directly.
