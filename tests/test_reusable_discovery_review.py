"""Regression cases from the independent review of #1609."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-required-checks.py"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("reviewed_discovery", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "WORKFLOW_DIR", workflows)
    return module


def _write(gate, name, text):
    path = gate.WORKFLOW_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


def _pair(gate, key="suffix", value='""', default=False):
    supplied = "" if default else f"    with:\n      {key}: {value}\n"
    caller = f"""name: Caller
on: pull_request
jobs:
  quality:
    name: Quality
    uses: ./.github/workflows/reusable.yml
{supplied}"""
    _write(gate, "caller.yml", caller)
    definition = f"        default: {value}\n" if default else ""
    expression = "${{ inputs." + key + " }}"
    callee = f"""name: Reusable
on:
  workflow_call:
    inputs:
      {key}:
        type: string
{definition}jobs:
  check:
    name: Test{expression}
"""
    _write(gate, "reusable.yml", callee)


@pytest.mark.parametrize("default", [False, True])
def test_empty_input_component_keeps_the_nonempty_resolved_name(gate, default):
    _pair(gate, default=default)
    assert gate.collect() == [("Caller", "Quality / Test", "every PR")]


@pytest.mark.parametrize("key", ["on", "off", "yes", "no", "ON", "Off", "Yes", "NO"])
def test_yaml_input_identifier_is_not_converted_to_boolean(gate, key):
    _pair(gate, key=key, value="value")
    assert gate.collect() == [("Caller", "Quality / Testvalue", "every PR")]


def test_distinct_yaml_identifiers_do_not_overwrite_one_another(gate):
    _pair(gate, key="on", value="first")
    caller = gate.WORKFLOW_DIR / "caller.yml"
    caller.write_text(caller.read_text() + "      yes: second\n")
    callee = gate.WORKFLOW_DIR / "reusable.yml"
    text = callee.read_text().replace("jobs:\n", "      yes:\n        type: string\njobs:\n")
    text = text.replace("Test${{ inputs.on }}", "${{ inputs.on }}-${{ inputs.yes }}")
    callee.write_text(text)
    assert gate.collect() == [("Caller", "Quality / first-second", "every PR")]


@pytest.mark.parametrize("direct", [False, True])
def test_duplicate_names_across_jobs_in_one_workflow_fail(gate, direct):
    _pair(gate, value="value")
    caller = gate.WORKFLOW_DIR / "caller.yml"
    if direct:
        extra = "  other:\n    name: Quality / Testvalue\n    runs-on: ubuntu-latest\n"
    else:
        extra = """  other:
    name: Quality
    uses: ./.github/workflows/reusable.yml
    with:
      suffix: value
"""
    caller.write_text(caller.read_text() + extra)
    with pytest.raises(gate.ContractError, match="emit the check name"):
        gate.collect()


def test_actions_loader_does_not_change_global_pyyaml_behavior(gate):
    before = yaml.safe_load("on: yes\n")
    _pair(gate, value="value")
    gate.collect()
    assert yaml.safe_load("on: yes\n") == before == {True: True}


def test_safe_loader_still_refuses_python_object_construction(gate):
    _pair(gate, value="value")
    _write(gate, "reusable.yml", "!!python/object/new:object []\n")
    with pytest.raises(gate.ContractError, match="cannot read reusable workflow"):
        gate.collect()


def test_true_false_remain_booleans_for_conditional_job_refusal(gate):
    _pair(gate, value="value")
    path = gate.WORKFLOW_DIR / "reusable.yml"
    path.write_text(path.read_text() + "    if: false\n")
    with pytest.raises(gate.ContractError, match="conditional"):
        gate.collect()


@pytest.mark.parametrize("required", ["", "        required: false\n"])
def test_omitted_optional_string_uses_implicit_empty_default(gate, required):
    _pair(gate, default=True)
    path = gate.WORKFLOW_DIR / "reusable.yml"
    path.write_text(path.read_text().replace('        default: ""\n', required))
    assert gate.collect() == [("Caller", "Quality / Test", "every PR")]


@pytest.mark.parametrize("prefix", ["", " "])
def test_implicit_empty_default_cannot_be_the_entire_check_name(gate, prefix):
    _pair(gate, default=True)
    path = gate.WORKFLOW_DIR / "reusable.yml"
    text = path.read_text().replace('        default: ""\n', "")
    text = text.replace(
        "name: Test${{ inputs.suffix }}", f'name: "{prefix}${{{{ inputs.suffix }}}}"'
    )
    path.write_text(text)
    with pytest.raises(gate.ContractError, match="unsupported check name"):
        gate.collect()


@pytest.mark.parametrize(
    "definition",
    [
        "        type: string\n        required: true\n",
        '        type: string\n        required: "false"\n',
        "        type: string\n        required: null\n",
        "        type: boolean\n",
        "        type: number\n",
        "        type: choice\n",
        "        description: missing type\n",
    ],
)
def test_implicit_string_default_is_not_guessed_for_other_declarations(gate, definition):
    _pair(gate, default=True)
    path = gate.WORKFLOW_DIR / "reusable.yml"
    text = path.read_text().replace('        type: string\n        default: ""\n', definition)
    path.write_text(text)
    with pytest.raises(gate.ContractError, match="unresolved input"):
        gate.collect()
