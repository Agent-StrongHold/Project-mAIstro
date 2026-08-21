#!/usr/bin/env bash
set -euo pipefail

# Install only the non-security quality scanners used by scripts/run-quality-scans.sh.
# This intentionally avoids requirements-dev-tools.txt because that file also
# includes heavier security tools with conflicting transitive pins.
uv pip install "radon>=6.0" "vulture>=2.11"
