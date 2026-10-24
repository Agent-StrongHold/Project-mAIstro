# Issue #1893 repair validation — job 841af872

## Frozen scope

- Issue #1893 only; assigned branch `auto-1893`.
- Starting head `dbae3b4455b32946244dacd379af129b29ab3e39`;
  supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree was clean. No incoming uncommitted work to salvage.
- Inspect existing admission codec/identity source and adjacent tests, repository
  instructions, relevant ADRs, CI workflow and quality policy. Validate named
  Vulture gate, provenance, focused tests, lint/format and scoped typecheck.
- Write scope: this evidence note only unless executed evidence identifies an
  in-scope code defect; no speculative fixes or reachability/grant edits.
- Dispatch snapshot is the supplied job's `dispatch-context.json`; do not
  re-fetch issues/PRs. Driver logs report 311 passing tests and three skips;
  those skips are not database acceptance evidence.

## Ambiguity and assumption

The generic `test: failure` contains no candidate-qualified failing traceback.
Proceed with focused independent reproduction. The prior report identifies a
reachability provenance failure, not a develop merge conflict. A local grant
or activation is prohibited; if reproduced, report the blocker rather than
repeat prior repair loops or claim a merge-ready result.

## Results

- Independently reproduced provenance failure (exit 1) with
  `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`.
  Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  are unauthorized new unreachable modules and unauthorized dispositions.
- Named Vulture command passed: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`;
  1323 findings match 1323 reviewed identities. No ledger amendment warranted.
- Local `origin/develop` resolves to the exact supplied base. No unresolved
  conflict exists. No fetch/merge is justified by these results.
- CI `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance
  gate independently of the passing Vulture scan.

Additional independent commands (1800-second timeout):

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes: 311 passed, 3 skipped in 1.60s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16467 nodes, zero duplicates |
| `git diff --check` | PASS |

## Acceptance audit and architecture reconciliation

Read repository `AGENTS.md`, quality-gates policy, accepted lifecycle
ADR-081226-a66b and trusted-base authority ADR-083126-5e62. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Staging permission is not
permission to override the protected-base oracle. The narrow Vulture repair
exception does not authorize reachability ledger/grant edits or a fake caller.

- **Immutable header/interfaces, strict named-field decode, signed timestamps,
  UUID hex storage, fresh flat encoding and typed/sanitized errors:** source
  inspection and focused contract tests pass, including mismatched headers,
  unknown formats, invalid scalars, schema omissions and error hygiene.
- **Exact v2 representation:** three-state round-trip test passes. Independent
  SQL-shape assertions at `test_admission_codec.py:134-137` check both binding
  fields; `admission_identity.py:291-292` rejects receipt disagreement. This
  is contract evidence, not a newly executed database CHECK proof.
- **Legacy identity must not be guessed:** bound/unbound/partial, receipt-only,
  unreadable evidence and bound-pair-without-receipt tests pass. The latter
  remains a typed partial disposition because the prerequisite binding DTO
  requires receipt identity; inventing a receipt would violate the contract.
- **Header/full-record separation:** expiry and fingerprint preservation tests
  pass despite corrupt snapshot or partial binding. Inclusive expiry and 409
  precedence belong to the later consumer and are not asserted as B2 behavior.
- **Snapshot integrity:** malformed/duplicate/nonobject/bare-nonfinite, lossy
  numeric, excessive nesting and invalid Unicode tests pass with valid controls.
  Tagged snapshot/fingerprint pass-through tests pass. Original-model
  fingerprinting through production evidence-json and `model_of`/`model_of_json`
  materialization remains UNVERIFIED: handwritten tags and a fixed fingerprint
  in these fixtures cannot prove that end-to-end boundary.
- **Real raw/production pools and migrated schema:** UNVERIFIED this round.
  Three cases skip at `test_admission_codec.py:470` because both required DSNs
  are absent. No migration/downgrade, DB session identity, final SQL counts,
  object-valued Run JSONB INSERT or real authorized principal/Workspace/Project/
  Graph admission proof is claimed. Stop at the mandatory gate blocker rather
  than treat skipped PG tests or previous runs as current durability evidence.
- **Reachable production behavior:** absent. Source import search finds only
  the codec importing the identity module and the Vulture whitelist importing
  its enum. Codec lines 50-53 explicitly say no production consumer exists.
  This is allowed pure staging but not production acceptance or mergeability.
- **No activation/authority expansion:** codec reads mappings and emits DTOs or
  mappings, with no clock, SQL mutation, HTTP/queue mapping or claim decision.
  This round makes no source change and selects no unresolved parent policy.
- **Integration validation:** focused tests/static checks/inventory pass, but
  provenance fails. Full integration CI is UNVERIFIED. The generic `test:
  failure` remains unattributed and was not reproduced by the focused suite;
  no candidate-qualified failing traceback was supplied in the lane brief.
- **Coordination:** assigned base/head verified; broader integration ownership
  and activation authorization remain UNVERIFIED. No mutation/pre-fix failure
  is claimed because this round has no code repair.

## Handoff

Verdict: BLOCKED. Only changed file is this evidence note; no tests added or
changed, so no inventory delta is necessary. Existing source, tests and ledgers
are preserved. Commit locally, without push or GitHub mutation.

Blocking evidence: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`; the required provenance gate
rejects both module identities and dispositions against the supplied base.
Resolution needs an owner-approved integration base/real consumer consistent
with #1845. A separately landed authorization would also need owner
reconciliation with #1893's explicit no-grant constraint; this worker cannot
self-authorize it. Provide changed trusted-base evidence and a
candidate-qualified test traceback before another repair dispatch on this
unchanged code. Do not repeat validation-only repairs on identical inputs.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
Next: owner resolution of the blocked integration boundary, not a local bypass.
