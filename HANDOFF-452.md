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
