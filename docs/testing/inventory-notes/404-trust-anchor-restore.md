---
inventory-delta:
  packages/maistro-core/tests: +15
---
# #404 repair: restore the deployment-wide signature trust anchor dropped by the develop-sync merge

Repair-round note for the exact-debt-ledger / Quality gate failure at merge
head b25f053796f4. No existing suite count changed shape: this round adds 15
node IDs to `packages/maistro-core/tests/tools/git/test_server_security.py`
and removes none.

## What failed and why

The develop-sync merge (b25f05379) reconciled two parallel #404
implementations by keeping the branch's enforcement core and adopting
develop's public URL-policy API — but it silently dropped develop's
deployment-wide signature trust anchor
(`MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`, `_enforce_signature_policy`,
`_trusted_signature_fprs`, `_landed_signer_fprs`). That dropped code was the
only in-tree use of the *name* `trusted`; vulture matches identities by name
(as `maistro/security/transport.py`'s parameter comment documents), so
`CodeEntry.trusted` (`code_registry/types.py:24`) became a fresh unmasked
finding:

```
pydantic-declarative-field: 1 NEW identit(y/ies) not in the ledger:
  packages/maistro-core/src/maistro/code_registry/types.py:24:
  unused variable 'trusted' (60% confidence)
1342 reviewed identities -> 1343 findings
```

The merge round had banked the row in `quality/vulture-baseline.json`, but
the per-identity ratchet reads authorizations from the merge base
(two-merge rule), so candidate banking cannot self-authorize —
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exit 1 at b25f0537 (reproduced). The field itself cannot
be deleted: SPEC-257 specifies `CodeEntry.trusted` as retained caller-asserted
API.

## The repair

Restored the dropped develop-side feature in
`packages/maistro-core/src/maistro/tools/git/server.py`: the anchor is parsed
from `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS` (normalized fingerprints), and every
successful `git_clone` runs `_enforce_signature_policy` — HEAD must carry a
cryptographically good signature (`%G?` G or U) by a key on the allowlist
(`%GP`/`%GF`), else a structured failure (`commit_signature_missing` /
`commit_signature_invalid` / `commit_signature_untrusted`); success augments
the result with `signature_verified: True`. It composes with the branch's
per-call `require_signed` (`git verify-commit`), which runs first. This is
the genuine-use fix: the `trusted` name is used by real shipped behavior
again, the finding disappears, and the banked row was pruned (the candidate
ledger is byte-identical to origin/develop's again).

## The +15

All in `test_server_security.py`, adapted from the develop-side suite the
merge had dropped, on the file's `_ScriptedGit` harness (exact-argv-element
matching, so the verification sequence itself is under test):

1. `test_trusted_fprs_normalize_entries_and_drop_empties` — anchor parsing
   (case, spacing, empties).
2. `test_signature_policy_is_off_without_the_trust_anchor` — unset knob: no
   `%G?` subprocess at all, no `signature_verified` key.
3. `test_signature_policy_when_git_status_is_unreadable_fails_closed`.
4. `test_signature_policy_rejects_not_good_verdicts[N/B/X/E]` — 4 nodes.
5. `test_signature_policy_rejects_good_signature_by_untrusted_key`.
6. `test_signature_policy_accepts_trusted_signer[primary/subkey]` — 2 nodes.
7. `test_git_clone_trust_anchor_composes_with_require_signed` — merge-specific:
   both policies' subprocesses scripted in one flow.
8. `test_git_clone_functionally_refuses_redirects` — real git,
   real HTTP: the 302 is refused and the destination never populated (the
   merged policy refuses plain http at the protocol whitelist, so the test
   widens it exactly as a hostile-config deployment would and proves the
   `http.followRedirects=false` pin still fires).
9. `TestLiveSignaturePolicy` — 3 real-git/real-gpg end-to-end nodes
   (throwaway GNUPGHOME, Ed25519 key, signed origin, the production
   `%G?`/`%GF` path), skipped only when gpg is absent.

Measured: canonical collection (`uv run pytest packages/maistro-core/tests
--collect-only -q` under `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`) 13707 at
b25f0537 → 13722 with this round; `packages/maistro-rsi/tests` unchanged at
1111.

## Residual risk (out of lane, measured, not introduced here)

`scripts/check-ac-state.py --run-tests --ratchet` fails on this branch:
`design_coverage: 38.1507 falls below the floor of 42.8609`. The floor is the
max-fold of the base's `quality/ac-state-notes/`, dominated by
`auto-119.json` (42.8609), which landed on develop in cd5618223 (PR #1756) on
2026-10-05 — after this branch's last green round. The branch's corpus is
identical to develop's (no diffs under `docs/specs`/`docs/adr`; ac-mark
distribution identical; marked tests pass), and the develop tree itself
measures the **same 38.1507** at b672b799a (measured in a throwaway worktree
at that SHA, `check-ac-state.py --run-tests`, then removed) — so the floor
undercut is inherited from develop, affects every candidate against it, and
cannot be repaired from this branch: the ratchet's regression half compares
against the base fold, only a separately-landed grant in
`quality/ratchet-authorizations.json` (ac-state section, empty at develop)
can lower it — the two-merge rule — and corpus-wide coverage work is outside
#404. Hosted CI's Quality-gate FAILURE at b25f0537 fired at the vulture step
(before the ac-state step), which this round fixes; the ac-state step will
still be red until the develop-side floor fall is banked/authorized upstream.
