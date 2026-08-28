"""Contract tests for the trusted gates-ran publisher."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts" / "check-gates-ran.py"
WORKFLOW = ROOT / ".github" / "workflows" / "gates-ran.yml"


def _gate_module():
    spec = importlib.util.spec_from_file_location("gates_ran_scope_contract", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_includes_base_coupled_release_checks():
    gate = _gate_module()
    names = gate.required_check_names(base_branch="main")
    assert [name for name in names if name.startswith("Analyze (")]
    assert "Container scan + SBOM + cosign" in names


def test_develop_excludes_main_only_release_checks():
    gate = _gate_module()
    names = gate.required_check_names(base_branch="develop")
    assert not [name for name in names if name.startswith("Analyze (")]
    assert "Container scan + SBOM + cosign" not in names


def test_publisher_has_only_the_write_permission_it_needs():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert doc["permissions"] == {"checks": "read", "contents": "read", "statuses": "write"}
    assert doc["jobs"]["publish-gates-ran"]["name"] == "gates-ran-publisher"


def test_publisher_targets_the_pr_head_from_trusted_workflow_run_code():
    text = WORKFLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    triggers = doc.get(True) or doc.get("on")

    assert "workflow_run" in triggers
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert "createCommitStatus" in text
    assert "context: 'gates-ran'" in text
    assert "github.event.repository.default_branch" in text
    assert "github.event.workflow_run.head_sha" in text
