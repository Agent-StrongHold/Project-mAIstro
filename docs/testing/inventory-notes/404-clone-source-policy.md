---
inventory-delta:
  packages/maistro-core/tests: +32
  packages/maistro-rsi/tests: +12
---
# Clone-source policy: hosts, digest pins, executable redirect/submodule enforcement (#404)

The first #404 round (`404-reject-git-protocol.md`) closed the scheme hole:
`git://` is rejected by both clone surfaces. Independent verification found
the remaining acceptance gaps: the scheme gate accepted every https host on
earth (no explicit source policy), nothing pinned candidate source to a
commit digest, the redirect/submodule argument was comment-only, and the
tests covered case variants only. This change closes those gaps.

A follow-up round closed the last unpinned production clone surface: the RSI
self-branch cycle (`maistro_rsi.selfbranch`) cloned policy-vetted URLs with
no way to name the digest it was branching from. `SelfBranchAttempt.commit`
now carries an optional full-digest pin, `RsiCycleConfig.source_commit`
feeds it, and `SelfBranchResult.cloned_commit` reports the digest `git_clone`
verified with its post-fetch `rev-parse HEAD` verdict — the cycle's audit
trail names the exact source object it branched, patched and tested.

## Policy (`maistro.tools.git.server`)

- `validate_clone_source(url)` is the one gate: `git://` (any casing) is the
  unauthenticated-transport verdict; https/ssh must additionally name a host
  on `_ALLOWED_CLONE_HOSTS` (deployment override:
  `MAISTRO_GIT_CLONE_ALLOWED_HOSTS`, comma-separated; user-info does not
  change the host); scp-style `git@host:path` and any other scheme spelling
  is refused on spelling; a bare path qualifies only as a *verified local
  source* by passing the same workspace-root validation as the destination.
  `maistro_rsi.__main__` harvest gates its `--clone-url` through the exact
  same function — one verdict, no second policy to drift.
- `git_clone(commit=...)` pins the checkout: the pin must be a full 40/64-hex
  digest (a ref name or short sha is remote-repointable), is fetched directly
  by digest, and the final `rev-parse HEAD` verdict runs after all fetching —
  a ref that moves mid-clone (TOCTOU) fails the call instead of silently
  delivering different content than the audited digest. `pinned_commit`
  carries the verified value in the result.
- The clone argv now carries `-c protocol.git.allow=never` and
  `-c http.followRedirects=false`: git itself refuses the git:// transport
  (even via a `.gitmodules` entry or a redirect) and refuses to follow
  redirects (the default `initial` still follows a cross-host initial
  redirect, which would let an allowed host's open redirect pick the real
  source). The RSI harvest clone argv carries the same pins, and both
  surfaces pass the URL after `--`.

Signature verification of the pinned object is deliberately out of scope: it
requires a configured trust anchor (whose keys sign what?) and no production
surface configures one; the digest pin over an authenticated transport is the
identity policy that exists end to end today.

Test delta (+32 node IDs in `packages/maistro-core/tests`, +12 in
`packages/maistro-rsi/tests`):

- `tests/tools/git/test_server_security.py` (+29):
  - host policy (+7): `blocked_clone_host` for off-allowlist hosts incl. the
    `github.com@evil.com` userinfo trick; not-overstrict cases (case, port,
    user-info); the env override admitting a deployment's own forge.
  - scheme spelling/encoding (+5): scp-style, uppercase scheme, `git+ssh://`,
    percent-encoded scheme, and an encoded-host `git://` that cannot
    resurrect the unauthenticated verdict.
  - verified local sources (+2): a workspace-root path is accepted; `/etc`
    and a `-`-prefixed flag string are not.
  - executable redirect/submodule enforcement (+3): the `-c` pins are
    asserted in the clone argv; real git refuses a live HTTP 302
    (`followRedirects=false`) leaving no checkout; real git refuses a
    `git://` submodule URL under the pin and refuses `git://` ls-remote in
    transport selection — before any connection.
  - digest pinning/TOCTOU (+12): non-digest pins refused pre-spawn (×6);
    pin to non-tip digest fetched and verified, pin to tip verified without
    refetch, uppercase pin normalized, unknown digest fails closed; the
    end-to-end TOCTOU case (ref moves between decision and fetch — an
    unpinned clone tracks it, a pinned clone still delivers the audited
    digest); the argv proves the verdict runs before success and the pins
    ride with the clone.
  - `tests/cli/test_builders.py` (+3): the builders TUI's `_open_repo` is
    where classification becomes a `git clone` subprocess — the git://
    rejection is now driven at runtime (casing-proof, naming the policy,
    spawning no subprocess and recording no session), alongside a local-path
    control proving the gate is on the transport only.
- `tests/test_harvest_entry_point.py` (+6): the harvest `--clone-url` gate —
  four refused URLs exit 2 with no subprocess and no work tree (including
  the named git:// verdict), and the allowed transport reaches git with the
  enforcement pins and the `--` separator.
- `tests/test_selfbranch.py` (+5, `TestSourceCommitPinning`): the self-branch
  clone surface closes the last unpinned #404 gap — an attempt's `commit`
  pin reaches `git_clone`; the unpinned default is explicit (no pin passed,
  no `cloned_commit` reported); a verified pin is recorded on the result;
  a failed clone reports no identity; and an end-to-end run against real git
  pins the origin's HEAD digest and proves the branched/patched workspace
  sits exactly on that object.
- `tests/test_runner.py` (+1): `RsiCycleConfig.source_commit` is threaded
  into the attempt the cycle hands to `run_self_branch_attempt`.

Existing tests updated, counts unchanged: `test_server.py` and two
`test_server_security.py` cases cloned from `example.com`, which the new
explicit host policy refuses by design — they now clone from allowlisted
hosts so they still exercise the subprocess paths they were written for.
