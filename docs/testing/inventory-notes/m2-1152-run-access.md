---
inventory-delta:
  packages/maistro-core/tests: +4
---

# M2-A #1152 Run access

`tests/runs/test_access.py` carries four async cases for the admission half of
the canonical Run seam (reads are covered by the Workspace-membership read
seam: `tests/runs/test_scoped_reads.py` and the cross-backend conformance
suite `tests/workspaces/test_store_boundary_scope_conformance.py`):

1. admission binds accounting to the authenticated and acting principals, and
   Run metadata cannot mint a different accounting identity;
2. a delegated acting principal must be the authenticated principal or an
   agent it owns (foreign acting principals are refused);
3. a delegation minted in one Workspace cannot admit work in another
   (authorization scope must match the Graph scope);
4. two principals in two Workspaces delegate concurrently and neither Run
   records the other's initiating or acting identity.

The maistro-server `/v1/runs` routes moved from actor-equality to the
Workspace-membership boundary (owner decision 2026-09-23):
`packages/maistro-server/tests/api/test_task_workspace_scope.py` pins that a
same-Workspace member reads another initiator's Run while a non-member gets
the word-for-word missing-id 404, and `test_runs_api.py` pins member reads of
a foreign-initiated Run plus identical missing-id refusals.

The interrupted round's two scoped-reader cases were retired here: the same
invariants ship (and pass on memory, SQLite and PostgreSQL) through PR #1595's
`ScopedRunReader` suite and the merged conformance oracle of PR #1809, whose
`KNOWN_GAPS` is empty.
