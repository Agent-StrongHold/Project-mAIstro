---
inventory-delta:
  packages/maistro-bootstrap/tests: +5
---
# M2-B5 Container Builder Conformance

The live Docker-gated tests in `test_container_sandbox.py` now exercise the
same `ContainerBuilderSandbox` used by the Builder/RSI production path. They
cover the backend's real network namespace, non-root identity and capability
floor, host-seed credential denylist (including complete `.git` exclusion),
read-only rootfs with explicit workspace/tmpfs writes, process/device/socket
surfaces, memory/resource configuration, timeout kill, and context cleanup. The
credential seed case includes environment-specific dotenv files and
application-specific `secrets/` material, matching the previously observed
`.env.production` and `secrets/production-token.txt` leak paths.

The CI test job builds the small `Dockerfile.sandbox` image and runs this lane;
without Docker or the image, local runs skip the Docker-gated module rather than
claiming backend evidence.
