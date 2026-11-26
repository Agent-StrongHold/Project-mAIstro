# Issue #1893 — exact-debt-ledger CI repair round at 0eacd9a4

**BLOCKED on the reachability two-merge wall; the named vulture ledger has
nothing to fix.** The `exact-debt-ledger` job failure was reproduced locally at
the assigned head with CI's exact arguments and matched the hosted log. The job
fails at its FIRST step (`scripts/check-ratchet-provenance.py`) on the
reachability/dispositions provenance gates; the vulture step the repair brief
names is never reached and passes exactly on its own.

## Scope and architecture

- Only issue #1893, worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`,
  starting head `0eacd9a447d2a24ce293887aecc288ae463206a7` (clean at start and
  unchanged except this report).
- Base `ab8b3737fa64f8d840f421ef87ca506c509444ff` = local
  `refs/remotes/origin/develop` (verified after `git fetch origin`; the remote
  ref did not move). `git merge-base HEAD origin/develop` = `ab8b3737…`, i.e.
  the branch already contains the develop tip; no sync or merge is pending.
- Canonical execution model (`Goal -> Graph -> Run -> NodeRun -> Attempt`)
  untouched; B2 stays an inactive contract leaf (no production import, no
  `_assess` change). Commit `29e3be4`'s wiring attempt remains reverted by
  `0eacd9a4`.

## Root cause (actual evidence, not scanner guesswork)

Hosted CI run 39034419822 job 117401264829 (read via `gh run view --log-failed`,
read-only) fails `exact-debt-ledger` at "Require enforced ratchet provenance
policy" with, verbatim:

- `FAIL: reachability dispositions moved away from trusted state`
  - `maistro.runs.admission_identity: NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization`
  - `maistro.tasks.admission_codec: NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization`
- `FAIL: reachability ratchet moved away from trusted state`
  - same two identities: `NEW unreachable module absent from trusted base and not previously authorized`
- `FAIL: ratchet provenance inventory is incomplete` (the two sub-gates above)

Local reproduction at `0eacd9a4` with `RATCHET_BASE_REV=ab8b3737…` is identical.

Mechanism: the #1893 reachability authorization for these two identities was
added in-branch (commit `6af21c54e`, `quality/ratchet-authorizations.json`) and
is banked in the candidate `reachability-baseline.json` /
`reachability-dispositions.json`. Both gates read authorizations from the merge
base via `ratchet_provenance.load_authorizations(RATCHET, base=trusted_ref.base_sha)`
(`scripts/check-reachability-provenance.py` line 64), so the in-branch grant is
deliberately invisible — the documented two-merge rule (AGENTS.md,
docs/quality-gates.md: "a floor raise takes two merges"). `--update`, candidate
ledger edits, or disposition edits cannot change the verdict by design.

## Why no in-tree repair exists

1. **Vulture (the brief's named target): no unbanked identities.**
   `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` → `1322 reviewed identities
   -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`, exit 0. There is
   no dead code to remove and no row to add or prune; amending
   `quality/vulture-baseline.json` would be a no-op fabrication.
2. **Deleting the two modules** would destroy the B2 deliverable the issue
   mandates (`admission_codec.py` is the leaf's required file;
   `admission_identity.py` is the #1851 DTO stack it decodes into; all 10
   prospective tests exist and pass).
3. **Wiring the modules into production** to make them reachable violates the
   issue's own constraints (B2 is inactive by design; "C is the consumer";
   "no baseline/grant/gate modifications to make an unwired slice green") and
   was already tried and reverted at `29e3be4`/`0eacd9a4`.
4. **Editing reachability ledgers/dispositions/grants in-tree** is prohibited
   for this lane outside the vulture exception, and would not pass anyway
   (authorization is read from the base, not the candidate).

Required unblock (outside this worktree's authority — no GitHub mutations are
permitted from a worker): land the #1893 reachability authorization for
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec` on develop
via a separate reviewed PR (it already exists verbatim in this branch at
`6af21c54e` for review), then merge develop into `auto-1893`; both gates then
see the authorization at the merge base. Owner alternative: schedule the C leaf
consumer so the modules become genuinely reachable instead.

## Executed checks (this round, head `0eacd9a4`)

| Command | Result |
| --- | --- |
| `uv sync --locked --all-extras` | OK (matches CI job env) |
| `git fetch origin` (read-only) | `origin/develop` unchanged at `ab8b3737…` |
| `uv run python scripts/check-ratchet-provenance.py` | **FAIL** — exactly the two reachability identities above; every other ratchet (adr-status-language, citation-status, promotion-surface, shell-execution, contract-markers, enumerations, lifecycle) OK with no candidate-approved expansion |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS — 1322 == 1322 exact, 0 unclassified, 0 unbanked |
| `uv run python scripts/check-reachability-provenance.py` | FAIL rc=1 (the two identities) |
| `uv run python scripts/check-reachability-dispositions-provenance.py` | FAIL rc=1 (the two identities) |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_idempotency.py -q` | 268 passed, 3 skipped |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3301 files) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS (2 source files) |
| `gh run view 39034419822 --log-failed` (read-only) | Hosted failure = local failure, same step, same identities |

## Acceptance status for the B2 leaf (unchanged by this round)

- Public codec surface matches the issue spec exactly (`AdmissionDecodeCode`,
  `AdmissionRowDecodeError(ValueError)`, frozen `AdmissionRowHeader`,
  `decode_admission_header`, `decode_admission_record`, `encode_admission_record`).
- All 10 prospective test names from the issue body are present in
  `packages/maistro-core/tests/tasks/test_admission_codec.py` and pass; driver
  checks for this job (ruff, format, focused pytest 346 passed / 3 skipped,
  suite inventory 16567 identities) are green.
- No SQL mutation, HTTP mapping, or queue change exists in the diff.
- Hosted required checks and integration acceptance remain separate gates; the
  reachability provenance wall is a merge-readiness blocker, not a correctness
  finding against the leaf.
