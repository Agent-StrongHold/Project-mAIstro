# Issue #1893 — exact-debt-ledger CI repair round at a8475eeb (develop-synced to eec7a587)

**Verdict: still blocked on the reachability two-merge wall; the named vulture
ledger again has nothing to fix.** This round re-proved the diagnosis at the
current develop tip after syncing the branch forward, with the vulture scan
exact at 1322 == 1322 and every other provenance ratchet green except the two
inactive-contract-leaf identities that require an owner-side grant.

## Scope and state

- Only issue #1893, worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Round start `a8475eeb7f2c` (clean; the tree at that head was left untouched —
  diagnosis only). `origin/develop` fetched read-only: unchanged at `eec7a587039`,
  the assigned base. The branch's previous merge had taken develop only to
  `9a4b0c5cc0fc` (17 commits behind, no file-level overlap with this branch, so
  the sync merge was conflict-free): merged as `19441d8f80cf` (#2173, #2157,
  #2161, #2199, #2171, #2166, #2164, #2206, #2202, #2159 and dependency bumps).
- **Ledger-integrity audit of the merge (AGENTS.md row-loss rule).** Every
  `quality/*.json` was compared index-free (multiset-preserving row walk, no
  list indices in keys) across branch tip `5872906d3`, develop tips
  `9a4b0c5cc`/`eec7a587`, and the merge result: **zero rows lost from either
  side in every file**, including the `vulture-baseline.json` multiset. An
  initial audit pass that keyed rows by list index reported 43 phantom "lost"
  develop rows in `reachability-baseline.json`; that was recognized as an
  index-shift artifact of the audit method and corrected before any edit was
  made. No quality file was modified by this round.
- The gh API rate-limit that blocked the previous round's preflight was avoided:
  all evidence here is from `git fetch`/local gate runs, no GitHub API calls.

## Gate diagnosis at the merged head, CI's exact arguments

`exact-debt-ledger` (`.github/workflows/vulture-ratchet.yml`, unchanged on
develop since the merge base) runs three steps in order:

1. `uv run python scripts/check-ratchet-provenance.py` — **FAIL (exit 1)**.
   Every ratchet inside it reports no candidate-approved expansion (ADR status
   language, citation-status, promotion-surface 272 modules, shell-execution,
   contract-markers 358, enumerations, lifecycle: all OK), except:
   - `reachability dispositions`: `maistro.runs.admission_identity` and
     `maistro.tasks.admission_codec` — "NEW disposition absent from trusted
     ledger and not covered by an already-landed reachability authorization";
   - `reachability`: same two identities — "NEW unreachable module absent from
     trusted base and not previously authorized" (169 trusted unreachable ->
     171 of 1413 candidate modules).
2. `uv run python scripts/check-shipped-surface-truth.py` — PASS.
3. `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` — **PASS, exact**:
   1322 reviewed identities -> 1322 findings, `unclassified: 0`,
   `never_allowlist: 0`. The brief's named target (vulture per-identity
   ledger) has no unbanked identity at either this head or the round-start
   head; amending `quality/vulture-baseline.json` would fabricate rows, and
   deleting nothing is possible because nothing is dead.

Root cause unchanged and re-verified in source: `load_authorizations`
(`scripts/ratchet_provenance.py:600`) reads `quality/ratchet-authorizations.json`
**from the base revision** deliberately — "a new grant does not take effect in
the change that introduces it… two merges." The #1893 grant for the two
identities exists verbatim in this branch (commit `6af21c54e`) and in the
candidate ledgers/dispositions, but the merge base `eec7a587` carries no
`admission_identity` authorization (`git show origin/develop:...` grep = 0), so
the gates correctly refuse candidate-approved self-authorization. Deleting the
candidate ledger rows instead would not help: the modules would then be *new
unreachable modules with no disposition at all*, a strictly worse state.

## Why no in-tree repair exists (unchanged from the 0eacd9a4 round, re-proven)

1. **Vulture: nothing unbanked** — exact at both heads (above).
2. **Wiring the modules into production** to make them genuinely reachable
   contradicts the B2 leaf's own exit constraints ("C is the consumer"; no live
   `_assess` change) and the issue's "no baseline/grant/gate modifications to
   make an unwired slice green". The prior attempt (`29e3be4`, an unused-import
   hack in `idempotency.py`) was reverted at `0eacd9a4`; repeating it is not a
   repair.
3. **Ledger/disposition/grant edits in-tree cannot change the verdict** — the
   authorization is read from the merge base by design, and this worker holds
   no GitHub mutation authority to land the grant on develop.

Required unblock (owner-side, outside this worktree): land the #1893
reachability authorization for `maistro.runs.admission_identity` +
`maistro.tasks.admission_codec` on develop via a separate reviewed PR (drafted
verbatim at `6af21c54e`), then merge develop into `auto-1893`; both sub-gates
then see the authorization at the merge base. Alternative: schedule the C-leaf
consumer so the modules become genuinely reachable, then drop the candidate
ledger rows.

## Executed checks (this round, head `19441d8f80cf` unless noted)

| Command | Result |
| --- | --- |
| `git fetch origin` (read-only) | `origin/develop` = `eec7a587039…`, unchanged |
| `git merge origin/develop` | conflict-free; merge commit `19441d8f80cf` |
| index-free multiset audit of all `quality/*.json` (3 refs) | 0 rows lost either side, all files |
| `uv run python scripts/check-ratchet-provenance.py` | **FAIL** — exactly the two reachability identities; all other ratchets OK, no candidate-approved expansion |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS — 1322 == 1322, 0 unclassified, 0 never_allowlist (also PASS at round-start head `a8475eeb7f2c`) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (3327 files) |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -q` | 201 passed, 3 skipped |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/a2a packages/maistro-core/tests/extensions/test_sandbox_runner.py -q` | 2278 passed, 310 skipped (includes develop-merged sandbox/a2a suites) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py packages/maistro-core/src/maistro/sandbox` | PASS (16 source files) |
| `uv run python scripts/check-suite-inventory.py` | PASS — 17 suites, 32066 unique identities, matches recorded inventory (no test additions this round, so no inventory delta) |

## Acceptance status for the B2 leaf

Unchanged by this round: public codec surface matches the issue spec; all 10
prospective test names present and passing; no SQL mutation, HTTP mapping, or
queue change in the diff; the canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` model and the #1841 security signature untouched. The reachability
provenance wall is a merge-readiness blocker requiring an owner-side grant,
not a correctness finding against the leaf.
