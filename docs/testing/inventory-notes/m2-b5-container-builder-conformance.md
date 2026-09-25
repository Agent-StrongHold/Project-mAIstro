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

Repair-pass addendum (lane auto-80, no new tests): `Dockerfile.sandbox` now
provisions a passwd entry for the sandbox uid 65532 (`appuser`). This is
image-level defense in depth only — the enforced boundary remains the
container-create configuration
(`--user 65532:65532`, `--cap-drop=ALL`, `--read-only`, `--network=none`) which
works in any image via the numeric uid. Verified the image builds with the added
layer and that the full live lane still passes against it.

Re-validated live at head ab8c1713f (with the image change applied): image build
`docker build -f Dockerfile.sandbox` ok; `uv run pytest
packages/maistro-bootstrap/tests/test_container_sandbox.py -v` = 11 passed;
`uv run pytest packages/maistro-bootstrap/tests -q` = 245 passed, 1 skipped;
`uv run ruff check .` and `ruff format --check .` clean;
`scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests` ok.
