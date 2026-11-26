# Issue #7 bounded implementation checkpoint

## Frozen scope

- Assignment: issue #7 only; branch `auto-7`; starting HEAD `d90b7afa41157afe42e63e602ea8cc7afbeceadc`; supplied develop base `7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d`.
- Evidence snapshot: `/home/dev/maistro/jobs/f3bbba4e05894a4985e8e5000423fee0/dispatch-context.json`. No remote enumeration or GitHub mutations.
- Initial worktree was clean. Existing committed lane work is preserved. No incoming uncommitted patch was necessary.
- This round will inspect and validate the salvaged Entra group-gated JIT provisioning slice (#492 in the milestone exit conditions), its production auth path, adjacent tests and governing ADRs. Candidate edit scope: Conductor backend auth/config/tests, corresponding inventory note, and this handoff. Other milestone capabilities are acceptance review only, not implementation scope for this bounded round.

## Prior-attempt diagnosis / ambiguities

- Supplied failure: provider HTTP 400 / tool calls cut off by max_tokens, with no new artifact. Strategy: smallest independently testable salvaged slice, no milestone-wide rewrite.
- Supplied prior result file is absent (`ENOENT`); not found, skipped.
- Job directory listing contains no `check-*.log` files; driver checks cannot be claimed.
- Issue #7 is a multi-initiative milestone, not a bounded implementation specification. Assumption: improve/prove the existing #492 slice and report all other exit conditions as unverified rather than claim milestone completion.
- Existing history includes rebuild repairs and broad changes relative to supplied develop base. Do not discard or silently certify that inherited diff.

## Progress

- Baseline targeted validation: `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -x -q` — 22 passed (2.20s); log `/tmp/issue-7-jit-before.log`.
- Reachable production seam: `OAuthLoginService.__init__` builds the JIT provisioner from Settings; `authenticate` calls it only for verified, unlinked Entra identities. Existing policy limits new accounts to role `user` and configured permissions.
- Evidence-backed gap selected: `GraphMembershipResolver.resolve` forwards the login access token to an arbitrary `@odata.nextLink`, and treats non-string/blank next links as completed membership. This can disclose credentials to an unrelated allowlisted origin or admit on malformed partial evidence. Bound repair to validating Graph pagination and rejecting malformed continuations; add both resolver and real-login regression tests. No new auth authority or entitlement semantics.
- Relevant governance reviewed: ADR-080 (same-user memory is not scope widening), ADR-082226-5104 (PostgreSQL authority; Ladybug projections), ADR-068 (existing authorization/elevation substrate), and Proposed ADR-059 (OAuth authN yields the existing Hive session, not IdP-provided authZ). Reconciliation: existing administrator-configured group-to-permission JIT mapping is the issue's explicit extension of ADR-059's deferred optional map; this repair changes neither that mapping nor the accepted authorization model. Memory and execution authorities remain untouched.
- Regression demonstration: `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q -k 'untrusted_graph_pagination or invalid_continuations'` — **17 failed, 22 deselected** against unchanged production code. Includes all three real-login cases; log `/tmp/issue-7-pagination-red.log`.
- Repair: validate continuations against the HTTPS Graph origin and `/v1.0/me/transitiveMemberOf` subject endpoint before issuing another request. Reject malformed present continuations instead of considering partial evidence complete. Never echo continuation values into errors/audit.
- After repair: targeted suite **39 passed** (1.52s), including pre-existing paged success and page-limit refusal; log `/tmp/issue-7-jit-after.log`. Focused ruff check passed. Initial format check found the two touched files needed formatting; applied `uv run ruff format` to those files. Wider validation pending.
