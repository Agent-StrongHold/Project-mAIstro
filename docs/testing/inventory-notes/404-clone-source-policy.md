---
inventory-delta:
  packages/maistro-core/tests: +19
  packages/maistro-rsi/tests: +12
---
# Clone-source policy: hosts, digest pins, executable redirect/submodule enforcement (#404)

Develop-side round (M6 WIP 159fbafe9), recorded here as merged into
`auto-404` (PR #1729's implementation). The develop commit carried a second,
parallel #404 implementation; the merge resolution kept the branch's
enforcement core — the three-layer transport pin (`_TRANSPORT_PIN`), the
verified-local-root gate for `file://`, the TOCTOU fetch/detach/re-verify
pin flow, `require_signed`, and the post-clone `.gitmodules` URL scan — and
adopted develop's public surface on top of it (`validate_clone_source`,
`ClonePolicyError`, `_COMMIT_DIGEST_RE`, the `git_remote_tip` tool, and the
resolve-then-pin `git_clone` flow), so every surface that clones shares one
verdict. Details of the resolution are in
`404-git-clone-source-policy.md` (develop-sync merge round) and
`404-develop-sync-merge.md` (node-ID ledger reconciliation).

## The merged policy (`maistro.tools.git.server`)

- `validate_clone_source(url)` is the one gate: `git://` (any casing) is
  hard-rejected before any allowlist logic; https/ssh must additionally name
  a host on the allowlist — `MAISTRO_GIT_CLONE_HOSTS` (comma-separated)
  overrides, and without it the default forges (github.com, gitlab.com,
  bitbucket.org, ssh.github.com) are the allowlist, so remote sources are
  always host-restricted; scp-style `git@host:path`, `-`-prefixed flag
  strings, and any other scheme spelling are refused on parsing, not
  prefix-matching. A local source is clonable only as `file://` with the
  scheme tuple explicitly widened AND the path under a verified root
  (`_ALLOWED_LOCAL_SOURCE_ROOTS`, empty in production — bare local paths
  are refused, not workspace-validated as this round's original draft had
  it). `maistro_rsi.__main__` harvest gates its `--clone-url` through the
  exact same function, and the builders TUI (`_builders_tui._open_repo`)
  runs the same verdict before its clone — one policy, no second to drift.
- `git_remote_tip` resolves a policy-vetted remote's HEAD to a full digest
  under the same source policy and transport pins; `git_clone` with an
  omitted pin resolves through it first, so **no successful clone is
  unpinned**. A `commit=<full digest>` pin is used as-is; the pinned digest
  is fetched by itself, checked out, and re-verified against HEAD after all
  fetching (TOCTOU guard); the proven digest is reported as `head_commit`
  and `pinned_commit`.
- The clone argv carries the branch's full transport whitelist
  (`protocol.allow=never` + explicit https/ssh allows + `protocol.file.allow=user`,
  `http.followRedirects=false`, `http.sslVerify=true`) ahead of the
  subcommand, and the URL sits after `--`; the RSI harvest clone argv
  carries its pins the same way. git itself refuses the git:// transport
  and refuses redirects, whatever a `.gitmodules` entry or a server
  response asks for.

Signature verification of the pinned object remains out of scope: it
requires a configured trust anchor (whose keys sign what?) and no production
surface configures one; the digest pin over an authenticated transport is the
identity policy that exists end to end today.

Test delta as merged (+19 node IDs in `packages/maistro-core/tests`, +12 in
`packages/maistro-rsi/tests`; the original +32 core claim covered a parallel
`test_server_security.py` suite whose API the merge resolution did not
retain — the branch's suite already covers those invariants):

- `tests/cli/test_builders.py` (+18): the builders TUI's `_open_repo` is
  where classification becomes a `git clone` subprocess — refused sources
  (git:// in any casing, plaintext http, off-allowlist hosts, scp-style,
  `-`-prefixed flag strings) are named and blocked at runtime, spawning no
  subprocess and recording no session; a local path still takes the
  directory branch (the gate is on the transport, not on opening repos);
  and an allowed https source reaches the shared, digest-pinning clone
  authority with the UI cache under the approved workspace root.
- `tests/tools/git/test_server.py` (+1 net): the `git_clone` orchestration
  contract for the merged resolve-then-pin flow — an omitted pin resolves
  via `git_remote_tip` before cloning, an explicit pin skips resolution, a
  failed resolution fails closed before any clone subprocess.
- `tests/test_harvest_entry_point.py` (+6, rsi): the harvest `--clone-url`
  gate — refused URLs exit 2 with no subprocess and no work tree, and the
  allowed transport reaches git with enforcement pins and the `--`
  separator.
- `tests/test_selfbranch.py` (+5, rsi, `TestSourceCommitPinning`): the
  self-branch clone surface — an attempt's `commit` pin reaches
  `git_clone`; a verified pin is recorded on the result as `cloned_commit`;
  and the end-to-end live cases run real git: a pinned attempt branches
  exactly from the audited digest, and the unpinned default resolves the
  tip and branches from that object.
- `tests/test_harvest_clone_source.py` (+5, rsi, new file): real-git
  materialization of the harvest clone — the workspace branches from the
  resolved digest with a materialized work tree and the pinned LF work
  tree; an unresolvable base ref or unreachable remote refuses before any
  workspace exists.
- `tests/test_runner.py` (+1, rsi): `RsiCycleConfig.source_commit` is
  threaded into the attempt the cycle hands to `run_self_branch_attempt`.

Existing tests updated, counts unchanged: the RSI hermetic real-git tests
(`test_cli.py`, `test_selfbranch.py`) register the `file://` origin as a
verified local source root alongside the widened scheme tuple — the merged
policy's local-source gate — so they still exercise the same subprocess
paths they were written for.
