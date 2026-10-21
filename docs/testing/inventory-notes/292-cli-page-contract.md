---
inventory-delta:
  packages/hive-conductor/backend/tests: +16
---
Issue #292 (Conductor CLI page contract): the `/cli` page's fixed command
set is now backend-owned. The client-side mini console was replaced by a
registered backend capability route (`POST /v1/cli/exec`), a machine-readable
manifest (`GET /v1/cli/commands`), and a thin rendering client.

Suite delta — `packages/hive-conductor/backend/tests` grows by eleven
collected node IDs in the new `test_cli_contract.py`:

- the manifest/registry shape test and the help-is-rendered-from-the-manifest
  test pin the single-registry-three-consumers contract;
- one parametrized execution test over the five shipped commands (5 node IDs)
  proves each executes through its backend capability, sanitizes output, and
  lands in durable session history;
- the failure states — unsupported command (404 + warning audit + empty
  history), unauthenticated caller (401 on exec and manifest), handler
  timeout (504 + audit), and handler exception (503) — are each pinned so a
  client-side simulation or a silent failure cannot return;
- sanitization (ANSI/control chars, line and count caps, history-equals-
  rendered), session-history persistence across calls, unknown-session
  refusal, and a JSON round-trip guard;
- the machine-readable frontend/backend compatibility test, which reads the
  shipped `CLI.tsx` statically and fails if the page issues an unregistered
  command or reaches outside `/v1/cli/*`. It was proven against the
  regression it names: on the pre-change page it fails reporting the
  client-simulated `hctl` command set.

The pre-existing `test_cli_routes.py` session bookkeeping tests are
unchanged (4 node IDs), and the playwright e2e additions
(`frontend/e2e/cli-page.spec.ts`, the rewritten degraded-mode CLI case) live
outside the pytest inventory.
