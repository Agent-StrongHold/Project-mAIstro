---
inventory-delta:
  packages/maistro-bootstrap/tests: +6
---
# M2-B5 Container Builder Conformance

The live Docker-gated tests in `test_container_sandbox.py` now exercise the
same `ContainerBuilderSandbox` used by the Builder/RSI production path. They
cover the backend's real network namespace, non-root identity and capability
floor, host-seed Git-index allowlist plus credential exclusions (including
complete `.git` exclusion), read-only rootfs with explicit workspace/tmpfs
writes, process/device/socket surfaces, memory/resource configuration, timeout
kill, and context cleanup. The credential seed case includes environment-specific
dotenv files, `.envrc`, application-specific `secrets/` material, and an
unrelated host-secret filename, matching the previously observed leak paths.
Docker proxy configuration is also blanked explicitly before candidate code
runs, so client-side proxy credentials cannot cross the environment boundary.

Re-validated live against the real Docker backend (issue #80 repair pass,
2026-08-31): `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py`
= 11 passed; `uv run pytest packages/maistro-bootstrap/tests` = 245 passed,
1 skipped. The core Tier-3 lane skips only where the host kernel refuses
bubblewrap namespaces; CI installs bwrap and relaxes
`kernel.apparmor_restrict_unprivileged_userns` before running it.

The CI test job builds the small `Dockerfile.sandbox` image and runs this lane;
without Docker or the image, local runs skip the Docker-gated module rather than
claiming backend evidence. The timeout case also creates a detached session, proving
that cleanup handles descendants which escape the command's process group.
