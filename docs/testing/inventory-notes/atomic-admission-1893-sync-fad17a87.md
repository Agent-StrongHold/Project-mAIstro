---
inventory-delta:
  packages/maistro-core/tests: +0
---
# atomic-admission-1893 — round-5 exact-debt-ledger re-validation, faithful CI-topology proof

Lane L1893, job `24028a249ff24a1ba0cc0b09d513db09`. Branch `auto-1893`.
Head `a253916fda8c5b85071a729d1f3a211bd7fc121f`, develop base
`fad17a87c34193a91c568eb8b0a910e8e6384ccd`. No source or ledger edits this
round — the round produced evidence only.

Dispatched CI failure: `exact-debt-ledger: failure`. That job
(`.github/workflows/vulture-ratchet.yml:30`) runs three steps; all three were
re-run at exact argv this round.

| step | command | result |
|---|---|---|
| vulture exact | `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS**, exit 0, `1321 reviewed -> 1321 findings`, `unclassified: 0`, `never_allowlist: 0` |
| shipped surface | `check-shipped-surface-truth.py` | **PASS**, exit 0 |
| provenance | `check-ratchet-provenance.py` | **FAIL**, exit 1, exactly the two #1893 modules |

## The brief's named repair path has no target

The lane brief scoped this round to "run `check-vulture-baseline.py` to list
unbanked identities ... and amend `quality/vulture-baseline.json`". That step
exits 0: there are **zero unbanked identities**, so there is nothing to bank,
nothing to delete, and no reviewed-retained identity to amend. Amending the
ledger here would have been a cosmetic edit unconnected to the failure. The
accounting is exact on both sides — the candidate ledger and the scan agree at
1321 — so the failing step is provenance, not vulture. `quality/` was left
untouched.

## What actually fails, at the develop base

`RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
exits 1 on four lines, one root cause:

```
FAIL: reachability dispositions moved away from trusted state
  - maistro.runs.admission_identity: NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization
  - maistro.tasks.admission_codec: NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.tasks.admission_codec: NEW unreachable module absent from trusted base and not previously authorized
```

The mechanism is `scripts/check-reachability-provenance.py:110`
(`authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`)
reaching `scripts/ratchet_provenance.py:626`, where `load_authorizations` calls
`resolve_baseline(..., base=...)`. Both the trusted ledger and the grant file
are read **at the base revision only**. A grant cannot authorize the change
that introduces it — the documented two-merge rule. The two modules are
unreachable *by design*: #1893's exit is "typed representation only", the
consumer is leaf C, and the issue forbids activation, production import and
`live _assess` change. So no in-branch source edit can honestly satisfy this
step, and the only gate-weakening escapes are forbidden.

## Correction to prior rounds' proof

Earlier rounds proved the escapes by
`RATCHET_BASE_REV=6af21c54e` (a branch ancestor) and reported "grant-first
proof: exit 0". **That proof was conflated.** At `6af21c54e` the branch's *own*
`quality/reachability-baseline.json` already listed both modules:

```
git show 6af21c54e:quality/reachability-baseline.json -> 171 unreachable, both present
```

so `added = current - trusted` was empty and the gate passed by baseline
**self-blessing**, never touching `load_authorizations`. It did not demonstrate
that the grant authorizes anything.

A faithful simulation also cannot be built by naming a non-ancestor commit:
`resolve_baseline` clamps to `merge-base(base, HEAD)`
(`scripts/ratchet_provenance.py:319`), and a local worktree that has not merged
the post-grant develop always collapses to the old merge point. This round
therefore built the real CI topology in a throwaway clone (the assigned
worktree was never modified):

1. `simdevelop2 = fad17a87c + git cherry-pick -x 6af21c54e` → `49147ecaa`,
   applying **cleanly, zero conflicts** (+10 grant lines, +86 note lines, and
   crucially `quality/reachability-baseline.json` at `simdevelop2` still has
   **0** admission rows).
2. `simcand = merge(simdevelop2, a253916f)` → the synthetic base+candidate
   merge GitHub checks out, with `git merge-base simdevelop2 HEAD ==
   49147ecaa` — i.e. the merge base *is* the named base, exactly the CI
   condition.

Result:

```
RATCHET_BASE_REV=simdevelop2 check-ratchet-provenance.py -> EXIT 0
OK: 170 unreachable module(s) have dispositions; new debt uses prior reachability authorization
OK: 170 unreachable module(s), no candidate-approved expansion
  authorized: maistro.runs.admission_identity: #1893 -- @BlakeMatthews-dev: ...
  authorized: maistro.tasks.admission_codec:    #1893 -- @BlakeMatthews-dev: ...
... 10 ratchets OK, 53 quality JSON consumers with explicit provenance
```

Because the base baseline held zero admission rows, `added` was the two
modules and the pass came from `load_authorizations` — the grant was genuinely
exercised. **The sole remaining ingredient is the owner-side landing of the
grant commit on develop, and it is a clean cherry-pick of `6af21c54e` with no
source or baseline rows attached.**

## Deliverable re-verified this round (not taken on trust)

- All ten prospective tests named in the issue body exist in
  `packages/maistro-core/tests/tasks/test_admission_codec.py` (one definition
  each).
- Interfaces match the issue text exactly: `AdmissionRowHeader` is
  `frozen=True, slots=True` with the six named fields and
  `format_version: Literal[1, 2]`; `decode_admission_header`,
  `decode_admission_record(*, header)`, `encode_admission_record`; the six
  `AdmissionDecodeCode` values; `AdmissionRowDecodeError(ValueError)` carrying
  `code` and a validated-hex-only `scope_key`.
- Exit constraints hold in source: no `time`/`datetime`/`random` import, no
  `execute`/`INSERT`/`UPDATE`/`DELETE`/`commit`, and 25 `raise ... from None`
  chain suppressions.
- Independent probes (in-process, no file edits) confirmed fail-closed
  behaviour rather than trusting the suite: `format_version` of `3`, `"2"` and
  `True` all yield `unsupported_format` (a bool never launders into format 1);
  `created_at` of `True` and `1.0` and an int64 overflow yield
  `invalid_header`; missing header columns yield `unsupported_schema`; a
  header disagreeing with the row yields `invalid_header`; an unvalidated
  scope yields `scope_key=None`; partial legacy pairs (`task_id`-only,
  `run_id`-only) yield `partial_legacy_binding` while unbound stays
  `LegacyAdmissionRecord(binding=None, admitted=False)` and a bound pair
  without `receipt_id` fails closed as "bound pair without receipt identity".

## Validation executed

| command | result |
|---|---|
| `uv run ruff check .` | PASS, "All checks passed!" |
| `uv run ruff format --check .` | PASS, 3364 files already formatted |
| `uv run pytest` codec + identity `-q` | **201 passed, 3 skipped** (skips = DSN-gated PG legs at `test_admission_codec.py:470`) |
| driver's five-file battery | **346 passed, 3 skipped** |
| live PG: fresh `pgvector/pgvector:pg18`, new DB, `alembic upgrade head` to `063`, `MAISTRO_REQUIRE_PG_LEGS=1` | **204 passed, 0 skipped** — durable round-trip and raw-vs-production-pool equality proven, including `test_raw_and_production_pool_codecs_read_identical_text_snapshots` |
| post-run row hygiene on that DB | `task_idempotency` 0, `canonical_runs` 0, `canonical_attempts` 0 |
| `git diff --numstat origin/develop HEAD -- quality/` | `10/0`, `2/0`, `11/0` — purely additive, no row loss |

The disposable container and database were dropped after the run; the
throwaway simulation clone was removed. No PG or SQLite substitute is counted
as durability evidence.

## What a worker cannot do here

Landing the grant on develop requires a push and a merge, which this lane
forbids. Nothing in the branch is wrong; the gate is sequenced one merge
ahead of it. Round outcome: **BLOCKED on the owner-side grant landing** —
actionable as a cherry-pick of `6af21c54e` onto `fad17a87c`, after which this
candidate's `exact-debt-ledger` goes green by authorization, as proven above.
