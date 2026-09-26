---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/maistro-core/tests: +22
  packages/maistro-core/tests/sandbox: +22
---
# #18 — canonical sandbox authority

The canonical selector now registers a socket-less container backend only when
host detection supplies a concrete launcher, while VM-required policies remain
fail-closed when no VM backend is registered. The compatibility
`SandboxConfig.network` field is mechanically rejected in favor of the
policy-owned egress grant. Host mount authorization and descriptor-relative
file transfer tests cover rejected roots and symlink non-following behavior.

## Repair disposition (2026-09-23, branch `auto-18`)

Two things happened after the commits above, and both are recorded here
because the worktree carried them as uncommitted state.

**The recorded-inventory gate failure was real and is fixed.**
`scripts/check-suite-inventory.py` refused this suite because the
`inventory-delta` above named `packages/maistro-core/tests/sandbox` while
`RECIPES` had no entry for it — a delta nothing collects. Commit `5691b0927`
registered the suite in `RECIPES`, `SUITE-INVENTORY.md` and `baseline.json`.

**A crashed follow-up run's uncommitted sandbox work was evaluated and not
integrated.** It proposed (a) `VMSandboxBackend`/`GVisoSandboxBackend`
classes that declare `tier = "vm"`/`"gvisor"` while executing every command
as a bare `asyncio.create_subprocess_exec` on the host, auto-registered by
`build_selector` whenever detection evidences the tier, (b) a
`maistro.sandbox.executor.execute_node` adapter, and (c) pointing
`legacy_dag_node._run_node_subprocess` at that adapter. Rejected on the
record:

- (a) is precisely the false boundary ADR-093 and
  `docs/security/SANDBOX-SUPPORT-MATRIX.md` refuse — a host with KVM and a
  VMM binary would run untrusted code with **no** isolation while the
  selector reported Tier 1. The selector's `TierMismatchError` guard cannot
  catch this, because the backend lies in its own declaration, not in the
  registration call. Tiers 1 and 2 stay "detected, not implemented"; the
  ladder refuses.
- (b) did not work against either shipped backend: `write_file(instance,
  "/tmp/code.py")` is refused by `BubblewrapSandboxBackend._resolve` (writable
  root is `/work`) and by `write_beneath` (absolute guest paths must sit under
  `/work`), and the exec invocation read back a path the backends do not
  map. It also dropped the requested egress: `WorkloadPolicy.network_allowed`
  was never converted to an `EgressGrant`, so the config stayed `DENY_ALL`
  and the node's LLM-gateway call would be silently denied.
- (c) breaks the pinned tests (`test_graph_runner_injection.py`,
  `test_node_metrics_are_measured.py`) that stub
  `services.hyperlight_executor.get_executor`; converging that consumer onto
  the canonical substrate remains open work for #18 and must retire those
  pins deliberately, not incidentally.

The rejected work is preserved unmerged at `~/Git/wt/incoming-18.patch` and
`~/Git/wt/incoming-18-salvage/` (checksum-verified), outside the repository.

## Convergence repair (this change)

The residual findings from the NEEDS-DEEP-REVIEW verdict are addressed without
repeating the rejected design's mistakes:

**`services/hyperlight_executor.py` is rewritten as an adapter behind the
canonical authority.** The module keeps its name, `get_executor()` seam and
legacy dict result contract — so `legacy_dag_node` (which imports
`get_executor` from exactly that module) and the injection pins keep their
seams — but everything policy-shaped now belongs to `maistro.sandbox`:

- the private tier integers, `_has_*` probes and five private launchers
  (hyperlight/firecracker/gVisor/bubblewrap/hardened-container) are deleted;
  selection is `SandboxSelector.select(WorkloadPolicy)` over the canonical
  ladder, assembled by `build_selector()`;
- `allow_network` becomes an explicit `EgressGrant(mode=HOST, reason=...)` or
  `DENY_ALL` — the dropped-egress failure of attempt (b) cannot recur, and
  the grant reaches `resolve_grant` so the audit line names its reason;
- `mode` maps onto `ExecutionMode` with unknown modes read as unattended
  (default deny, ADR-093 decision 6), and the untrusted mode floors do the
  rest: an unattended node on a host without a `gvisor`-or-better *backend*
  refuses with the selector's reason — including a `runsc`-on-PATH host,
  which the retired executor wrongly served through a launcher the support
  matrix calls "detected, not implemented";
- the sandbox environment is exactly the caller's explicit dict: canonical
  backends start from a cleared environment, so the retired behavior of
  handing the host's whole `os.environ` to every unattended node
  (the #78 failure mode) is structurally gone, not filtered;
- `memory_mb`/`timeout_s` cross as policy ceilings through
  `build_config`'s clamp; untrusted code reaches the backend as a `-c` argv
  element — there is no generated wrapper source left to template into.

**The pins that gated the retired internals were retired deliberately, and
each replacement pins the same property against the adapter or the canonical
machinery:** mode floors and ladder order in `test_sandbox_mode_gating.py`
(now via injected selectors/stub backends, including the
detected-but-unimplemented gVisor refusal); the transport-kill behavior in
`test_hyperlight_executor.py` (owned by the canonical backends and covered by
the conformance suite); the wrapper-templating pin in
`test_graph_runner_injection.py` (there is no wrapper; code crosses as argv
data, asserted with the original breakout payload); the `_backend = None`
pokes in `test_security_regression.py` (an empty selector). The
`get_executor` stubs in `test_graph_runner_injection.py` and
`test_node_metrics_are_measured.py` were preserved, not broken.

**A reachability/convergence gate ships: `scripts/check-sandbox-authority.py`.**
AST over every non-test file under `packages/`: no backend construction or
`maistro.sandbox.backends` imports outside the authority, no hand-assembled
launcher flag vocabulary (`--unshare-all`, `--share-net`, `--die-with-parent`,
`--clearenv`, `--new-session`, `--runtime=runsc`,
`firecracker-containerd`), no `hyperlight`/`firecracker` imports (no
Tier-1/2 backend ships), and a positive assertion that the adapter still
imports `maistro.sandbox`. Wired as a `quality.yml` step beside the
execution-lifecycles and model-egress convergence gates, so CI fails if a
supported code-exec consumer stands up a sandbox outside the canonical
authority.

Known residuals, recorded rather than hidden:

- ~~`legacy_dag_node` carries no `SandboxFence` (#79)~~ **resolved in the
  2026-09-26 round — see "Fence threading repair (#79)" below.**
- On a Tier-3-only host, unattended legacy DAG nodes now refuse where the
  retired executor sometimes "succeeded" on a claimed gVisor boundary. That
  is the honest downgrade the support matrix documents; deployments needing
  unattended execution need a Tier-2 backend behind the protocol, and #81's
  installer preflight already reports the real ladder.
- Child-issue closure states (#76–#81, #811, #1197, #1198) are not
  verifiable from this worktree; no GitHub action is taken from here.

## Fence threading repair (#79, 2026-09-26 round)

The recorded residual — the canonical fence machinery existed and was tested
but no production executor put a real lease on the wire — is closed on the
same production backend the selector already picks:

- `NodeContext` carries the Attempt's lease identity (`lease_epoch`,
  `fencing_token`) beside `node_run_id`/`attempt_id`. The durable attempt
  executor stamps it in `context_for_attempt` from the live
  `attempt.execution_lease` — the same lease whose token the store checks at
  every `transition_attempt`, so there is exactly one source of fence truth.
- `maistro.sandbox.fence_from_context(context)` (exported from
  `maistro.sandbox`) is the one way to project that stamp onto the boundary
  fence. Partial identity reads as `None`, never a weaker fence, mirroring
  `SandboxFence.from_env`. The projection lives in the sandbox substrate, so
  the graph node contract stays sandbox-free.
- The production path consumes it end to end: `LegacyConductorNode._execute`
  (sandbox tier) → `_run_node_subprocess(fence=...)` →
  `SandboxExecutor.execute_node(fence=...)` → `SandboxConfig.fence` (frozen;
  set via `dataclasses.replace`) → canonical container/bubblewrap backends
  inject `fence.to_env()` as `MAISTRO_FENCE_*` environment. A node executed
  under an Attempt lease now runs in a sandbox that carries the fence of that
  Attempt; nothing synthesizes a fence anywhere on the path.
- What this deliberately does not do: `fenced_commit` enforcement for guest-
  side external writes stays with the publishing caller (the legacy node
  script publishes only through its parent, whose writes the store's own
  token check already fences). The runner-level gap — no lease epoch to
  fence from — is what this repair closes; guest-side publication policy is
  the publisher's, not the substrate's.

## Verification repair (2026-09-23, same branch)

Independent acceptance validation of the convergence repair found two real
defects; both are fixed here, with the evidence that produced them:

**1. The lane broke the hard type gate it ships inside.** CI's mypy step is
`uv run mypy --strict packages/maistro-core/src` (quality.yml, 0-baseline).
Files this lane added/changed carried four errors:
`backends/container.py:116/143/189` (`str | None` launcher reaching
`create_subprocess_exec`) and `tools/sandbox/server.py:52` (a compatibility
facade returning `Any` from a `str` function). Fixed at the source — the
launcher is narrowed by the constructor's own refusal, and the facade declares
its `bytes` — not by widening any config. `mypy --strict` is now clean across
all 629 core source files, and the pyright ratchet moved 21 → 20 errors
(baseline 21).

**2. The container backend could not read its own workspace — found by the
conformance coverage #80 requires.** `build_selector` prefers the container
tier over bubblewrap wherever a runtime is reachable, so on Docker/Podman
hosts `ContainerSandboxBackend` IS the production boundary; it had no tests.
The new `tests/sandbox/backends/test_container.py` (argv-boundary assertions
that run anywhere; spawn/exec/destroy, default-deny network, env-allowlist,
output-bound and timeout assertions against the real daemon where one is
reachable) failed immediately: the container runs as uid 65532 while the
host-created workspace was `mkdtemp` 0700 with 0600 files, so
`ls /work` → Permission denied — the backend's primary write-then-execute
flow was broken. Fix: the backend-created workspace is chmod 0755 and
`write_file` writes 0644 (`paths.write_beneath` grew a `mode` parameter,
default unchanged at 0600 for same-uid backends); the host-side exposure is
still gated by the authorized-root parent chain. All 17 container tests pass
against a live daemon; the full sandbox suite is 139 passed / 36 skipped
(kernel-bound bubblewrap tests skip on this host, whose userns is restricted —
the same hosts CI enables userns for, so they run there).

## Residual findings from the same validation (recorded, not repaired here)

Two production consumers still reach a sandbox **outside** the canonical
authority, through the legacy `maistro.tools.sandbox.docker` module — which
remains a full second launcher: it hand-assembles its own `docker run` argv,
re-adds `CHOWN/SETUID/SETGID` after `--cap-drop=ALL` (ADR-093 decision 3's
hardened profile says cap-drop ALL, full stop), runs the image's default user
(often root, vs the canonical backend's fixed 65532), and gates networking on
a settings boolean instead of a policy `EgressGrant`. The shipped
`check-sandbox-authority.py` cannot see it: its flag vocabulary and class
names cover the canonical backends only.

- `packages/maistro-evolve/src/maistro_evolve/benchmarks/sandbox_exec.py:77`
  executes model-generated candidate code via `create_sandbox`. Under
  ADR-093 decision 6 this is unattended untrusted code: converging it onto
  the canonical ladder *refuses* it on every Tier-3-only host — the correct
  ADR answer, but a functional decision for the evolve owners (their evals
  fail closed until a Tier-2 backend exists), not a mechanical repair.
- `packages/maistro-rsi/src/maistro_rsi/sandbox/microvm.py:21` wraps the same
  legacy module as RSI's development `MicroVmSandbox`. The issue text places
  RSI-specific containment leaves under M5 #552's hierarchy; converging this
  seam is theirs, with the same refusal trade-off to own.

Both must be adapted (or the legacy module converted to a facade over the
selector, as `tools/sandbox/server.py` and the conductor adapter were) before
#18's "direct alternate sandbox APIs are retired/adapted" and "RSI consumes
this substrate" criteria are fully satisfied; `test_docker.py` pins the legacy
flags and must be re-based deliberately with that change. Recorded here
because the convergence CI cannot yet fail on this pair — extending its rule
set to the legacy launcher vocabulary is part of that same deliberate change.

## Verification round (2026-09-25, head `d5e654eb7`, no code changes)

Fresh independent acceptance validation of this branch. Every gate re-executed
green at this head: `ruff check .`, `ruff format --check .`,
`mypy --strict packages/maistro-core/src` (631 files, 0-baseline),
`scripts/check-sandbox-authority.py`, `scripts/check-suite-inventory.py`
(14 suites match, incl. this suite at 175), the vulture per-identity ledger,
sandbox suite 139 passed / 36 skipped (kernel-bound bwrap skips on this
userns-restricted host), `tools/sandbox` 69 passed, conductor
executor/gating/injection/security 34 passed, bootstrap #811 argv 38 passed.
The container conformance suite ran **against the live daemon**: 17/17 passed
(argv boundary, default-deny network, env allowlist, output bounds, timeout).
`maistro sandbox status` reports the honest ladder on this host: container
registered, vm/gvisor/bubblewrap refused with per-tier reasons — the
#81-aligned installer preflight (`platform_detect.SANDBOX_AUTHORITY`) consumes
exactly this CLI.

Verdict recorded for the epic: the branch is green and its claims hold, but
three exit criteria remain open above this lane and are **not** closable by
another in-lane mechanical pass: (1) the evolve/RSI legacy-launcher residuals
above (a fail-closed functional decision for their owners plus a CI-gate
extension scoped to that same change), (2) #79 fence threading into
`legacy_dag_node` needs a real lease epoch in the runner's `NodeContext` —
inventing one from `attempt_id` alone would be a lie, (3) child-issue closure
states (#76–#81, #811, #1197, #1198) are GitHub state, unverifiable and
untouchable from this worktree. These go to deep review / owner coordination,
not back to this repair lane.

## Convergence repair, round 2 (2026-09-25, same branch)

This round was sent back to resolve exactly those residuals, and the two
code-level ones are now closed:

**The legacy launcher is retired; `tools/sandbox/docker.py` is the facade.**
The module kept its `create_sandbox(workspace, settings, env)` signature and
`SandboxContainer` handle shape, but every policy-shaped decision moved behind
`maistro.sandbox`: selection is `build_selector().select(policy)`; the policy
is honest about trust class (`min_tier="vm"`, AUTONOMOUS, untrusted — the
workloads reaching this seam are evolve candidates and RSI dev cycles, ADR-093
decision 6); egress is `DENY_ALL` unless the operator explicitly sets
`SandboxSettings.network_disabled=False`, which becomes an audited HOST grant
(same mapping as the conductor adapter); env is the caller's explicit dict;
there are no per-call launcher knobs (`SandboxSettings.image` no longer
crosses). Consequence, consistent with the conductor path: on a
container-only host `create_sandbox` raises `NoSuitableBackendError` — the
honest downgrade, not a regression, because the retired launcher "succeeded"
there by running a container it called a VM boundary. The evolve benchmark
returns a failed check (never a host fallback — its contract already said so);
RSI's dev sandbox refuses at `create_microvm_sandbox`, which is M5 #552's
territory for a real Tier-2 backend.

**The convergence gate now sees the container-launcher vocabulary and the
seams.** `scripts/check-sandbox-authority.py` rules 3/5 extended: `--cap-add`,
`--cap-drop`, `--security-opt`, `--tmpfs`, `--pids-limit`, `--read-only`,
`--network=none`, `--network=host`, `--privileged`, `--userns` may appear only
inside `maistro.sandbox`; the facade must keep importing `maistro.sandbox`
(facade-not-behind-authority); and AUTHORIZED_SEAM_POSTURE pins the posture of
files authorized to carry the vocabulary. Negative-tested: a synthetic
launcher, a regressed seam posture, and a drifted facade each fail the gate.

**A third invisible consumer surfaced and is dispositioned, not hidden:**
`maistro_bootstrap/builders/container_sandbox.py` hand-assembles its own
`docker run` argv. It is a *data-plane* sandbox — its bulk repo seed/sync
travels as tar over stdin/stdout pipes, which cannot fit the bounded
`SandboxProtocol.exec` capture (#1197), and maistro-bootstrap deliberately
does not depend on maistro-core, so it cannot import the authority. It is
registered as an authorized seam with posture pins (default-deny egress,
cap-drop, no-new-privileges, non-root uid 65532) — if its documented
containment regresses, CI fails. Its full convergence onto the selector
authority remains an owner decision (#18 follow-up), recorded here because
that is a protocol-capability gap, not a mechanical rewrite.

**`WorkloadPolicy.network_allowed` is no longer a dead parallel knob.** It is
now a consistency mirror: `__post_init__` rejects a policy whose flag
contradicts its `EgressGrant` — the same "mechanically rejected" disposition
the issue applies to `SandboxConfig.network`, applied to the policy layer's
duplicate. All shipped policies and both adapters already agreed; now the
constructor enforces it.

**The previous round's "vulture all green" claim was false at this head** —
re-run evidence: exit 1 at `32a1f1043` with three unbanked identities plus a
stale ledger entry. Fixed rather than banked (grants load from the base
revision, so a same-change grant cannot authorize anything):
`network_allowed` (fixed by the consistency check above),
`ExecResult.output_truncated` (dead convenience property, deleted; the fake-
backend overflow test pins the per-stream flags directly), `ensure_workspace`/
`CONTAINER_WORKSPACE` (dead with the retired launcher, deleted from
`tools/sandbox/workspace.py`; `validate_workspace_path` and its tests remain),
and the stale `selector.build_config` ledger entry pruned — it has callers in
product code since the server facade and this facade. The vulture gate now
exits 0 at this head.

Tests: `test_docker.py` rebased to facade translation (8 tests, real
`SandboxSelector` + stub vm backend, no daemon); `test_swebench.py` re-based
off live-Docker execution (stub vm-tier backend for the scoring plumbing; new
`test_host_without_vm_tier_fails_closed` pins the container-only-host
refusal); `test_sandbox_paths.py` re-pins `_safe_path`'s properties against
the canonical `_relative_parts`/`read_beneath`/`write_beneath`; selector
consistency tests added. Suites re-run green: core sandbox 143 passed /
36 skipped, core tools 393, evolve 646, RSI 721, conductor
gating/executor/injection/security 34, bootstrap 231; ruff, ruff format,
mypy --strict (631 files), check-sandbox-authority, check-suite-inventory
(14 suites), and the vulture ledger all pass at this head.

Remaining open, unchanged: #79 lease threading (runner-side, above this lane)
and GitHub closure states for the child issues.

## Verification round (2026-09-25, head `28911588e7ee`, no code changes)

Independent acceptance re-validation after the round-2 commit (the previous
verification job died on a provider timeout before recording anything, and the
round before this branch carried the recorded-inventory gate failure fixed by
`5691b0927`). Every gate re-executed green at this exact head:

- `ruff check .`, `ruff format --check .` (2533 files);
- `mypy` over all six declared package src trees (715 files) **and** CI's hard
  gate `mypy --strict packages/maistro-core/src` (631 files, 0-baseline);
- `scripts/check-sandbox-authority.py` — plus its rules exercised live:
  synthetic launcher (2 violations), direct backend construction (3),
  `import hyperlight` (1) all fail; clean `build_selector` use passes;
- `scripts/check-suite-inventory.py` — 14 suites match, including this suite;
- vulture per-identity ledger — exit 0 (1415 reviewed → 1414 findings);
- pytest: core 10100 passed / 651 skipped / 1 xfailed, core sandbox 143 passed
  / 36 skipped, core tools 393, evolve 646, RSI 721, conductor backend
  2658 passed / 1 skipped, bootstrap #811 argv 38;
- container conformance 17/17 **against the live daemon** (Docker 29.7.2), and
  `maistro sandbox status` reports the honest ladder on this host: container
  registered; vm (kvm present but not rw), gvisor (no runsc), bubblewrap
  (userns refused) each refused with its reason — the #81 preflight surface.

Acceptance criteria spot-verified against production behavior: the retired
`SandboxConfig.network` input raises in `build_config` and is test-pinned;
`WorkloadPolicy.network_allowed` contradicts its grant in `__post_init__`; the
selector refuses tier relabelling (`TierMismatchError`) and fails closed with
per-tier reasons (`NoSuitableBackendError`); host-side transfer walks
directory fds with `O_NOFOLLOW` and authorized roots reject symlinks; capture
is bounded per-stream with truthful `*_truncated`/`output_limit_exceeded`
flags and kill-on-overflow.

Still above this lane, unchanged: #79 lease threading into the runner's
`NodeContext`, child-issue GitHub closure states, and the bootstrap data-plane
sandbox's full convergence (owner decision, posture pinned by the gate).

## Verification round (2026-09-25, head `beace0425a7`, no code changes)

Re-validation after the docs-only inventory commit, run independently
(no driver check logs were supplied to this job, so every gate was executed
from scratch here). All green at this exact head:

- `ruff check .`, `ruff format --check .` (2533 files);
- `mypy --strict packages/maistro-core/src` (631 files, 0 errors) and the
  six-declared-src-tree mypy run (715 files, clean);
- `scripts/check-sandbox-authority.py` exit 0 — and its negative case
  re-proven live: a scratch module importing and constructing
  `FakeSandboxBackend` under `maistro_server` produced 3 violations and
  exit 1, then passed clean after removal;
- `scripts/check-suite-inventory.py` — 14 suites match (core sandbox 179);
- vulture per-identity ledger — exit 0 (1415 reviewed → 1414 findings);
- pytest: core sandbox 143 passed / 36 skipped (userns-restricted host),
  core tools 393 passed, conductor executor/gating/injection/security 34
  passed, evolve swebench+e2e and bootstrap 249 passed / 1 skipped;
- container conformance 17/17 **against the live daemon**;
- `maistro sandbox status` reports the honest ladder (vm not rw, no runsc,
  bubblewrap userns refused, container registered) — the #81 preflight
  surface wired as `platform_detect.SANDBOX_AUTHORITY`.

Policy-disposition spot-check against the real selector on this host:
`TRUSTED_TOOL`/`BROWSER_AUTOMATION` select the container backend;
`UNTRUSTED_CODE`/`BENCHMARK_EVAL` refuse with `NoSuitableBackendError` and
the per-tier reason (vm required, none registered); `DEV_ONLY` selects.
Criterion evidence re-confirmed in source: `SandboxConfig.network` raises at
`protocol.py:101`; `WorkloadPolicy.network_allowed` contradicts its grant in
`__post_init__` (`policy.py:74`); container backend sanitizes env
(`sanitize_env(config.env)`) and bwrap assembles `--clearenv`;
`SandboxFence`/`assert_fence_is_current` exist and are tested but are still
not threaded into the legacy DAG runner (no lease epoch in `NodeContext`).

Verdict unchanged from the previous round: the branch is green and its
claims hold; what remains (#79 runner-side lease threading, child-issue
closure states, bootstrap data-plane convergence) is above this lane and
goes to deep review / owner coordination.
