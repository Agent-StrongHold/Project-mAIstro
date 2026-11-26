"""#331: the Compose durability harness must resolve the Conductor image by service.

Regression this names: ``packages/hive-conductor/scripts/verify-compose-durability.sh``
derived its helper image with ``$COMPOSE config --images | head -1``. Once #331
added the ``conductor-layout-check`` one-shot (``image: alpine:3.20``) the
standalone file had two images, and ``docker compose config --images`` lists them
in Go map order -- measured locally at 5 alpine-first of 12 invocations. On the
alpine-first half, every ``docker run --entrypoint maistro "$IMAGE"`` in the
inventory/backup/restore half of the scenario died with::

    exec: "maistro": executable file not found in $PATH

so the acceptance scenario for "CI performs create, write, recreate, read,
backup, and restore" failed for a reason unrelated to state loss. The image is
now read from the container the script already proved healthy, which names the
Conductor service's image explicitly.

The stub ``docker`` stands in for a daemon (no Docker is exercised here); the
point is which image the harness selects, not what the daemon does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packages" / "hive-conductor" / "scripts" / "verify-compose-durability.sh"

CONDUCTOR_IMAGE = "hive-durability-331-hive-conductor"

#: Emits the same two images `config --images` emits for the standalone file,
#: with the one-shot's alpine FIRST -- the map-order case that broke the
#: harness. `inspect` reports the image of the Conductor container.
_STUB = f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"config --images"*) printf 'alpine:3.20\\n{CONDUCTOR_IMAGE}\\n' ;;
  *"ps -q hive-conductor"*) printf 'deadbeefcafe\\n' ;;
  *"inspect --format"*) printf '{CONDUCTOR_IMAGE}\\n' ;;
  *) echo "stub docker: unexpected argv: $*" >&2; exit 1 ;;
esac
"""


def _run_with_stub(tmp_path: Path, body: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(_STUB, encoding="utf-8")
    stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "COMPOSE": "docker",
        "HOME": str(tmp_path),
    }
    completed = subprocess.run(
        ["bash", "-c", body],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _image_assignment() -> str:
    """The script's own IMAGE= line, so this test tracks the real code path."""
    lines = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.startswith("IMAGE=")
    ]
    assert len(lines) == 1, f"expected exactly one IMAGE= line in {SCRIPT}, got {lines}"
    return lines[0]


def test_harness_selects_the_conductor_image_not_another_service(tmp_path: Path) -> None:
    resolved = _run_with_stub(tmp_path, f'{_image_assignment()}\nprintf "%s" "$IMAGE"')
    assert resolved == CONDUCTOR_IMAGE


def test_head_first_over_config_images_would_pick_the_one_shot(tmp_path: Path) -> None:
    """Shows the fixed code path differs from the regression it replaced.

    Under the same stub the old expression yields ``alpine:3.20`` -- an image
    with no ``maistro`` entrypoint -- which is exactly how the backup/restore
    half of the scenario failed.
    """
    naive = _run_with_stub(
        tmp_path, 'IMAGE="$($COMPOSE config --images | head -1)"\nprintf "%s" "$IMAGE"'
    )
    assert naive == "alpine:3.20"
    assert naive != CONDUCTOR_IMAGE


def test_harness_no_longer_lists_all_compose_images() -> None:
    """A re-introduced `config --images` re-opens the flake this test names.

    Only executable lines count: the comment above the assignment quotes the
    rejected expression on purpose, to explain why it was replaced.
    """
    code = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert "config --images" not in "\n".join(code)
