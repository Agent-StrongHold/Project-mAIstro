---
inventory-delta:
  tests/: +15
---
# pr1516-engine-floor-install-check

`tests/test_install_engine_floor.py` (new file, 15 node IDs) guards the install.sh enforcement of the Docker Engine 25+ (API 1.44+) floor required by the embedded docker:29-cli binary (go1.26.8 rebuild; CVE-2025-68121). Following the established verbatim-lift pattern from `tests/test_secret_env.py::TestTheRealShellPath`, the tests sed-extract `version_ge` and `ensure_docker_engine_supported` out of `install.sh` and execute them under `set -euo pipefail` against a stub `docker` binary: Engine 24 (API 1.43) is refused with the upgrade pointer, Engine 25+ APIs pass, missing-CLI and unanswering-daemon cases skip, and the dotted-version comparator's ordering boundaries are pinned. Two structural tests assert the floor constant stays present at 1.44 and that `start_engine` wires the check after `ensure_compose_runtime` and before `record_docker_sock`.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +15 node IDs.
