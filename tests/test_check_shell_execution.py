"""Tests for the shell-execution ledger gate (#305).

The gate's job is to make an undeclared `shell=True` impossible to add quietly,
so these are about the ways one could still slip past: a call the ledger does
not mention, an entry describing a call that no longer exists, and an entry that
names no caller. The last is the one that matters most — `reachable_from` going
stale is exactly how #305 happened.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-shell-execution.py"

_ENTRY = {
    "file": "packages/maistro-rsi/src/maistro_rsi/x.py",
    "symbol": "runner",
    "owner": "@someone",
    "reachable_from": "the CLI",
    "reason": "an operator typed it",
}


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_shell_execution", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bench(tmp_path: Path, gate, monkeypatch: pytest.MonkeyPatch):
    """Point the gate at a source tree and a ledger we control."""

    def _set(source: str, calls: list[dict]) -> None:
        governed = tmp_path / "packages" / "maistro-rsi" / "src" / "maistro_rsi"
        governed.mkdir(parents=True, exist_ok=True)
        (governed / "x.py").write_text(source, encoding="utf-8")
        ledger = tmp_path / "shell-execution.json"
        ledger.write_text(json.dumps({"calls": calls}), encoding="utf-8")
        monkeypatch.setattr(gate, "ROOT", tmp_path)
        monkeypatch.setattr(gate, "LEDGER", ledger)
        monkeypatch.setattr(gate, "GOVERNED", ("packages/maistro-rsi/src",))

    return _set


class TestItFindsTheCallsThatMatter:
    def test_a_shell_true_keyword_is_found_under_its_symbol(self, gate) -> None:
        source = "def runner():\n    subprocess.run(cmd, shell=True)\n"

        assert gate.shell_calls(source) == ["runner"]

    def test_a_nested_function_reports_the_class_it_sits_in(self, gate) -> None:
        """`LocalSandbox.exec` runs its subprocess inside an inner `_run` it
        hands to a thread. Reporting the innermost name alone would make the
        ledger entry ambiguous between classes."""
        source = (
            "class Box:\n"
            "    async def exec(self):\n"
            "        def _run():\n"
            "            subprocess.run(cmd, shell=True)\n"
        )

        assert gate.shell_calls(source) == ["Box._run"]

    def test_shell_false_is_not_a_finding(self, gate) -> None:
        source = "def runner():\n    subprocess.run(argv, shell=False)\n"

        assert gate.shell_calls(source) == []

    @pytest.mark.parametrize(
        "expression",
        ["ENABLE_SHELL", "not False", "bool(flag)", "cfg.shell", "True if x else False"],
    )
    def test_a_shell_value_the_gate_cannot_read_as_False_is_governed(
        self, gate, expression: str
    ) -> None:
        """Matching only a literal `True` left the hole open: `shell=ENABLE_SHELL`
        enables a shell at runtime and would have passed undeclared. Anything
        the gate cannot evaluate to False by reading it is governed."""
        source = f"def runner():\n    subprocess.run(cmd, shell={expression})\n"

        assert gate.shell_calls(source) == ["runner"]

    def test_no_shell_keyword_at_all_is_not_a_finding(self, gate) -> None:
        source = "def runner():\n    subprocess.run(argv)\n"

        assert gate.shell_calls(source) == []

    def test_a_test_module_is_not_governed(self, gate, tmp_path: Path) -> None:
        """A test that proves the CLI's shell path still works has to write
        `shell=True` to assert on it."""
        assert gate._is_test(Path("packages/maistro-rsi/tests/test_x.py"))
        assert gate._is_test(Path("packages/maistro-rsi/src/test_helper.py"))
        assert not gate._is_test(Path("packages/maistro-rsi/src/maistro_rsi/local_loop.py"))


class TestTheLedgerIsExactInBothDirections:
    def test_an_undeclared_call_fails(self, gate, bench) -> None:
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", [])

        failures = gate.audit()

        assert len(failures) == 1
        assert "not in shell-execution.json" in failures[0]

    def test_a_stale_entry_fails(self, gate, bench) -> None:
        """The direction people forget. An entry for a call that is gone is a
        standing approval for whoever next writes one in that file."""
        bench("def runner():\n    subprocess.run(argv)\n", [dict(_ENTRY)])

        failures = gate.audit()

        assert len(failures) == 1
        assert "no longer passes" in failures[0]

    def test_a_declared_call_passes(self, gate, bench) -> None:
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", [dict(_ENTRY)])

        assert gate.audit() == []

    @pytest.mark.parametrize("field", ["file", "symbol", "owner", "reachable_from", "reason"])
    def test_every_entry_names_who_reaches_it_and_why(self, gate, bench, field: str) -> None:
        entry = dict(_ENTRY)
        del entry[field]
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", [entry])

        assert any(field in message for message in gate.audit())

    def test_an_empty_reason_is_not_a_reason(self, gate, bench) -> None:
        """`""` passes a key check and answers nothing."""
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", [{**_ENTRY, "reason": ""}])

        assert any("reason" in message for message in gate.audit())

    def test_an_entry_that_is_not_an_object_fails(self, gate, bench) -> None:
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", ["it's fine"])

        assert any("not an object" in message for message in gate.audit())

    def test_an_unreadable_ledger_fails_rather_than_passing_empty(
        self, gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gate, "LEDGER", tmp_path / "missing.json")

        assert gate.audit()


class TestTheRepositorysOwnLedger:
    def test_it_agrees_with_the_tree(self, gate) -> None:
        assert gate.audit() == []

    def test_the_conductor_backend_runs_no_shell(self, gate) -> None:
        """The HTTP boundary. #305 was a route reaching a shell in another
        package; a shell added directly here would be the same defect with a
        shorter path."""
        conductor = [
            entry for entry in gate.discovered() if entry[0].startswith("packages/hive-conductor")
        ]

        assert conductor == []

    def test_main_passes_and_says_how_many(self, gate, capsys) -> None:
        assert gate.main() == 0
        assert "shell=True call(s) in the governed trees are declared" in capsys.readouterr().out

    def test_main_fails_and_names_the_problem(self, gate, bench, capsys) -> None:
        bench("def runner():\n    subprocess.run(cmd, shell=True)\n", [])

        assert gate.main() == 1
        assert "shell-execution.json" in capsys.readouterr().out
