from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepull-base-images.sh"


def _list_images(*dockerfiles: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--list", *(str(path) for path in dockerfiles)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_external_copy_source_is_pre_pulled(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.13 AS builder\n"
        "COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker\n"
        "COPY --from=builder /app /app\n"
        "COPY --from=0 /other /other\n",
        encoding="utf-8",
    )

    result = _list_images(dockerfile)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["docker:27-cli", "python:3.13"]


def test_shipped_docker_cli_source_is_covered_by_retry() -> None:
    result = _list_images(ROOT / "Dockerfile", ROOT / "packages/hive-conductor/Dockerfile")

    assert result.returncode == 0
    assert "docker:27-cli" in result.stdout.splitlines()
