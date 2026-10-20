---
inventory-delta:
  tests/: +3
  packages/maistro-core/tests: +3
---

# auto-1859 — the API gate's temporary-disposition contract (#1859)

## Status: resolved on the owner-accepted exception contract, reconciled with develop `e20e9f52`

## The contradiction (characterized before anything changed)

At PR #1716 head `61913386e` — and still at this branch's original base
`faf93b2f0` — the gate contradicted itself: the checker documentation,
`docs/api/route-contract-inventory.md` and the registry `_comment`
advertised a registered `temporary` disposition (tracking issue + unexpired
review date) as the way a canned handler ships, `_check_registry` validated
those fields, but `main()` unconditionally failed every canned handler
without consulting its disposition, and its advice offered registration as
a pass that never existed. A synthetic full-gate run at that base with a
canned handler whose exact registry entry carried `disposition="temporary"`,
issue `#9999` and a future expiry exited **1** while the advice offered
"or register a temporary disposition" — recorded by the first attempt
(`8e6b74bb2`).

## Where the owner decision actually lives (the blocker, resolved)

#1859 asked the policy owner to state whether a temporary entry is
tracking-only-while-red or a narrowly governed exception, and to cite
accepted policy before changing acceptance behavior. The first attempt
looked in the issue threads and found nothing (#1859 carried no policy
comments; the only #1716 review is a Codex bot), so it shipped the branch
that cannot weaken #389 — tracking-only — and flagged the missing owner
statement as its blocker.

The statement exists in the repository instead of the threads: after that
attempt (commits `8e6b74bb2`/`8684ee504`, 2026-10-04 23:22–23:23 UTC) the
owner landed the decision through merged, CI-green PRs on this same gate.
All three are present in this round's base `e20e9f52`:

- **#1974** (merge commit `901b84f78`, merged 2026-10-05 11:30:29 UTC) —
  `_temporary_exempt_identities()`: a registry entry with
  `disposition="temporary"`, a tracking issue and an unexpired review date
  exempts that exact `(file, method, path)` identity from the canned
  findings, and `main()` passes it through. `docs/api/
  route-contract-inventory.md` documents the excuse. That is the narrowly
  governed **exact-route exception**, accepted and shipped on develop
  ~7 hours after the tracking-only attempt raced it.
- **#1976** (merge commit `94781cf6b`, merged 2026-10-05 05:44:50 UTC) —
  the excuse is pinned to the declared handler identity, so a wrong-identity
  entry cannot satisfy it.
- **#1975** (merge commit `9a5eb7ba6`, merged 2026-10-05 09:02:02 UTC) —
  the canned judgment scope was refined; the excuse applies to every
  detected handler class.

Provenance, stated exactly (a previous round of this note cited the three
merge SHAs as if all three sat on develop's first-parent history, which two
of them do not): `94781cf6b` **is** an ancestor of `origin/develop`;
`901b84f78` and `9a5eb7ba6` are not, because develop's history was later
re-squashed — their content reaches develop inside the squashed commit
`07fac4abd` (2026-10-17 18:45 UTC), the only commit in develop's history
that touches `scripts/check-api-route-contracts.py` or
`tests/test_check_api_route_contracts.py`
(`git log -S "_temporary_exempt_identities" origin/develop -- scripts/check-api-route-contracts.py`
and `git log origin/develop -- tests/test_check_api_route_contracts.py`
each return that commit alone). The merged PR states above are the
owner decision; the develop-side commits are where the content lives.

Accepted, merged develop state is the policy of record for this gate; the
#389 invariant stays intact because the excuse is per-identity, must expire,
and the shipped registry holds **zero** `temporary` entries (9 implemented /
5 unsupported-501 / 1 preview) — no canned route ships today.

## Reconciliation of this branch (this round)

- Merged develop `e20e9f52` into the branch (conflict-free: the develop
  delta touches five files — `.cursor/context/repair-1851-9ddea59d.md`,
  `docs/testing/inventory-notes/task-admission-identity-types.md`,
  `packages/maistro-core/src/maistro/runs/admission_identity.py`,
  `packages/maistro-core/tests/runs/test_root_admission_identity.py` and
  five added `quality/vulture-baseline.json` rows — and none of them
  overlaps the three surfaces this lane owns; `git merge-tree --write-tree`
  resolved cleanly and `git diff --numstat origin/develop -- quality/` is
  empty after the merge, so no ledger row was lost).
- The three non-test surfaces the tracking-only attempt had touched —
  `scripts/check-api-route-contracts.py`, `docs/api/route-contract-inventory.md`
  and `quality/api-route-contracts.json` — are **byte-identical to
  develop**: the tracking-only reversal is superseded by the owner-accepted
  exception contract it raced against. The registry `_comment` is develop's
  wording (it passes before expiry and refuses once expired — correct
  under the exception contract).
- `tests/test_check_api_route_contracts.py` is **develop's suite plus this
  lane's three new `main()`-level negatives** (`git diff origin/develop --
  tests/test_check_api_route_contracts.py` is +98 lines, additions only).
  It is not byte-identical to develop, and this note does not claim it is.
- This lane's surviving contribution: this decision record, the three
  `main()`-level negative proofs #1859 names that develop's suite still
  lacked (below), and the supply-chain repair recorded further down. The
  9 tracking-only tests from the first attempt were withdrawn together with
  that contract.

## Acceptance mapping (#1859)

- **Owner-approved contract** → the exception branch, per merged develop
  #1974/#1976/#1975 in base `e20e9f52` (cited above); not silently relaxing
  #389: no temporary entry exists in the registry, and the excuse is
  exact-identity and expiring.
- **Exception applied end to end, negatives still fail** → develop's suite
  proves at `main()` level: valid temporary entry passes
  (`test_registered_valid_temporary_disposition_excuses_logging_only_handler`,
  `main() == 0`), expired does not, unregistered/logging-only does not,
  handler-identity drift fails alone; this lane adds the three named
  negatives that were still missing at `main()` level — missing tracking
  issue, unparseable review date, and a fully valid entry registered under a
  foreign `(file, method, path)` identity, which excuses nothing (the
  exact-route keying is the #389 guard against a broad exemption).
- **No new exemption instance or closure claim** → registry byte-identical
  to develop; zero `temporary` entries; nothing here closes #389.

## Root-suite delta (+3, `tests/test_check_api_route_contracts.py`)

- `test_main_temporary_disposition_without_issue_does_not_excuse` — a
  temporary entry with no tracking issue: registry failure ("needs an
  issue") and the canned finding both fire, `main() == 1`.
- `test_main_temporary_disposition_with_malformed_date_does_not_excuse` —
  an unparseable review date: registry failure ("unparseable expires") and
  the canned finding both fire, `main() == 1`.
- `test_main_temporary_disposition_under_foreign_identity_does_not_excuse`
  — a fully valid temporary entry (issue, future date, live handler,
  matching name) registered against a *different* live route leaves the
  canned handler unexcused: `main() == 1` on the canned finding alone, with
  zero registry failures, pinning the excuse's exact-identity keying.

(The first attempt's note claimed `tests/: +9`; those tests pinned the
superseded tracking-only contract and were withdrawn with it. Net lane
delta against develop is +3.)

### Fail-before proof (re-run this round, outside the repository tree)

The three negatives are not vacuous. A scratch harness in `/tmp` (the
repository tree was not modified) loaded the real test module, swapped one
gate helper for a deliberately leaky variant, and re-ran each negative:

| leak injected into the gate | negative that must catch it | result |
| --- | --- | --- |
| one valid temporary entry excuses **every** canned handler (`_canned_handlers` patched) | `test_main_temporary_disposition_under_foreign_identity_does_not_excuse` | fails on the leak, passes on the shipped gate |
| the excuse ignores the tracking issue | `test_main_temporary_disposition_without_issue_does_not_excuse` | fails on the leak, passes on the shipped gate |
| the excuse ignores the review date | `test_main_temporary_disposition_with_malformed_date_does_not_excuse` | fails on the leak, passes on the shipped gate |

`uv run pytest /tmp/test_failbefore_1859.py -q` → **6 passed** (3 leak
variants × fail-on-leak, 3 controls × pass-on-shipped-gate). The first
variant had to be re-shaped: a leak that only widened the *identity set*
returned the same exact `(file, method, path)` tuples and therefore did not
actually broaden the exemption — the negative correctly did not fire. The
broad-exemption leak had to patch the consumer (`_canned_handlers`), not the
identity source, to model the real #389 failure mode.

## CI repair: `Supply chain (pip-audit)` — the assigned gate failure

The merge-queue evaluation of PR #2231 failed two jobs with **one** root
cause: `Supply chain (pip-audit)` (security workflow) and `security` (CI
workflow). Both ran `scripts/pip_audit_gate.py` and both reported:

```
aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
```

Reproduced locally before the change with CI's exact contract
(`uv sync --locked --extra dev` → `uv pip freeze --exclude-editable` →
`uv run pip-audit --strict --format=json -r deps.txt` → `uv run python
scripts/pip_audit_gate.py report.json`): the gate exited 1 with exactly
those three advisories. The scanner-side before/after is one package:

| requirement | `pip-audit` result |
| --- | --- |
| `aiohttp==3.14.3` | 3 known vulnerabilities (CVE-2026-111064, GHSA-2g87-pp6c-29x5, CVE-2026-111063), exit 1 |
| `aiohttp==3.14.5` | `No known vulnerabilities found`, exit 0 |

**Fix**: `uv lock --upgrade-package aiohttp` → `aiohttp 3.14.3 → 3.14.5`
(past the 3.14.4 fix) and `yarl 1.24.2 → 1.25.1` (aiohttp ≥3.14.4
requires `yarl>=1.25.1`); `multidict` stays at 6.9.1 (3.14.5 allows
`<8.0`). Nothing else in the lock moved. No allowlist entry was added:
every advisory has a fixed version, and the gate's own rule is to upgrade
rather than triage when a fix exists.

After the bump, the same gate over the frozen environment (208 distributions
audited) reports only the already-triaged `ecdsa==0.19.2 PYSEC-2026-1325`
(in the gate's `ALLOWED` list) and exits 0 —
`pip-audit OK (1 known, all triaged in ALLOWED)` plus
`direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions`.
The same frozen environment also passes
`uv run python scripts/check-dependency-namespaces.py` (exit 0), the gate
that runs immediately before the audit in CI's `security` job.

## Validation (this round, at the reconciled head)

- `uv sync --locked --extra dev` — clean.
- `uv run ruff check .` — `All checks passed!`; `uv run ruff format --check .`
  — `3362 files already formatted`.
- `uv run pytest tests/test_check_api_route_contracts.py -q` — **64 passed**
  (develop's suite + the 3 new negatives).
- `uv run pytest /tmp/test_failbefore_1859.py -q` — **6 passed** (fail-before
  table above).
- `uv run pytest tests/ -q` — **3 failed, 5489 passed, 138 skipped**. The
  three failures are `tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`
  and `tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`
  — all three are the **develop-level** `maestro.runs.admission_identity`
  reachability debt inherited from #1936, not this lane's delta (see
  "Inherited develop-level reds" below). A first full run also showed
  `tests/test_restore_oracle_characterization.py::test_semantic_loss_is_rejected`
  failing; it passes in isolation and in the re-run, and it drives its own
  postgres containers — a Docker-resource flake under the other lanes'
  containers, not a code defect.
- `uv run python scripts/check-api-route-contracts.py` — OK on the real tree
  (`295 handlers scanned, 15 audited routes registered, 0 canned`), exit 0.
- `uv run python scripts/check-suite-inventory.py --suite tests/` — ok,
  `collected node IDs: 5630`, `ok: 1 suite(s) match the recorded inventory`.
  The `+3` delta for this lane is recorded in this note's front matter; no
  edit to `docs/testing/inventory/baseline.json` was needed (the gate folds
  note deltas into the recorded total).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  (CI's exact argv) — exit 0: `baseline: base e20e9f52ea94`, `candidate:
  f547cef795a8` (the develop merge), `1326 reviewed identities -> 1326 findings`,
  `unclassified: 0`, `never_allowlist: 0`. **No amendment to
  `quality/vulture-baseline.json` is required**: the candidate ledger is
  already exactly the reviewed set, so any edit would be a no-op (and the
  lane brief's amendment authority is limited to genuinely reviewed
  identities). `git diff --numstat origin/develop -- quality/` is empty —
  the merge lost no ledger row.
- `uv run python scripts/check-dependency-namespaces.py` — exit 0.
- `uv run python scripts/verify-minimum-dependencies.py` — exit 0.
- `uv run python scripts/check-ratchet-provenance.py` — exit 1, **solely**
  on the reachability leg (below); every other leg is green.

## Inherited develop-level reds (not this lane's delta, not fixable here)

Syncing develop brought in the debt that #1936 (`auto-1851`) landed on
`develop` itself. Develop's own push of `e20e9f52` is red: run `39369230464`
(Vulture Ratchet) and run `39369230418` (CI) both fail, and the develop
`test` job fails with the same three reachability tests this branch now
reports. The one line this lane must not blur:

```
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.runs.admission_identity: current unreachable module missing from candidate baseline
```

`maistro.runs.admission_identity` (added by #1936) is unreachable and is not
banked in `quality/reachability-baseline.json`. This branch reproduces
develop's failure exactly (168 unreachable -> 169 of 1417 modules) and
cannot repair it: `ratchet_provenance.load_authorizations` reads
`quality/ratchet-authorizations.json` **from the merge base**, so a
branch-side grant is inert — the two-merge rule requires the owner to land
the grant on `develop` first. Writing the reachability baseline row here is
outside this lane's authority (the lane's ledger authority is the vulture
per-identity ledger, which needs no amendment) and would mask real
develop-level debt. The same `develop` push also fails `SAST / Gitleaks`
(3 leaks in the #1936 commits) and `Quality / Vulture` (the vulture
two-merge wall: `1321 reviewed identities -> 1326 findings` against base
`fad17a87c`) — both of which clear for this branch, whose ratchet base is
`e20e9f52`, where the five `admission_identity` rows are already banked.

## Repair round (job `ce7b54d3`, head `d1431777d`) — the gate's sole red is the reachability leg, and it is not this lane's to fix

This round was assigned to repair `exact-debt-ledger` through the vulture
per-identity ledger. Re-run at this exact head with CI's own argv
(`.github/workflows/vulture-ratchet.yml`):

| step | command | exit |
| --- | --- | --- |
| 1 | `uv run python scripts/check-ratchet-provenance.py` | **1** |
| 2 | `uv run python scripts/check-shipped-surface-truth.py` | 0 |
| 3 | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 0 |

Step 3 is green: `baseline: base e20e9f52ea94`, `candidate: d1431777d1c6`,
`1326 reviewed identities -> 1326 findings`, `unclassified: 0`,
`never_allowlist: 0`. The brief's amendment authority
(`quality/vulture-baseline.json`) has no target — the ledger is already
exactly the reviewed set and `git diff --numstat origin/develop -- quality/`
is empty. CI's own `exact-debt-ledger` job (run `39376432253`, job
`118475501998`) failed at **step 1**, never reaching step 3.

Step 1 fails on exactly one ratchet leg — the reachability ratchet; every
other leg prints `OK`. The two lines are the same `maistro.runs.admission_identity`
NEW-unreachable / missing-from-candidate-baseline pair recorded above. The
module is present in base `e20e9f52` and absent from
`quality/reachability-baseline.json` (168 rows, zero admission matches) and
from `quality/ratchet-authorizations.json` (11 `reachability` grants, zero
admission); it is imported only by
`packages/maistro-core/tests/runs/test_root_admission_identity.py`, and its
docstring declares it an inactive contract leaf whose runtime consumer lands
in a separately reviewed integration.

Develop's own push of `e20e9f52` failed the same Vulture Ratchet run
(`39369230464`, `conclusion: failure`, event `push`, head `e20e9f52ea94`)
and CI run `39369230418`. This branch's diff vs develop is exactly three
files (this note, `tests/test_check_api_route_contracts.py`, `uv.lock`) and
does not touch the module.

**No in-branch fix exists.** The two-merge wall
(`ratchet_provenance.load_authorizations` reads the grant ledger from the
merge base) makes a branch-side reachability grant inert, so the grant must
land on `develop` first. The lane brief's amendment exception covers only
`quality/vulture-baseline.json` (green), and #1851's unconditional
prohibition forbids grants and baseline additions. Wiring the module into
`maistro/runs/__init__.py` purely to hold an import edge would make the gate
measure a fiction — #1154 retired exactly that kind of wrapper. Banked is
not authorized: adding the candidate baseline row alone flips the failure to
the `not previously authorized` line and cannot clear it.

> **Corrected by the round below.** "No in-branch fix exists" was too strong.
> The two-merge wall closes the *ledger* repairs (a branch-side grant, a
> branch-side baseline row); it does not close a repair that changes the
> **tree**. When the module is reachable from an entry point there is no
> candidate debt to authorize at all, and no `quality/*.json` file has to
> move. Sibling lanes `#886` (`2d662ed43`) and `#948` (`8b5a2e838`) applied
> exactly that tree-side repair for the identical inherited red while this
> lane was blocked; the next section applies the same change here.

**Handoff (one exact action, on `develop`).** Land a grant-only change:
append one entry under `reachability` in `quality/ratchet-authorizations.json`
for `maistro.runs.admission_identity` (owner `@BlakeMatthews-dev`, issue
`#1851`; reason: the root-admission identity contract leaf shipped by #1936,
an importable maistro-core surface with no process entry point in this
repository, dispositioned LIBRARY; the #1845 integration adopts it and the
entry then leaves the baseline), plus the matching
`quality/reachability-baseline.json` row and a LIBRARY group in
`quality/reachability-dispositions.json`. Then sync `origin/develop` into
`auto-1859` and re-queue. Until it lands, every branch based on `e20e9f52`
fails `exact-debt-ledger` identically.

**#1859 acceptance re-proven this round (independent of the note above).**
`uv run pytest tests/test_check_api_route_contracts.py -q` -> **64 passed**.
Fail-before, outside the repository tree: with a broad-exemption leak patched
into the gate consumer (`_canned_handlers` returns no canned handlers, so
one valid temporary entry excuses every route — the real #389 failure mode),
all three new negatives fail (`3 failed`); on the shipped gate they pass
(`3 passed`). `uv run python scripts/check-api-route-contracts.py` -> exit 0
(`295 handlers scanned, 15 audited routes registered, 0 canned`). Registry,
gate script and inventory doc are byte-identical to develop; zero
`temporary` entries.
