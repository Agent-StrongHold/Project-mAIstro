---
inventory-delta:
  packages/maistro-core/tests: +37
---

# Candidate-source policy for `git_clone` (issue #404 / [M6 deferred])

Rejects unauthenticated `git://` clone URLs so an on-path attacker cannot
substitute repository content that RSI later builds/tests. Thirty-seven
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
  https/ssh allows and `file=user` (the git transport whitelist),
  `http.followRedirects=false` (redirects and protocol-downgrade hops fail
  instead of being followed), and `http.sslVerify=true`. The whitelist is
  applied at three layers, because `-c` flags are invocation-scoped (the
  clone neither writes them into the destination repo nor are they inherited
  by a later command): they ride ahead of the clone itself, ahead of every
  later git command the server issues in the workspace (GIT_CONFIG_PARAMETERS
  carries them into child git processes, so a server-issued `git submodule
  update` pins the submodule's internal clone), and they are persisted into
  the destination repo's local config post-clone, where in-repo
  fetch/pull/push read them. A hostile `.gitmodules` is additionally caught
  by the post-clone URL scan below.
- `commit=<full digest>` pins the checkout: the tool fetches the digest
  itself, detaches to it, and re-verifies HEAD, so a branch ref moving
  between resolution and fetch (TOCTOU) cannot change what gets built;
  `require_signed` demands `git verify-commit` accept the pin. The resolved
  HEAD digest is returned as `head_commit` on every success.
- Submodule URLs in the fetched `.gitmodules` are validated against the same
  policy; a malformed `.gitmodules` is rejected outright.
- The transport whitelist is enforced beyond the clone call: persisted into
  the destination repo config (fail-closed on write failure), and re-applied
  by every git command the server runs in the workspace.

## Test nodes

`test_server_security.py`: non-policy source URLs (10 parametrized cases —
git transport incl. case/encoded spellings, lookalike schemes, bare and
scp-like local paths, host-less https, plaintext http), the widened-allowlist
precedence invariant, host allowlist enforcement + case-insensitivity, the
transport hardening argv, `head_commit` reporting, pin-when-branch-moved
(TOCTOU success and rejection), fetch-failure → `commit_pin_mismatch`,
non-digest pins (3 cases), uppercase digest normalization, signature policy
fail-closed and pass, policy-compliant / non-policy (4 cases) / malformed
submodule URLs, the three local-source gating cases, destination-config pin
persistence + fail-closed pin-write, the per-command workspace pin, and a
real-git behavioral test of a pinned `git submodule update --init` refusing
a git:// submodule URL.

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

## Repair round (verifier findings at 3762152dbf, resolved on top of it)

The verification round at 3762152dbf probed git 2.53.0 and established that
the `-c protocol.*` flags passed ahead of `clone` are invocation-scoped: the
destination repo's `.git/config` carries no protocol/http keys, and a later
`git submodule update` runs unpinned — so the comments claiming the whitelist
was "inherited by submodule fetches" were false, and the post-clone
`_validate_submodule_urls` scan was the only actual submodule defense. Probed
again independently this round, plus the fix behavior:

- Reproduced: hardened `clone` → `git -C dest config protocol.allow` empty;
  later `git submodule update --init` against a hostile `git://` URL attempts
  the unauthenticated transport (hangs on connect in the probe sandbox).
- Established what does constrain later invocations: `-c` flags (equivalently
  GIT_CONFIG_PARAMETERS) on the *later* command reach the submodule's
  internal clone → `fatal: clone of 'git://…' failed` before any network;
  dest-local config is read by in-repo `fetch` (direct `git fetch git://…`
  → `fatal: transport 'git' not allowed`), but NOT by `clone`, which ignores
  the enclosing repo's config — hence both layers below.
- Fix in `maistro.tools.git.server`: `_TRANSPORT_PIN` is now the single
  source of the (key, value) whitelist; its flat `-c` form is passed ahead of
  the clone (unchanged `_CLONE_CONFIG_HARDENING` argv) AND ahead of every
  `_git` invocation (all workspace git tools: branch/add/commit/push/diff/
  status/log, plus the post-clone verification commands); and the clone
  persists the pairs into the destination's local config
  (`_pin_destination_transport`), failing the clone closed with
  `transport_pin_failed` when a write fails. The false comment claims at the
  old server.py:34-35/61-62 and the matching claim in this note were
  rewritten to state each layer's actual mechanism.
- Tests: four new nodes (destination-pin persistence argv + ordering,
  fail-closed pin write, per-command workspace pin argv, and a real-git
  behavioral test where a policy clone of a compliant-submodule repo, with
  `.gitmodules` flipped to `git://` afterwards, has its server-issued
  `git submodule update --init` refused by git itself); the scripted
  step lists now model the pin writes. Residual, stated plainly: a git
  process that is neither server-issued nor reading the destination repo
  config (e.g. a bare `git clone` run by an unrelated tool inside the
  workspace) is outside the pin's reach — the source policy's authority is
  the clone gate plus these two layers.

## Independent verification round (head 44a36c4bc73e, post develop-sync merge)

Executed fresh at the assigned head (prior claims not carried forward). The
develop-sync block from the previous round is resolved: `origin/develop`
(35f2e0158a91) is an ancestor of HEAD, which is a merge commit of exactly that
SHA, with no merge in progress and a clean worktree. `git diff --numstat
origin/develop HEAD -- quality/` shows only the additive
`quality/ac-state-notes/auto-404.json` (17 added rows, 0 removed) — no
multiset loss across the merge.

- Driver checks re-executed at this head: `ruff check .` clean; 120 passed in
  `packages/maistro-core/tests/tools/git` (including the real-git
  `test_pinned_workspace_refuses_submodule_update_over_git_protocol`); 77
  passed in the targeted set (`test_server_security.py` + RSI
  `test_cli.py`/`test_selfbranch.py`); `check-suite-inventory.py` matches for
  `packages/maistro-core/tests` (13089) and `packages/maistro-rsi/tests`
  (968). No closure keywords in branch commit messages or the PR body
  ("Refs #404" only).
- Independent mechanism probe with git 2.53.0 (separate sandbox, hand-written
  `.gitmodules` + gitlink so setup never touches the network): with
  `-c protocol.*` on the outer `submodule update --init`, the inner clone is
  refused client-side (`fatal: transport 'git' not allowed`); with the same
  keys present only in the superproject's local config and no `-c`, the inner
  clone attempts the actual connection (probe timed out attempting it). This
  confirms both the GIT_CONFIG_PARAMETERS propagation claim in the rewritten
  comments and that the persisted-config layer alone cannot protect a
  server-issued submodule update — both repair layers are required.
- Agent-reachable clone path audit re-run at this head: `maistro_rsi
  .selfbranch` uses the hardened `git_clone`; remaining raw `git clone` sites
  (`_builders_tui.py`, `rsi harvest --clone-url`/`--repo-dir`,
  `local_loop.py` repo_path) are operator CLI trust domain, outside the
  candidate-source policy surface.
- CI on PR #1729 at this head: Quality gate, security, SAST,
  exact-debt-ledger, lint-and-type-check, formal-conformance, Compliance
  registry, postgres (pg17/pg18), MinIO, durable-events all SUCCESS — but
  `test`, `integration-scope`, `coverage (no services)`, `coverage
  (PostgreSQL)`, and `docker-build` were IN_PROGRESS and `gates-ran` PENDING
  at review time. CI is therefore not green on this head yet and is recorded
  UNVERIFIED rather than inferred.

## Repair round (head 98a04e147, develop sync to 94781cf6b + CI conclusion)

Two facts closed this round, neither carried forward from earlier rounds:

- **Hosted CI on PR head 2ebefd794f8d concluded green.** Check-run snapshot:
  31 runs, 30 `success`, 1 `skipped`, none failed. The `gates-ran` commit
  status history on that head reads failure 04:55:11Z ("Required execution
  evidence is missing or non-executed" — a transient while checks were still
  arriving) → pending → **success 05:59:30Z** ("All required checks executed
  on this exact head"). The earlier `failure` is superseded, not the current
  state.
- **Develop sync.** `origin/develop` moved to 94781cf6b (handler-identity
  drift detection in `check-api-route-contracts.py`, its 5 tests, the 1860
  inventory note). That SHA is exactly this lane's declared develop base, and
  the branch was one commit behind (merge-base 534d475e). Merged
  `origin/develop` into `auto-404` → merge head 98a04e147, `ort` strategy,
  zero conflicts (verified beforehand: no path overlap between
  534d475e..origin/develop and 534d475e..2ebefd794). `git diff --numstat
  origin/develop HEAD -- quality/` shows only the additive
  `quality/ac-state-notes/auto-404.json` (+17/−0) — no multiset rows lost
  across either merge.

Re-executed fresh at 98a04e147 (prior claims not carried forward): `ruff
check .` clean; `ruff format --check .` 2917 files formatted; targeted set
`test_server_security.py` + RSI `test_cli.py`/`test_selfbranch.py` + the
synced-in `tests/test_check_api_route_contracts.py` → 113 passed; the
synced-in gate `check-api-route-contracts.py` exit 0 (279 handlers, 15
audited routes, 0 canned); `check-suite-inventory.py` matches for
`packages/maistro-core/tests` (13327) and `packages/maistro-rsi/tests`
(998), and the full 14-suite run matches including root `tests/` (4541);
quality ratchets with CI's exact argv against base 94781cf6b —
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exit 0 (1338 = 1338), `check-radon-baseline.py` exit 0
(143 = 143), zero new/regressed/stale on both; `check-reachability.py` exit
0; `check-security-inventory.py` exit 0. The 21 policy-surface git nodes
re-run individually green (10 parametrized non-policy URLs incl. git://
case/encoded spellings, host allowlist ×2, transport hardening argv,
submodule-URL policy ×5, destination-pin persistence, per-command pin,
real-git submodule-update refusal). Merge commit messages 2ebefd794..HEAD
carry no closure keywords.

## Independent verification round (head 77017baf1358)

Re-executed fresh at the docs head that carries every record above (prior
claims not carried forward), with independent mechanism probes instead of
trusting the recorded ones:

- Full local gate battery, CI's exact argv: `ruff check .` clean; `ruff
  format --check .` 2917 files formatted; 120 passed in
  `packages/maistro-core/tests/tools/git` (incl. the real-git
  `test_pinned_workspace_refuses_submodule_update_over_git_protocol`, which
  drives `git_clone` and `_git` against real subprocesses); 34 passed in RSI
  `test_cli.py` + `test_selfbranch.py`; `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0
  (1338 = 1338, zero unbanked); `check-radon-baseline.py` exit 0 (143 =
  143, zero new/regressed/stale); `check-reachability.py`,
  `check-security-inventory.py` exit 0; `check-suite-inventory.py` all 14
  suites match (26002 unique identities);
  `check-api-route-contracts.py` exit 0 (279 handlers, 15 audited routes).
- Probe (policy entrypoint, real tool): `git_clone` returns
  `blocked_url_scheme` for `git://`, `GIT://`, and `%67it://` spellings with
  the subprocess spawner replaced by a tripwire — rejection happens before
  any process spawns; with the same `_TRANSPORT_PIN` on the command line,
  real git refuses the transport itself (`ls-remote git://…` → exit 128,
  "transport 'git' not allowed") — defense in depth re-confirmed.
- Probe (mechanism, git 2.53.0, offline file:// superproject): plain `git
  submodule update --init` in a freshly cloned workspace → inner clone
  refused (`transport 'file' not allowed`), and `git -C dest config
  protocol.allow` is empty after a `-c`-pinned clone (0 protocol/http keys
  in dest/.git/config) — the `-c` flags are invocation-scoped, exactly as
  the rewritten comments state; with `-c protocol.file.allow=always` on the
  *outer* `submodule update --init`, the inner clone succeeds —
  GIT_CONFIG_PARAMETERS propagation to child git processes confirmed. Both
  pin layers (per-command re-application + persisted dest config) remain
  necessary and neither alone is sufficient.
- Merge integrity re-verified: `origin/develop` (94781cf6b) is an ancestor
  of HEAD; `git diff --numstat origin/develop HEAD -- quality/` shows only
  the additive `quality/ac-state-notes/auto-404.json` (+17/−0). No
  auto-close keywords in 2ebefd794..HEAD messages (only the synced-in
  develop PR references #1860/#1976).
- CI scope of this record: hosted CI concluded success on PR head
  2ebefd794f8d (recorded above); heads 98a04e147/77017baf1 add only the
  conflict-free develop merge and this docs commit. No hosted run for those
  heads is observable from this sandbox and pushing is prohibited here, so
  CI on the exact branch head is recorded UNVERIFIED — the required gates
  were instead proven locally with CI's argv at this head.

## Independent verification round (head e8b8c0352590, develop sync to 2728e3a58145)

Re-executed fresh at the assigned verification head (prior claims not carried
forward). Merge shape: HEAD is exactly `20113e003` (docs head) merged with the
declared develop base `2728e3a58145` — the merge's second parent equals the
declared base SHA. The delta `77017baf1..HEAD` is docs-only (the synced-in
M8-I research plan plus this note); `git diff --name-only 77017baf1..HEAD --
packages/maistro-core/src/maistro/tools/git/ packages/maistro-core/tests/
tools/git/ packages/maistro-rsi/tests/` is empty, so the policy surface is
byte-identical to the fully-probed round at 77017baf1. `git diff --numstat
2728e3a58145..HEAD -- quality/` shows only the additive
`quality/ac-state-notes/auto-404.json` (+17/−0) — no multiset rows lost
across the merge, and `quality/` is byte-identical to the 77017baf1 round.

- Executed at this head: `ruff check .` clean; `ruff format --check .` 2917
  files formatted; targeted set `test_server_security.py` + RSI
  `test_cli.py`/`test_selfbranch.py` → 77 passed (including the real-git
  `test_pinned_workspace_refuses_submodule_update_over_git_protocol`, which
  drives `git_clone` and `_git` against real subprocesses and lands the
  persisted `protocol.allow=never` in the destination config before refusing
  a git:// submodule fetch); `check-suite-inventory.py` matches for
  `packages/maistro-core/tests` (13327) and `packages/maistro-rsi/tests`
  (998).
- Quality ratchets with CI's exact argv against base 2728e3a58145:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 (1338 = 1338); `check-radon-baseline.py` exit 0
  (143 = 143). The develop syncs also brought in
  `check-api-route-contracts.py`: exit 0 (279 handlers, 15 audited routes,
  0 canned) and its synced-in `tests/test_check_api_route_contracts.py` →
  36 passed.
- No closure keywords in `77017baf1..HEAD` commit subjects/bodies (only the
  synced-in develop references #908/#1969); PR #1729 body still says
  "Refs #404" only.
- Hosted CI on this exact head: combined commit status `pending` at review
  time (block, DevSkim, Gate C, ADR front-matter, exact-debt-ledger, SAST,
  devskim SUCCESS; integration-scope and the Quality gate IN_PROGRESS;
  test, the four coverage jobs, lint-and-type-check, security,
  formal-conformance, compliance, supply chain, pr-base, workflow-lint
  QUEUED) — recorded UNVERIFIED, not inferred from the earlier heads. Scope
  note: the last fully-concluded hosted run is on PR head 2ebefd794f8d
  (green, recorded above); the only deltas since are the two conflict-free
  docs-only develop merges and this lane's own docs commits — no source or
  test surface moved (`2ebefd794..HEAD` touches only
  `docs/` and the synced-in `scripts/check-api-route-contracts.py` with its
  test file, both re-run locally here).

## Independent verification round (head 7b68d0e7ed4b, develop sync to b3662bb3719a)

Re-executed fresh at the assigned verification head (prior claims not carried
forward). Merge shape: HEAD's second parent is exactly the declared develop
base `b3662bb3719a`; the policy surface is byte-identical to the
fully-concluded-green head `2ebefd794` (`git diff --name-only 2ebefd794..HEAD
-- packages/maistro-core/src/maistro/tools/git/ packages/maistro-core/tests/
tools/git/ packages/maistro-rsi/tests/` is empty). The sync brings in
develop's M8-B1 routing benchmark (script, 28-node test file, workflow) —
re-run locally here. `git diff --numstat b3662bb..HEAD -- quality/` shows only
the additive `quality/ac-state-notes/auto-404.json` (+17/−0); no multiset rows
lost across the merge.

- Local gate battery with CI's exact argv at this head: `ruff check .` clean;
  `ruff format --check .` 2919 files formatted; `check-merge-markers.py` ok;
  `verify-monorepo-layout.sh` exit 0; mypy over the nine CI-listed src trees →
  "Success: no issues found in 941 source files"; 120 passed in
  `packages/maistro-core/tests/tools/git`; the full `packages/maistro-core`
  suite → 12438 passed, 888 skipped, 1 xfailed; targeted set
  (`test_server_security.py` + RSI `test_cli.py`/`test_selfbranch.py`) → 77
  passed; synced-in `tests/test_bench_model_routing.py` → 28 passed;
  `check-suite-inventory.py` → all 14 suites match (26030 identities);
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 (1338 = 1338); `check-radon-baseline.py` exit 0
  (143 = 143); `check-reachability.py` exit 0; `check-security-inventory.py`
  exit 0; `check-api-route-contracts.py` exit 0 (279 handlers, 15 audited
  routes, 0 canned). No closure keywords in `2ebefd794..HEAD` commit subjects
  or bodies (develop's own PR references are `(#NNNN)` merges, not issue
  closures); PR #1729 body remains "Refs #404" only.
- Independent live-daemon mechanism probes (git 2.53.0, fresh superproject
  each time — a residue `.git/modules/<name>` from an earlier control run
  makes a later `submodule update` materialize the worktree offline, so every
  probe below starts from a clean worktree): (a) unpinned control against a
  running `git daemon` serving the declared submodule URL → full clone, attack
  surface confirmed; (b) the `_TRANSPORT_PIN` keys as `-c` flags on the outer
  `git submodule update --init` → nested clone refused client-side
  (`fatal: transport 'git' not allowed`), 0 daemon connections —
  GIT_CONFIG_PARAMETERS propagation into the submodule's internal clone
  confirmed as the rewritten comments state; (c) the same keys persisted only
  in the superproject's local config, no `-c` flags → the nested clone
  proceeds over `git://` and lands content — the persisted-config layer alone
  cannot protect a server-issued submodule update, so the per-command
  re-application layer is load-bearing, exactly as the comment block claims.
- Hosted CI on this exact head is not observable or triggerable from this
  sandbox (no push), so it stays UNVERIFIED; the required gates were re-proven
  locally with CI's argv above, and the hosted run last fully concluded green
  on PR head 2ebefd794f8d whose policy/test surface is byte-identical here.
