"""The repository anchor: the merged reference extension runs green (#974).

The harness's statement of the manifest contract is validated against the
extension the repository actually ships — `extensions/reference-greeter` —
and then the full `tool` suite runs against it in-process. This is the test
that holds the harness's contract statement and the product's reference
extension together while the normative SDK package (M9-A1) is pending.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REFERENCE_EXTENSION = Path(__file__).resolve().parents[3] / "extensions" / "reference-greeter"

pytestmark = pytest.mark.skipif(
    not (REFERENCE_EXTENSION / "extension.json").is_file(),
    reason="reference extension not present in this checkout layout",
)


def test_reference_extension_validates_and_passes_the_tool_suite(
    tmp_path: Path,
) -> None:
    from maistro_ext_harness import RunRequest, load_manifest_file, run_conformance

    manifest = load_manifest_file(REFERENCE_EXTENSION / "extension.json")
    assert manifest.family == "tool"
    assert manifest.contract_major == 1

    report = run_conformance(
        RunRequest(subject=REFERENCE_EXTENSION, family="tool", with_reference=False)
    )
    data = report.to_dict()
    assert data["summary"]["failed"] == 0, [
        case for case in data["cases"] if case["status"] == "failed"
    ]
    ids = {case["case_id"] for case in data["cases"]}
    assert "tool/handler-invocation-succeeds" in ids
    assert "security/undeclared-authority-invisible" in ids
