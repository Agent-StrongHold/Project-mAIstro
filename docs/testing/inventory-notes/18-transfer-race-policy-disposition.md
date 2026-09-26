---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-core/tests/sandbox: +4
---
# #18 — transfer race closure, MCP-tool policy honesty, seam ceiling (round 3)

Repair round addressing the 2026-09-26 NEEDS-REPAIR verdict at head
`fcb87d447`. Each fix targets a finding that was re-derived from reachable
production behavior, not taken on faith.

## 1. Bubblewrap host-side transfer: check-to-open symlink race closed (#1198)

`BubblewrapSandboxBackend.write_file`/`read_file` mapped the guest path with
`Path.resolve()` and opened it afterwards — a check-to-open window a symlink
swap wins. The backend now transfers through the substrate's
`read_beneath`/`write_beneath` (`maistro.sandbox.paths`), which walk directory
file descriptors with `O_NOFOLLOW`; the kernel refuses the symlink at `open`
time, so there is no window left to win. The dead `_resolve` helper is
deleted.

**The new race test detects the old implementation.** Mutation evidence
(scratch driver, not committed): the identical swap-loop race run against the
old resolve-then-open transfer escaped — reads returned the outside sentinel's
content and the sentinel was modified (host write). Against the new
implementation the same race never escapes; transfers either succeed on the
regular file or fail with ELOOP.

Tests (`tests/sandbox/test_host_transfer_race.py`, +4, no bubblewrap needed —
transfer is host-side): symlink at the final component refused for read and
write; symlink at an intermediate component refused (every walked fd is
`O_NOFOLLOW`); the deterministic held-open window against the production
backend seam (validate-then-swap-then-use now raises `OSError`); and the
active race (swapper thread vs. transfer loop, sentinel never modified, no
read ever returns sentinel content).

## 2. The MCP tool sandbox selects `UNTRUSTED_CODE`, not `TRUSTED_TOOL`

`tools/sandbox/server.py::create_sandbox` classified the sandbox MCP tool's
workload as `TRUSTED_TOOL` — the policy for first-party API calls (Jira, web
search, ADR-093 decision 3). But `sandbox_exec` runs *model-chosen shell*,
and ADR-093's context names the tool sandbox as a place untrusted,
model-generated code runs. The live review measured the consequence:
tier=container, network_mode=host — the host network namespace granted to
model-chosen commands (#77 violated) and the mode floors skipped (ADR-093
decision 6).

The seam now selects `UNTRUSTED_CODE`: VM tier, default-deny egress,
autonomous floor for the unstated mode. On every host shipped today (no
Tier-1/2 backend behind the protocol) the selector raises
`NoSuitableBackendError` and the tool refuses — the same honest disposition
already recorded for the evolve benchmark and RSI seams in
[18-sandbox-authority.md](18-sandbox-authority.md).

`TRUSTED_TOOL` itself is unchanged and remains correct for its documented
consumers (first-party tool calls; pinned by
`test_selector.py::test_container_satisfies_trusted_tool`): the finding was
the sandbox_exec mislabel, not the standard profile. The support matrix now
names the MCP tool sandbox as an `UNTRUSTED_CODE` consumer so the disposition
is written down where operators read.

Tests (`tests/tools/sandbox/test_server.py`, +2): the selected policy is
`UNTRUSTED_CODE` with a `DENY` egress grant, one authorized writable root and
no ambient env (#78); and `create_sandbox` refuses with
`NoSuitableBackendError` on a host with no registered backend.

## 3. The bootstrap data-plane seam gets a ceiling, not just a floor

`scripts/check-sandbox-authority.py` registered
`maistro_bootstrap/builders/container_sandbox.py` as an authorized seam with
posture floor pins (default-deny egress, cap-drop, no-new-privileges, uid
65532) but nothing stopped the seam from *widening*. The gate now also
enforces `AUTHORIZED_SEAM_CEILING`: `docker.sock`, `--privileged`,
`--network=host`, `--cap-add=ALL`, `--pid=host`, `--userns=host`, `--device`
must never appear in the file — any of them turns the data-plane tar seam into
a second backend again. Mutation-checked: planting `--privileged` fails the
gate with `authorized-seam-widened`; the clean file passes.

Full convergence of this seam onto the selector authority remains the recorded
owner decision (maistro-bootstrap deliberately does not depend on maistro-core,
and the bulk tar seed/sync cannot fit the bounded `SandboxProtocol.exec`
capture, #1197); what changed here is that the convergence CI now proves the
seam cannot silently become the thing it is exempted from being.

## 4. SAST: container backend B108 findings repaired

`backends/container.py:84` (`/tmp/maistro-workspace` default root) and `:109`
(the guest tmpfs mount point) reproduced the live PR's SAST failure exactly:
`uv run bandit -r packages/maistro-core/src packages/hive-conductor/backend
packages/maistro-server/src -ll --confidence-level=medium` exited 1 with two
MEDIUM/MEDIUM B108 findings. Both lines now carry `# nosec B108` with the
justification the rest of the tree uses for exactly this class
(`paths.py`, `detect.py`, `bubblewrap.py`): line 84 is the fixed root
`AUTHORIZED_HOST_ROOTS` already authorizes; line 109 is the mount point
*inside* the container, where `noexec,nosuid` is the hardening. `nosemggrep`
annotations for the semgrep tmp-directory rule ride on the same lines.
Re-run: bandit exits 0 with 0 findings at CI's exact invocation.

## Executed evidence at this head

- `uv run pytest packages/maistro-core/tests/sandbox
  packages/maistro-core/tests/tools/sandbox
  packages/maistro-core/tests/tools/test_sandbox_paths.py
  packages/maistro-core/tests/graph/durable_runs/test_attempt_executor.py -q`
  → 205 passed, 36 skipped (bwrap-userns skips, honestly keyed);
- evolve `test_swebench.py` + `test_e2e_sandbox_loop.py` → 18 passed;
  conductor sandbox gating/executor/injection/security → 59 passed;
- `uv run ruff check .` / `ruff format --check .` → clean;
- `uv run mypy --strict packages/maistro-core/src` → clean (640 files,
  after `uv sync --locked --all-extras` to match CI's env);
- `scripts/check-sandbox-authority.py` → ok, negative case proven live;
- vulture per-identity ledger → exit 0 (1411 reviewed → 1410 findings);
- bandit SAST invocation → exit 0, 0 findings.
