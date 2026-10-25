# Handoff — issue #452 (M6 deferred-cleanup initiative), lane L452, job 8758e06e8c144e88913591bc9afecf99

Head at close: this round's repair commit on `0337df64e4` (merge of develop
`30677b185`). Worktree clean after commit. No `quality/*.json` edits this
round — both CI failures were repaired in code, not by ledger.

## This round's delta — the two CI failures closed (verification round d48c389db)

1. **Radon CC ratchet (Quality gate job) — repaired by refactor, not grant.**
   The prior head added three unbaselined C blocks in
   `maistro-core/src/maistro/tools/git/server.py`
   (`_clone_and_maybe_pin` C(11), `_enforce_signature_policy` C(15),
   `git_remote_tip` C(11)) and regressed
   `maistro_rsi/selfbranch.py::run_self_branch_attempt` to C(16)
   (baseline 13). Grants read from the merge base and can never authorize
   the change that introduces them, so the repair is structural:
   `_ENFORCEMENT_ARGV` (module-level pre-expansion of the `-c` pins)
   replaces the per-spawn comprehensions in `_clone_and_maybe_pin` and
   `git_remote_tip`; `_enforce_signature_policy` delegates its three
   failure shapes to `_signature_policy_failure` / `_landed_signer_fprs`;
   `run_self_branch_attempt` delegates pin resolution to
   `_resolve_source_pin` and PR-URL extraction to `_pr_url_of`, landing at
   exactly its baseline C(13) (no regression, no improvement — no radon
   ledger interaction). `check-radon-baseline.py` exit 0: 143 = 143, zero
   new/regressed/improved/stale. Behavior unchanged (error strings and
   argv byte-identical); full core suite green.
2. **`coverage (no services)` / `test` CI failures — the submodule fixture
   leaned on ambient git identity.**
   `_origin_with_git_submodule` ran `git commit -qm` with no committer
   identity; identity-less CI runners exit 128 at fixture setup. It now
   sets repo-local `user.email`/`user.name` (the file's own convention,
   e.g. its lines 551-552). Proven: bare `git commit` under
   `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null` exits 128
   (reproduced), and the fixed test plus the whole
   `test_server_security.py` (62), `test_selfbranch.py` +
   `test_harvest_entry_point.py` (54) pass under that same identity-less
   env. Every other real-git site in the lane's tests already sets
   repo-local identity (audited).

Validation at this head: `ruff check .` / `ruff format --check .` clean
(2922 files); `pytest packages/maistro-core/tests -q` 12476 passed; `pytest
packages/maistro-rsi/tests -q` 1043 passed; `pytest
packages/maistro-core/tests/cli/test_builders.py -q` 22 passed; `mypy
--strict packages/maistro-core/src` clean; canonical mypy battery clean;
`check-radon-baseline.py` exit 0 (143=143); xenon (CI args) blocks 143 ≤ 145,
average 0, module ledger empty; `check-vulture-baseline.py` (CI args) exit 0
(1338→1337, base-authorized, no amendment); `check-suite-inventory.py` ok
(14 suites; no test additions this round, so no inventory-note delta);
`check-test-duplicates.py`, `check-reachability.py`,
`check-promotion-surface.py`, `check_direct_effects.py` all exit 0.

---

# Prior rounds (context)

# Handoff — issue #452 (M6 deferred-cleanup initiative), lane L452, job e325340c796d497285789c0a1a8e3f3c

Head at close: this round's commit on `a285a95ad` (the prior merge of develop
`2728e3a58`). Worktree clean after commit.

## This round's delta — the three verifier findings closed

Independent verification left three findings against reachable #404 behavior;
all three are closed in tree with tests pinning the closures (note:
`docs/testing/inventory-notes/404-pinned-defaults-and-builders-policy.md`,
delta +12 core / +3 rsi):

1. **Builders TUI cloned outside the shared source policy.** `_open_repo`
   rejected `git://` but cloned every other classified URL (`http://`, any
   https host, scp-style, `.git`-suffixed flag strings) with a raw argv — no
   `validate_clone_source`, no pins, no `--`. It now gates through the shared
   policy (one verdict with the MCP tool and RSI harvest) and the clone argv
   carries the `-c` enforcement pins and the `--` separator. The test that
   asserted `http://example.com/repo.git` was accepted is gone; refusal is
   now pinned at runtime for http:// (both casings), off-allowlist hosts,
   scp-style, and flag strings, with an admitted https URL proving the pins
   and separator.
2. **The digest-pin fetch carried no argv pins.** `_verify_pinned_checkout`'s
   fetch-by-digest now passes the same `-c protocol.git.allow=never` /
   `http.followRedirects=false` pins in its own argv (shared
   `_ENFORCEMENT_CONFIG` with the clone), so the enforcement is executable,
   not inherited from whatever config the clone happened to persist.
3. **RSI "pin" defaulted to unpinned.** `source_commit`/`commit` = None
   cloned whatever the remote tip was at fetch time. None now resolves the
   remote's HEAD to a digest first — new `git_remote_tip`
   (`maistro.tools.git.server`): policy-gated pre-spawn, ls-remote under the
   pins with the URL after `--`, non-digest resolutions refused — and the
   clone is always fetch-by-digest with the `rev-parse` verdict. A failed
   resolution fails the attempt closed before any clone; an explicit pin
   skips resolution. Every successful run reports a verified
   `cloned_commit`.

Validation at this head: `ruff check .` / `ruff format --check .` clean;
`pytest packages/maistro-core/tests -q` 12476 passed; `pytest
packages/maistro-rsi/tests -q` 1013 passed; canonical mypy battery clean;
`check-vulture-baseline.py` (CI args) exit 0, no amendment needed;
`check-suite-inventory.py` ok after the recorded delta. Live probes: resolver
names the origin tip digest, resolve→pin→clone lands HEAD == pin, policy
verdicts (http://, git://, off-host, flag string) all refuse with distinct
codes.

---

# Prior rounds (context)

# Handoff — issue #452 (M6 deferred-cleanup initiative), lane L452, job f1c5ce96c0fc4338a29b2097d332160e

Head at close: `30d16275d` (= develop base `94781cf6b` merged cleanly into
`65c889bba`, plus this round's commit). Worktree clean after commit.

## This round's delta

1. **Develop sync** — the branch forked before the declared base `94781cf6b`
   (#1976, api-route-contract handler identity) landed; merged conflict-free
   as `733ccaef0` (files disjoint from the lane's surface).
2. **#404 AC3 residual closed** — "verify fetched object identity/signature
   policy" had no trust anchor to verify a signature against, so the
   signature half was comment-only. `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`
   (comma-separated full OpenPGP fingerprints) is now the anchor: with it
   set, `git_clone` requires the landed HEAD to carry a cryptographically
   good signature (`%G?` G/U) by a trusted key (`%GF`/`%GP` match), after
   the digest-pin verdict; error codes `commit_signature_missing` /
   `commit_signature_invalid` / `commit_signature_untrusted`; success
   reports `signature_verified: True`; the unset-anchor off-state is
   documented and asserted (no signature subprocess). Both clone surfaces
   (MCP tool + RSI harvest/self-branch) share the one gate. Tests:
   +13 node IDs (`test_server_security.py`: verdict mapping, anchor
   parsing, live gpg signed/foreign/unsigned origins; red-checked 11/12
   fail with enforcement disabled). Inventory note:
   `docs/testing/inventory-notes/404-signature-trust-anchor.md`.
   Vulture ledger: pruned the one row the new name-use eliminated
   (`code_registry/types.py::unused variable 'trusted'`, 1338→1337, gate
   exit 0 with CI args) — permitted amendment in this CI-repair round.

## Steering checkpoints — evidence at this head (tree-side)

Direct deferred children of #452: 19. Implemented in this tree:

| Child | Evidence (in HEAD) |
|-------|--------------------|
| #399 | demo-gated seeding with `synthetic=True` provenance (`hive-conductor/backend/stores.py::_seed_messages`; #1899) |
| #400 | `stream1-diagnostic.yml` gone; workflow-inventory gate (`cfb6c64`/#1901) |
| #401 | `scripts/install-maestro.sh` absent; `tests/test_installer_entrypoints.py` pins it |
| #402 | `MAISTRO_ACCESS_TOKEN` gone from compose; `install.sh` migrates it; `tests/test_secret_env.py`, `tests/test_check_compose_secrets.py` |
| #403 | `/invoke` suffix exemption removed (`8e0fd00c`/#1731) |
| #404 | this branch: git:// rejection, host allowlist, digest pins, executable redirect/submodule pins, signature trust anchor |
| #405 | override included explicitly with ownership/permission checks (`64d57cb`/#1902, `install.sh`) |
| #406 | `scripts/check-dependency-namespaces.py` gate (`97c05e0`/#1903) |
| #407 | Compose v2 floor + platform instructions, no v1 fallback (`install.sh`, #1901-family) |
| #408 | closed `completed` (GitHub) |
| #409 | `get.ps1 -AnswersFile` parity with `get.sh` (`e067b7b`/#1905) |
| #410 | falsifiable formal properties + mutants (`f904207`/#1907) |
| #411 | channel switching on single-branch checkouts (`135bffd`/#1908) |
| #441 | closed `completed` (GitHub) |
| #1191 | `ProportionalityDisposition = allow|deny|unavailable`, explicit at every dispatch (`e760eb7`/#1915) |
| #1205 | `quota/billing.py` compatibility alias over canonical `normalized_daily_budget` |
| #1206 | poll floor + visible `first_seen` repair (`00aafef`/#1912) |
| #1207 | empty-substitution contract documented + tested (`eed1d09`/#1913) |
| #863 | **open, in-flight on lane `auto-863`** (migration 053 index work, not merged to develop) — do not race it |

Checkpoint verdicts (tree-side): "every direct deferred child completed /
obsolete / promoted" — 18/19 implemented in-tree, #863 in flight on its own
lane; "#415 closed" — #415's exit-criteria validation and required
GitHub-side repairs are recorded in `HANDOFF-415.md` (commit `249c12d1`),
but issue state (#452 checkboxes, #399/#400/#401/#407/#402–#406/#409–#411/
#1191/#1205–#1207 still open on GitHub) needs a mutation-capable driver —
this lane is prohibited from GitHub mutations.

## Re-validation round (job `20b9b4763c8445dba557f42ce789e390`, head `fb679d893`)

The prior round closed NEEDS-DEEP-REVIEW with no tree-side repair left; this
round re-ran the full battery at the unchanged head and probed the policy at
runtime. All green, no code changes required:

- `uv run ruff check .` / `uv run ruff format --check .` — clean (2917 files)
- `uv run pytest packages/maistro-core/tests/tools/git packages/maistro-core/tests/cli/test_builders.py -q` — 149 passed
- `uv run pytest packages/maistro-rsi/tests -q` — 1010 passed (incl. `test_harvest_entry_point.py` 32: refusal exits 2 before any subprocess; allowed path spawns git with both `-c` pins and `--` separator)
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1338 base → 1337 candidate, zero unbanked identities; CI-repair clause satisfied with no amendment)
- `uv run python scripts/check-suite-inventory.py` — ok, 14 suites
- Runtime probes of `validate_clone_source`: `git://`, `GIT://`, `git%3a//`, off-allowlist host, `github.com@evil.com` userinfo trick, and `ext::sh -c id` all refused with distinct error codes; `MAISTRO_GIT_CLONE_ALLOWED_HOSTS` override admits `example.com` while `github.com` stays refused under it
- Spot-checks of the child table: `scripts/install-maestro.sh` absent (#401), no `stream1-diagnostic*` anywhere (#400), `MAISTRO_ACCESS_TOKEN` only in removal-documenting comments (#402)

Remaining residual is unchanged and **not tree-repairable**: 16 of 19 child
issues plus #452's own checkboxes and #415 are still open on GitHub despite
the in-tree fixes; #863 is in flight on lane `auto-863`. Closing them needs a
mutation-capable driver — this lane is prohibited from GitHub mutations.

## Validation battery at head `30d16275d`

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 2917 files clean
- `uv run pytest packages/maistro-core/tests -q` — 12464 passed, 888 skipped, 1 xfailed
- `uv run pytest packages/maistro-rsi/tests -q` — 1010 passed
- `uv run pytest packages/maistro-core/tests/tools/git -q` — 132 passed
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1337=1337)
- `uv run python scripts/check-suite-inventory.py` — ok, 14 suites
- `uv run python scripts/check-api-route-contracts.py` — OK (279 handlers); its tests 36 passed

## This round's delta — the coverage-gate failure closed (repair round at 756112f60)

CI's `Coverage gate (publish-set floor + diff coverage)` failed at
`756112f60` with exactly one file below the per-file floor:
`packages/maistro-rsi/src/maistro_rsi/__main__.py` at 87.5% of its 24 scored
changed lines (need 90%), uncovered 755, 766, 767. Those are the digest-guard
`raise` and the two checkout calls of `_run_harvest_clone` — unreachable by
`test_an_allowed_clone_url_resolves_then_fetches_a_digest_under_pins`, which
stubs `subprocess.run` and raises at the fetch on purpose.

Repair is test-only (no source change, so the scored line set is untouched):
`packages/maistro-rsi/tests/test_harvest_clone_source.py` (new, 5 tests) runs
real git against a local `file://` origin — happy path lands branch/HEAD on
the resolved digest with a materialized work tree and the `core.autocrlf=false`
pin persisted; the no-matching-ref and unreachable-remote shapes both refuse
before `git init` creates a workspace. Inventory delta recorded in
`docs/testing/inventory-notes/452-harvest-clone-pinned-source.md` (+5 rsi).

Validation:

- `scripts/check-diff-coverage.py coverage.xml --base 879d66a1` (CI's exact
  merge-group base): `__main__.py` 24/24 scored changed lines covered;
  `audit()` failures NONE — the exact failing gate passes locally
- Publish-set floor reproduced locally (core/canvas/evolve/rsi/bootstrap
  producers, CI's argv): 92% total, floor 87 — passes; CI's own floor step
  passed at this head too (unit/postgres/archive producer jobs all green)
- `uv run pytest packages/maistro-rsi/tests -q` — 1085 passed (incl. the 5 new)
- `uv run python scripts/check-suite-inventory.py` (core+rsi) — ok
- vulture CI-exact argv — exit 0, zero unbanked identities, no ledger edit
- ruff check + format — clean

Note: `packages/maistro-core/tests/test_container_postgres.py::
test_an_unreachable_server_is_an_error_not_a_fallback` is a local-environment
flake (needs ~62s of container startup; the suite's `--timeout=30` kills it).
Untouched by this branch; passes with `--timeout=120`; CI's coverage jobs
passed it at this head.
