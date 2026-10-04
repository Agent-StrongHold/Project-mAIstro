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

## Independent validation record (verification round at 0f2214162668)

Deterministic checks re-run fresh against the fix commit (prior claims not
trusted): `ruff check` / `ruff format --check` clean; 116 passed in
`packages/maistro-core/tests/tools/git`; 28 passed in
`packages/maistro-rsi/tests/test_cli.py` + `test_selfbranch.py`;
`check-vulture-baseline.py` exit 0; `check-suite-inventory.py` matches for
`packages/maistro-core/tests` (11715) and `packages/maistro-rsi/tests` (786);
`check-security-inventory.py` OK. Live behavioral probes with real git (not
mocks):

- `git://` (and case/encoded spellings, scp-like, `http://`) rejected with
  `blocked_url_scheme` before any subprocess spawns; with the same pinned
  config, git itself refuses the transport (`fatal: transport 'git' not
  allowed`) — defense in depth.
- True TOCTOU: main force-amended to an attacker commit between pin
  resolution and clone; the pinned clone fetched the trusted digest
  (`head_commit == pin`) and the tree held trusted content, not the attacker
  content.
- `require_signed` on an unsigned pin → `commit_signature_unverified`.
- Fetched `.gitmodules` declaring a `git://` submodule URL →
  `blocked_submodule_url` post-clone.
- Agent-reachable clone paths audited: `maistro_rsi.selfbranch` imports the
  hardened `git_clone`; the only raw-clone sites left are operator CLI args
  (`rsi harvest --clone-url`, `--repo` local path) — human trust domain,
  outside the candidate-source policy surface.

## Repair round (CI Quality gate: radon CC ratchet)

The radon ratchet at b2ca211948a0 flagged three new C-rank blocks introduced
by the fix (`_validate_clone_url` 11, `_verify_cloned_source` 13,
`git_clone` 11). Rather than growing `quality/radon-baseline.json` (the
ratchet forbids growth outside reviewed remediation), each hotspot was
decomposed into single-purpose helpers, behavior- and message-identical:
`_check_clone_scheme_allowed` + `_validate_remote_clone_host` (URL policy),
`_resolve_pinned_head` (TOCTOU fetch/detach/re-verify) +
`_verify_commit_signature` (fail-closed signature policy), and
`_parse_commit_pin` + `_run_git_clone` (pin normalization + hardened
subprocess). No test moved: 116 git-tool tests and the 28 targeted RSI
tests pass unchanged, `check-radon-baseline.py` reports 67 → 67 with zero
new/regressed findings, xenon counts 67 C-blocks (baseline 77, none in
tools/git), the vulture ledger holds at 1378 identities, mypy --strict has
no errors outside the pre-existing maistro_bootstrap import-resolution gaps,
and both suite inventories match.

## Independent verification round (head d21d5f28e839, post develop-sync)

Re-executed fresh at the merge head that carries the develop sync
(8c8fc8d6706a) — the validation rounds above predate it, so none of their
claims were carried forward. Executed evidence: driver checks in job
d747e1ab348c all green (`ruff check` / `ruff format --check` clean; 73
passed in `tests/tools/git/test_server_security.py` +
`maistro-rsi/tests/test_cli.py` + `test_selfbranch.py`; suite inventories
match — maistro-core 12265, maistro-rsi 851); the two prior blocking
Quality gates re-run locally with CI's exact argv —
`check-radon-baseline.py` exit 0 (145 = 145, zero new/regressed/stale) and
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exit 0 (1361 = 1361); `mypy packages/maistro-core/src`
reports only the 5 pre-existing environment-only maistro_bootstrap
import-not-found errors in files this branch does not touch. The
agent-reachable clone path (`maistro_rsi.selfbranch` → hardened
`git_clone`) is unchanged by the sync; raw `git clone` sites remain limited
to the operator CLI trust domain (`rsi harvest --clone-url` / `--repo-dir`,
`_builders_tui.py`, local-loop baseline of the operator-configured repo
path). PR #1729 body and branch commits carry no closure keywords
("Refs #404" only).
