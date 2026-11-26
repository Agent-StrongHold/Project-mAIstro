# Issue #1893 — bounded repair check (job 523dc851)

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `95c3e771fe4c9dcaad84595209e44601c9f239ad`, supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`; initial worktree clean.
- One item: #1893 admission codec repair. Inspect the supplied dispatch snapshot,
  driver check-0..4 logs, prior result 4336b2aa, codec and identity modules and their
  adjacent tests, relevant ADRs, CI gate definitions and existing ledger evidence.
- Potential source changes restricted to the codec/identity modules and adjacent
  tests if a defect is reproduced; this report records validation otherwise.
  Vulture ledger exception applies only to actual retained unbanked identities.
  No reachability ledger/grant edits, policy changes, production activation or
  unrelated repairs are authorized.
- Ambiguity: `test: failure` has no command/traceback in the assignment. Treat it
  as unproven pending supplied logs and focused reproduction, not permission to
  guess repairs. Previous gate success claims are not current evidence.

## Progress

- Confirmed exact starting HEAD and clean worktree; no salvage needed.
- Read issue body in supplied dispatch snapshot. B2 is explicitly staged and
  cannot introduce a live consumer or infer legacy identity. Reachability grants
  require an already-landed authorization, not candidate policy edits.
- Supplied driver logs: sync, Ruff, format and inventory pass; focused tests
  report 346 passed / 3 skipped. No failing traceback is supplied.
- Fresh exact Vulture command passed: 1322 reviewed identities / 1322 findings,
  zero unclassified findings. No ledger amendment is justified.
- Fresh `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run
  python scripts/check-ratchet-provenance.py` failed (exit 1): two unauthorized
  unreachable modules and two unauthorized dispositions, for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  The supplied base resolves and is the actual merge base. Logs are
  `.pytest_cache/repair-523dc851/{vulture,provenance}.log`.
- Read accepted ADRs 081226-a66b, 082526-7f02, 082826-b601 and 083126-5e62.
  Reconciliation: preserve immutable provenance and canonical execution; do
  not create fake runtime imports or activate an unapproved consumer to pass
  reachability. Candidate banking cannot authorize its own debt. The Vulture
  exception does not permit reachability grants or policy changes.
- Confirmed blocker cannot be repaired within this lane. Finished bounded
  focused validation rather than repeating the failing gate.

## Fresh validation at the starting source SHA

All commands received 1800-second timeouts. Logs are under
`.pytest_cache/repair-523dc851/` (local ignored artifacts).

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 identities (`vulture.log`) |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1, reachability and dispositions (`provenance.log`); other subchecks passed |
| `uv run ruff check .` | PASS (`ruff.log`) |
| `uv run ruff format --check .` | PASS, 3301 files (`format.log`) |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files (`mypy.log`) |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 349 nodes: 346 passed, 3 skipped (`focused.log`) |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 2229 nodes: 1919 passed, 310 skipped, 5 aiosqlite closed-event-loop thread warnings (`adjacent.log`) |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16567 nodes, no duplicate evidence (`inventory.log`) |

No source or tests changed; test inventory delta is zero, so no new inventory
note is needed. No new mutation test or regression repair is claimed. The
existing tests inject malformed storage TEXT, scalar/header mismatches and
partial identity pairs; the binding-pair assertions at
`test_admission_codec.py:134-137` independently constrain encoder output.

## Acceptance evidence and limits

Evidence below is library contract evidence, not reachable production admission.
The production import search finds only codec-to-identity and Vulture-whitelist
imports; `admission_codec.py:50-53` explicitly describes the absent consumer.

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header, named columns, strict format/scope/fingerprint/signed timestamps | Inspected `admission_codec.py:157-233`; fresh invalid-scalar, unknown-format and missing-column tests pass. |
| Supplied header matches row scalar fields before full decoding | Fresh scalar-mismatch and format tests pass; full decode re-derives the header. |
| Exact immutable V2 records, fresh flat encoding, UUID `.hex` at storage only | Fresh three-state round trips, UUID/token, fresh-mapping and identity immutability tests pass. |
| Legacy bound/unresolved/partial, receipt-only and announced-without-Run remain distinct; no invented identities | Fresh legacy pair, missing receipt, receipt-only, unreadable/whitespace and completed-at tests pass. |
| Header preserves expiry/fingerprint despite malformed snapshot or partial binding | Both named header-preservation tests and expired-header test pass. Codec takes no clock or incoming fingerprint and makes no admission assessment. |
| Six typed decode codes, validated scope only, safe error messages/chains | Source enum/error inspection plus fresh malformed JSON, nesting, numeric, Unicode, token and scope tests pass. |
| Reject duplicate/nonobject/bare nonfinite JSON; preserve tagged evidence and stored fingerprint | Fresh strict JSON, tagged-nonfinite, exact numeric and Unicode tests pass. No fingerprint recalculation in codec. |
| Existing evidence-json/model_of materialization, original-model fingerprinting, arbitrary permitted program_context | UNVERIFIED end-to-end: fixture snapshots are synthetic and fingerprint is predetermined; tests prove tagged TEXT preservation, not production model integration. |
| Both raw and production pools against real migrated disposable PG; TEXT parameters and JSONB Run object shape | UNVERIFIED this round: three real-pool tests skipped because both DSNs are unset. No DB session identities or SQL counts claimed; prior job's PG claims were not adopted. |
| Explicit authorized principals, Workspace/Project and valid registered Graph | UNVERIFIED: codec fixtures do not establish authorized canonical admission. |
| No SQL/HTTP/queue/assessment/scope-policy changes; canonical execution remains sole authority | Inspected codec is Mapping/DTO conversion only; this round changes only this report. No activation or alternate authority added. |
| Inventory/lint/format/mypy and integration gates | Focused checks pass above; trusted-base provenance fails. Full unchanged integration CI and remaining standalone gates UNVERIFIED this round. |
| Production reachability and coordinated staged integration readiness | BLOCKED by unauthorized unreachable modules/dispositions; no wiring claim. Consumer expiry/409 ordering and activation remain outside B2. |

## Disposition / next input

**BLOCKED.** `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` introduce the two modules
without trusted-base authorization. `.github/workflows/vulture-ratchet.yml:77`
requires the failing provenance gate before Vulture. No Vulture ledger edit
can fix this failure, and changing the reachability policy is prohibited here.
There is no sync conflict at this head; no fetch/merge or GitHub mutation was
performed.

The reported hosted `test: failure` remains **UNRESOLVED**: neither supplied
logs nor fresh focused/adjacent runs reproduce it. A failing command, exact
SHA and traceback are needed before a source repair can be justified. Do not
redispatch this unchanged state as another Vulture repair: the integration
owner must first resolve the trusted-base dependency outside this lane.

Only changed file: `docs/testing/issue-1893-repair-523dc851.md`. This evidence
handoff must be committed locally; it is not integration or rollout approval.
Progress: checked 1, done 0 repairs, skipped 0 items, errors/blockers 1;
next: authorized integration decision and exact hosted test failure evidence.
