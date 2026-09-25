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

- `legacy_dag_node` carries no `SandboxFence` (#79): `NodeContext` has
  `attempt_id`/`node_run_id` but no lease epoch or fencing token, and a fence
  invented from those would be a lie. The canonical fence machinery
  (`SandboxFence`, `fenced_commit`, backend env injection) is in place and
  tested; threading a real lease into legacy nodes is runner work outside
  this repair.
- On a Tier-3-only host, unattended legacy DAG nodes now refuse where the
  retired executor sometimes "succeeded" on a claimed gVisor boundary. That
  is the honest downgrade the support matrix documents; deployments needing
  unattended execution need a Tier-2 backend behind the protocol, and #81's
  installer preflight already reports the real ladder.
- Child-issue closure states (#76–#81, #811, #1197, #1198) are not
  verifiable from this worktree; no GitHub action is taken from here.

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
