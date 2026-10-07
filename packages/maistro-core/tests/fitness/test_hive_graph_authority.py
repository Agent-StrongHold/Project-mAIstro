"""Shipped Hive Graph entrypoints cannot regress to a private lifecycle (#1113)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SERVICES = Path(__file__).resolve().parents[3] / "hive-conductor" / "backend" / "services"


@pytest.mark.parametrize(
    "module,function,store",
    [
        ("dag_agents", "run_registered_dag", "run_store"),
        ("canonical_dag_runner", "execute_dag", "canonical_run_store"),
    ],
)
def test_new_graph_work_requires_unconditional_canonical_admission(module, function, store):
    source = (_SERVICES / f"{module}.py").read_text()
    tree = ast.parse(source)
    entry = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function
    )
    # Guard and create are top-level statements, never an optional `if run_store` arm.
    guarded = [
        node
        for node in entry.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "require_graph_execution_spine"
    ]
    admissions = [
        node
        for node in entry.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Attribute)
        and node.value.value.func.attr == "create_run"
    ]
    assert len(guarded) == len(admissions) == 1
    assert guarded[0].lineno < admissions[0].lineno
    calls = [
        node
        for node in ast.walk(entry)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_durable_graph"
    ]
    assert len(calls) == 1
    kwargs = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
    assert kwargs["run_store"] == store
    assert kwargs["run_id"] == "admitted_run_id"
    assert kwargs["store"] == "container.graph_run_store"
    assert "_fallback_run_store" not in source
    assert "InMemoryDurableRunStore" not in source
    assert "hive-standalone-compat" not in source
