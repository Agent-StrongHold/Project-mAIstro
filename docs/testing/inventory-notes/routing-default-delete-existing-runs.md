---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Existing-run operations survive a deleted default Workspace

One test pins the four Workspace-independent operations on
`WorkspaceRoutingAdmitter` — `record_transition`, `run_for_task_receipt`,
`lookup_run`, `find_task_run` — after the default Workspace is deleted.
Deleting a default Workspace that owns no Runs is legal, but the #37
canonical-existence fence in `admitter_for` refuses any resolution of the
deleted id, so routing these operations through `admitter_for(None)`
strands every transition and lookup for Runs admitted under other,
still-live Workspaces. The fix routes the four operations through a
store-bound admitter built at construction (its Project resolution stays
inert; admissions keep the fence).

Fails against the pre-fix router (`admitter_for(None)` delegation) with
`WorkspaceNotFound` on the stranded Run's first transition; passes with the
store-bound admitter. No PG leg: the fence and the operations are tier-
independent and the InMemory spine already binds the canonical Workspace
authority that arms the fence.
