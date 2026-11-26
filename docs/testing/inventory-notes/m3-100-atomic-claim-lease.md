---
inventory-delta:
  packages/maistro-core/tests: +74
  packages/maistro-server/tests: +6
---

# m3-100-atomic-claim-lease

New tests only; nothing was removed or moved.

- `packages/maistro-core/tests` (+74):
  `workspaces/backlog/test_backlog_store_conformance.py` gains the claim/lease
  (#100) bodies for the same in-memory/SQLite pair: atomic claim with one
  winner under `asyncio.gather` (all four concurrent claims, both backends),
  claimant Agent/worker/Run recorded and `goal_ref` untouched, lease expiry as
  an injected reading (expired lease re-opens the item; the re-claim advances
  the fence), renewal extending the lease at the same fence generation,
  release clearing the claim with the fence never repeating across hand-offs,
  the dependency gate parametrized over satisfied (implemented/superseded/
  obsolete) and blocking (proposed/accepted/accepted_spec/blocked/abandoned)
  statuses, the claimable status pool (proposed/accepted/accepted_spec in;
  blocked/implemented/superseded/obsolete/abandoned out), the autonomy gate
  (the four #103 campaign modes plus an unknown fail-closed token, agent vs
  human claimants) with the vocabulary pinned against `campaigns.AutonomyMode`,
  declared scope checked against allowed/protected scope with path semantics,
  fence-required edits on claimed items (missing/wrong/live fence), a stale
  holder refused after release + re-claim even at the right version, retiring
  a claimed item releasing the claim in the same write with deterministic
  re-eligibility, claimant/lease shape refusals, renew/release with no live
  claim, a non-holder refused renew/release at the live fence (review-fix
  round: the fence is readable by every contributor, so it alone proves
  nothing), and the SQLite-only restart test (claim survives reopen; the
  fence continues from the stored generation).
- `packages/maistro-server/tests` (+6): `api/test_backlog_api.py` covers the
  contributor claim cycle over HTTP (claimant/fence/lease recorded, second
  claim 409 with the current item, fence-required PATCH, renew, release, the
  dedicated `GET .../claim` read for members and `null` after release), agent/
  run/scope attribution, human-only refusal for agent claims, the open-
  dependency 409 with the blocking id named, the membership boundary (member
  403 on claim/renew/release, stranger and cross-Workspace 404), and 422 body
  validation.
