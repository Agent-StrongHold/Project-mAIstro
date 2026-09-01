from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-minio-evidence-owner.py"
spec = importlib.util.spec_from_file_location("check_minio_evidence_owner", SCRIPT)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


QUALITY = """jobs:
  coverage-archive:
    name: coverage (MinIO)
    steps:
      - name: Start MinIO
        run: minio/minio:latest server /data
      - name: Archive conformance against MinIO (under coverage)
        env:
          MAISTRO_REQUIRE_S3_LEGS: \"1\"
        run: |
          uv run coverage run --branch --source=packages/maistro-core/src/maistro \\
            -m pytest packages/maistro-core/tests/archive -v --tb=short
"""

CI = """jobs:
  object-storage:
    name: object storage (MinIO)
    steps:
      - uses: actions/checkout@v4
      - name: Canonical MinIO evidence ownership
        run: python3 scripts/check-minio-evidence-owner.py
"""


def test_minio_evidence_owner_fails_closed_on_duplicate_or_weakened_proof(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "quality.yml").write_text(QUALITY, encoding="utf-8")
    (workflows / "ci.yml").write_text(CI, encoding="utf-8")
    protection = tmp_path / ".github" / "branch-protection.json"
    protection.write_text(
        json.dumps({"required": ["coverage (MinIO)", "object storage (MinIO)"]}),
        encoding="utf-8",
    )

    assert checker.validate(tmp_path) == []

    (workflows / "ci.yml").write_text(
        CI + "\n  duplicate:\n    run: uv run pytest packages/maistro-core/tests/archive -v\n",
        encoding="utf-8",
    )
    assert any("exactly one workflow execution" in error for error in checker.validate(tmp_path))

    (workflows / "ci.yml").write_text(CI, encoding="utf-8")
    (workflows / "quality.yml").write_text(
        QUALITY.replace('          MAISTRO_REQUIRE_S3_LEGS: \"1\"\n', ""),
        encoding="utf-8",
    )
    assert any("skipped S3 legs fatal" in error for error in checker.validate(tmp_path))

    (workflows / "quality.yml").write_text(QUALITY, encoding="utf-8")
    protection.write_text(
        json.dumps({"required": ["object storage (MinIO)"]}),
        encoding="utf-8",
    )
    assert any("coverage (MinIO)" in error for error in checker.validate(tmp_path))
