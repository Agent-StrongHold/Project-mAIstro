---
inventory-delta:
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
