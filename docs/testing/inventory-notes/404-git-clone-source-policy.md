---
inventory-delta:
  packages/maistro-core/tests: +33
---

# Candidate-source policy for `git_clone` (issue #404 / [M6 deferred])

Rejects unauthenticated `git://` clone URLs so an on-path attacker cannot
substitute repository content that RSI later builds/tests. Thirty-three
maistro-core node IDs cover the new policy surface; no other suite moves
(the two RSI hermetic tests were re-pointed at the new explicit local-source
opt-in without adding or removing cases).

## What the policy now does (`maistro.tools.git.server`)

- `git://` is hard-rejected before any allowlist logic — it stays rejected
  even if `_ALLOWED_CLONE_SCHEMES` is widened by a caller or test.
- Sources must be `https://` or `ssh://` for a host allowed by
  `MAISTRO_GIT_CLONE_HOSTS` (unset = any host over an authenticated
  transport); URLs are parsed, not prefix-matched, so case variance
  (`GIT://`), percent-encoded schemes, and scheme lookalikes resolve to the
  same decision as their canonical spelling.
- `file://` is a *verified local source*: clonable only when explicitly
  opted into AND the resolved path sits under `_ALLOWED_LOCAL_SOURCE_ROOTS`
  (empty by default — production refuses local sources outright).
- Every clone runs with pinned config: `protocol.allow=never` plus explicit
  https/ssh allows and `file=user` (the git transport whitelist, inherited
  by submodule fetches), `http.followRedirects=false` (redirects and
  protocol-downgrade hops fail instead of being followed), and
  `http.sslVerify=true`.
- `commit=<full digest>` pins the checkout: the tool fetches the digest
  itself, detaches to it, and re-verifies HEAD, so a branch ref moving
  between resolution and fetch (TOCTOU) cannot change what gets built;
  `require_signed` demands `git verify-commit` accept the pin. The resolved
  HEAD digest is returned as `head_commit` on every success.
- Submodule URLs in the fetched `.gitmodules` are validated against the same
  policy; a malformed `.gitmodules` is rejected outright.

## Test nodes

`test_server_security.py`: non-policy source URLs (10 parametrized cases —
git transport incl. case/encoded spellings, lookalike schemes, bare and
scp-like local paths, host-less https, plaintext http), the widened-allowlist
precedence invariant, host allowlist enforcement + case-insensitivity, the
transport hardening argv, `head_commit` reporting, pin-when-branch-moved
(TOCTOU success and rejection), fetch-failure → `commit_pin_mismatch`,
non-digest pins (3 cases), uppercase digest normalization, signature policy
fail-closed and pass, policy-compliant / non-policy (4 cases) / malformed
submodule URLs, and the three local-source gating cases.
