---
inventory-delta:
  packages/maistro-core/tests: +18
---
# Reject the unauthenticated `git://` clone transport (#404)

`maistro.tools.git.server.git_clone` no longer accepts `git://` URLs. The
scheme gate stays an allowlist — `https://`, `ssh://` — but `git://` now has
its own unconditional verdict (`blocked_unauthenticated_transport`, matched
case-insensitively because git parses remote schemes per RFC 3986) instead of
riding the generic `blocked_url_scheme` message. The git protocol provides
neither transport encryption nor server authentication, and the clones this
tool performs are candidate source for the RSI self-modification cycle
(`maistro_rsi.selfbranch` runs clone → branch → patch → build → test over the
result), so an on-path attacker substituting repository content over `git://`
was executable-source injection, not a formatting concern.

Why an unconditional check rather than a narrower allowlist entry: the RSI
hermetic tests legitimately widen the allowlist (monkeypatching
`_ALLOWED_CLONE_SCHEMES` to opt into `file://` origins), and a gate that only
lived in the allowlist would widen with it. The unauthenticated-protocol
rejection is deliberately not overridable by that knob. Redirects and
submodules cannot smuggle the scheme back in: git's http transport follows
only http(s) redirects, and the tool surface never runs `git submodule
update`, so `.gitmodules` URLs are never fetched.

Test delta (+18 node IDs in `packages/maistro-core/tests`):

- `tests/tools/git/test_server_security.py` (+7):
  - `test_git_clone_rejects_git_protocol_before_git` (×3): `git://` URLs —
    including a nonstandard host/port — are rejected with the explicit error
    code and a named stdout reason, and a subprocess spy proves git is never
    spawned for them.
  - `test_git_clone_rejects_git_protocol_case_insensitively` (×2): `GIT://`
    and `Git://` receive the same unauthenticated-transport verdict rather
    than slipping into whichever message a case-sensitive comparison would
    produce.
  - `test_git_clone_allows_authenticated_transports` (×2): `https://` and
    `ssh://` still pass the gate and reach git, with the URL pinned after the
    `--` argv separator so no scheme can be reinterpreted as a flag.
- `tests/cli/test_builders.py` (+11): the builders TUI classifies what to
  clone with `_is_git_url`, whose `.endswith(".git")` catch-all used to wave
  `git://host/repo.git` straight into its `git clone` subprocess — a second,
  independent acceptance path for the unauthenticated protocol. That path now
  rejects `git://` before classification (any casing), states the policy in
  the UI instead of falling into "Not a directory", and
  `TestGitUrlClassification` pins the classification both ways (4 rejection
  cases incl. `GIT://...repo.GIT`, 6 authenticated-transport cases, 2 local
  path cases) via a minimal textual stub (textual is not installed in the
  test environment; the stub covers only the names the module binds at
  import time).

Companion change: the two RSI hermetic tests (`test_selfbranch.py`,
`test_cli.py`) dropped `git://` from their patched allowlist tuples — the
patch replaces the production value in-process, so listing `git://` there
advertised an escape hatch that no longer exists and no test ever used. Their
comments now state that no caller, and no test knob, may reintroduce the
protocol. RSI suite counts are unchanged.
