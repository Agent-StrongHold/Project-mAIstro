---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/maistro-core/tests: +5
  packages/maistro-core/tests/sandbox: +5
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
