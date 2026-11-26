---
inventory-delta:
  packages/maistro-core/tests: +13
---

# #404 AC3 — signature policy made executable: `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`

The previous #404 rounds closed the transport/host gate, the digest pin, and
the redirect/submodule pins. Independent review left one residual: AC3 reads
"verify fetched object identity/signature policy", and the signature half
had no trust anchor to verify against — no production surface named a key a
signature could be checked against, so the clause could only be a comment.

This round gives the policy its anchor. `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`
(comma-separated full OpenPGP key fingerprints; space/case insensitive) is
the deployment's statement of whose signatures its candidate sources carry.
With it set, `git_clone` requires — after the clone, and after the digest-pin
verdict when one is given — that the landed HEAD commit's signature is
cryptographically good (`git log %G?` in {G, U}; U is a keyring-trust state,
not a cryptographic verdict, and the anchor is the fingerprint allowlist) and
that the signing key (`%GF` subkey / `%GP` primary) is one of the trusted
fingerprints. Three distinguishable failure codes:

- `commit_signature_missing` — HEAD unsigned (`N`) or status unreadable;
- `commit_signature_invalid` — present but not good (`B` bad, `X`/`Y`
  expired, `E` unchecked, `R` revoked);
- `commit_signature_untrusted` — good signature, unlisted key.

Every failure says "do not use this workspace", like the other #404
verdicts. A passing clone reports `signature_verified: True` alongside
`pinned_commit`. With the anchor unset the policy is unchanged — digest
identity over authenticated transport — and that off-state is itself
asserted (no signature subprocess runs, so the default costs nothing and is
a documented choice, not an oversight). Because the check lives in the one
shared `_clone_and_maybe_pin` path, both clone surfaces (the MCP
`git_clone` tool and the RSI harvest/self-branch cycle, which calls it)
inherit it — there is no second policy to drift.

## Tests (`packages/maistro-core/tests/tools/git/test_server_security.py`)

- off-state: no anchor → no signature subprocess, no `signature_verified`;
- anchor parsing: grouping spaces stripped, case normalized, empties dropped;
- verdict mapping (scripted `%G?`): unreadable/`N` → missing; `B`/`X`/`E` →
  invalid (parametrized);
- good signature by unlisted key → `commit_signature_untrusted`;
- good signature by trusted key, named as primary or subkey → pass, with
  `signature_verified: True` (parametrized);
- live gpg (throwaway `GNUPGHOME`, Ed25519 key, real signed origin, real
  clone): trusted signer passes with `pinned_commit` + `signature_verified`;
  foreign anchor fails `commit_signature_untrusted`; unsigned origin fails
  `commit_signature_missing` (this direction needs no gpg, so fail-closed
  holds even on gpg-less runners).

Red-checked: with the enforcement disabled, 11 of the 12 signature-policy
node IDs fail (the off-state test correctly still passes). Live gpg tests
skip when gpg is absent rather than weakening the assertions.
