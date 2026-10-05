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

## Validation battery at head `30d16275d`

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 2917 files clean
- `uv run pytest packages/maistro-core/tests -q` — 12464 passed, 888 skipped, 1 xfailed
- `uv run pytest packages/maistro-rsi/tests -q` — 1010 passed
- `uv run pytest packages/maistro-core/tests/tools/git -q` — 132 passed
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1337=1337)
- `uv run python scripts/check-suite-inventory.py` — ok, 14 suites
- `uv run python scripts/check-api-route-contracts.py` — OK (279 handlers); its tests 36 passed
