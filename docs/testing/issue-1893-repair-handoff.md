# Issue 1893 repair checkpoint

## Frozen scope

- Sole item: issue #1893; assigned worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `1797e5dafc7ac4c325391a8dfb6bd574796785ab` (verified); clean on entry.
- Supplied develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Evidence: supplied job `a6d570bc758046e68d13c9d34f80d335`, its five check logs,
  dispatch context, and prior result `ddf0c26e5c0f4e40a10fbdf79eafa594`.
- Inspection scope: admission codec, admission identity DTOs, adjacent tests,
  existing atomic-admission inventory notes, relevant ADRs and CI definitions.
- Modification scope: this report; codec/tests/inventory only if a reproduced defect
  requires repair. Vulture ledger edits only for reproduced retained identities.
  No reachability/grant/gate changes, activation, or GitHub mutations.

## Initial evidence and assumptions

- The supplied head resolves and matches the worktree; no salvage is necessary.
- The initial combined inspection output was truncated; its diff output cannot
  support a no-delta claim. Verified merge base is the supplied develop base,
  which also matches the local `origin/develop` ref. No sync conflict is present.
- The issue explicitly stages a pure codec, forbids activation, and leaves runtime
  policy to other leaves. Pure codec correctness is not production activation proof.
- An initial instruction-file search accidentally traversed sibling directory names;
  no sibling contents were read or modified. Further inspection is confined to the
  assigned worktree and supplied job artifacts.
- Reported `test: failure` has no traceback in the prompt. Reproduce from captured
  evidence rather than making speculative repairs.

## Checkpoint: reproduced blocker

- Read supplied `check-0.log` through `check-4.log`: dependency sync, lint,
  format and scoped inventory passed; selected tests reported 346 passed,
  3 skipped. Those skipped PostgreSQL legs are not durability evidence.
- Independently ran exact Vulture command: exit 0, 1322 reviewed findings,
  zero unclassified/never-allowlist findings (`/tmp/1893-a6d5-vulture.log`).
  No Vulture ledger amendment is justified.
- Independently ran `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb
  uv run python scripts/check-ratchet-provenance.py`: exit 1. Both admission
  modules introduce unauthorized unreachable modules and dispositions against
  that trusted base (`/tmp/1893-a6d5-provenance.log:20-29`). This reproduces
  the prior blocker; it is not a Vulture identity mismatch.
- Codec/identity tests: 201 passed, 3 skipped (`/tmp/1893-a6d5-focused.log`).
- Accepted ADRs 081226-a66b, 082826-b601 and 083126-5e62 preserve one execution
  spine, explicit consumer eligibility and trusted-base authority. Adding fake
  imports or changing reachability policy to pass this lane would violate them.
- A guessed prior-note filename `atomic-admission-b2-repair-ddf0.md` was not
  found; skipped. The supplied prior result artifact was read successfully.

## Final validation at the starting source SHA

All commands ran in the assigned worktree using `uv run`, with 1800-second
validation timeouts. Log prefix below is `/tmp/1893-a6d5-`.

| Command | Executed result / artifact |
| --- | --- |
| `uv run ruff check .` | PASS (`ruff.log`) |
| `uv run ruff format --check .` | PASS, 3301 files (`format.log`) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files (`mypy.log`) |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 1919 passed, 310 skipped, 6 SQLite thread/event-loop warnings (`adjacent.log`); no PG configured for this run |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (`shipped.log`) |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16567 nodes, no duplicate evidence (`inventory.log`) |
| `git diff --check` | PASS |

The exact Vulture and failing provenance commands/results are recorded above.
No source or test changes were justified; test inventory delta is zero, and no
inventory/baseline/grant/gate file was changed.

### Real PostgreSQL boundary

Confirmed the database name absent, then `createdb maistro_1893_a6d570bc` and
`DATABASE_URL=postgresql:///maistro_1893_a6d570bc uv run alembic upgrade head`:
PASS, real chain 001 through 063 including migration 055 (`migration.log`).
Server: PostgreSQL 18.6 (`pg-version.log`). This dedicated disposable database
is retained for inspection; no shared database was migrated or truncated.

With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
`postgresql:///maistro_1893_a6d570bc`, and `MAISTRO_REQUIRE_PG_LEGS=1`, ran:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-a6d5-focused-pg.xml
```

Result: **204 passed, zero skipped** (`focused-pg.log`). Both pools used the
same database over the local Unix socket. Production/raw backend PID pairs:
unbound 3686227/3686228; bound 3686229/3686230; acknowledged 3686231/3686232.
Each case observed one persisted admission row through independently connected
production-codec and raw pools. Tests assert actual bound INSERT storage shape,
identical TEXT/DTO round trips and typed rejection of escaped lone surrogates
in each snapshot column. Final direct SQL: revision 063, **0 admission rows,
0 distinct generations, 0 distinct Run identities** (`final-sql.log`).

Mutation control: in a separate Python process, replaced only the in-memory
encoder with a wrapper that forces `task_id=None`, then ran the unchanged
`test_v2_round_trip_preserves_all_snapshot_bytes[bound]`. It failed exactly at
`test_admission_codec.py:134` (`None != 'rcpt-1'`, pytest exit 1), as expected
(`mutation.log`). No on-disk source was mutated. This shows the storage assertion
would catch the prior paired-binding defect rather than merely agreeing with a
similarly broken decoder.

## Acceptance accounting

All test names below belong to the executed codec file, unless stated otherwise.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header; strict scalars, required columns and supported formats | Source `admission_codec.py:157-233`; unknown-format, missing-column, invalid-scalar and scalar-mismatch tests passed |
| Header/full-record separation without clock or mismatch decisions | Expired-header, malformed-snapshot, partial-binding fingerprint and inverted-scalar tests passed; header remains unchanged after full decode failure |
| Exact v2 record, fresh SQL mapping and original binding | Three-state round trip, fresh-flat-mapping and binding-corruption tests passed; real migrated INSERT/SELECT; mutation control above |
| Owner/generation UUID .hex storage, no identity invention | Owner-token and strict-generation tests passed; DTO validation rejects nil/malformed identifiers |
| Bound/unbound/partial legacy evidence distinct | Legacy binding, receipt-only, missing receipt, unreadable/whitespace evidence and ignored completed-at tests passed; no inferred receipt or Run |
| Typed failures, safe errors and validated hash scope | Invalid JSON, nesting, lossy numbers, invalid Unicode, scope and malformed-header tests passed; parsing chains suppressed |
| Strict object JSON; preserve permitted tagged context and fingerprint | Duplicate/nonobject/nonfinite rejection, tagged-nonfinite and exact-number/Unicode round trips passed; no fingerprint recalculation in codec |
| TEXT independent of pool JSON codecs | All three real raw/production-pool cases passed on one migrated DB; non-null pg_pool enforced |
| Representation only; unchanged runtime assessment, HTTP, queue and execution authority | Source inspection: mapping/DTO functions only; this round changes documentation only |
| Production reachability | NOT established: production-source search finds only codec-to-DTO import plus Vulture whitelist, no runtime codec consumer; trusted-base reachability gate FAILS |
| Model materialization via evidence-json/model_of, authorized principals/Workspace/Project/registered Graph, Run JSONB object insertion | UNVERIFIED by these tests. Fixtures are synthetic codec records, not real authorized admission or canonical Run materialization |
| Full unchanged integration CI, expiry/409 consumer precedence, activation policy and coordinated integration ownership | UNVERIFIED; no activation or parent/issue closeout claimed |

## Reported CI failure and disposition

The supplied captured check-runs for PR #1945 head
`80171ce1cff9ca45eaf000bf52569875643a5ba0` report `test: success` and
`exact-debt-ledger: failure`, with no failure traceback in their output fields.
That is a different SHA from this worktree and is not current-head proof.
The prompt's unspecific `test: failure` was not reproduced by this round's
focused/adjacent runs; full hosted CI remains unverified. No unrelated test or
scanner change was guessed to address it.

**BLOCKED**: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` remain unauthorized against the
frozen base. The lane exception permits only justified Vulture ledger repairs,
not reachability policy changes. Passing storage tests cannot fix this policy
blocker. This round cannot land the required independent trusted-base decision,
merge into develop, or activate the consumer. No merge conflict exists to repair.

Changed file: this report only. No source defect reproduced or speculative
repair applied. Local commit is a blocked handoff, not integration approval.
Progress: checked 1, done 0, skipped 0, errors 1 (trusted-base provenance gate).
Next: obtain the authorized integration/base decision outside this lane, and
supply the exact failing `test` SHA/traceback if that separate failure persists.


