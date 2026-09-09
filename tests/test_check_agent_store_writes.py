"""Tests for the agent-store write-path gate.

The script is a CI gate, so the property that matters is that it *fails* on a
`stores.agents` mutation (or a `container.agents` rebinding) outside the one
permitted service. A gate that stays quiet on the defect it names is worse
than no gate. Synthetic trees, the same way `tests/test_check_wiring_reads.py`
tests its script -- plus one integration run of the real script over this
tree, which is what CI executes.
"""

from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-agent-store-writes.py"

#: The gate's allowlist paths are fixed relative to the scanned root, so a
#: synthetic tree exercises them by recreating these exact locations.
_SERVICE_RELPATH = "packages/hive-conductor/backend/services/agent_materialization.py"
_SERVER_RELPATH = "packages/maistro-server/src/maistro_server/main.py"


@pytest.fixture(scope="module")
def gate() -> Any:
    spec = importlib.util.spec_from_file_location("check_agent_store_writes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, relpath: str, source: str) -> None:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _details(gate: Any, tmp_path: Path) -> list[str]:
    return [v.detail for v in gate.find_violations(tmp_path)]


ROGUE = "import stores\n\n\ndef make(key: str) -> None:\n    stores.agents[key] = object()\n"


def test_flags_an_item_assignment_outside_the_service(gate: Any, tmp_path: Path) -> None:
    _write(tmp_path, "packages/demo/src/demo/rogue.py", ROGUE)
    assert any("item-assigns stores.agents" in d for d in _details(gate, tmp_path))


@pytest.mark.parametrize(
    "snippet",
    [
        "stores.agents.pop(key)",
        "stores.agents.pop(key, None)",
        "stores.agents.update({})",
        "stores.agents.clear()",
        "stores.agents.setdefault(key, value)",
        "del stores.agents[key]",
    ],
)
def test_flags_mutating_calls_and_deletes_outside_the_service(
    gate: Any, tmp_path: Path, snippet: str
) -> None:
    _write(
        tmp_path,
        "packages/demo/src/demo/rogue.py",
        "import stores\n\n\ndef go(key, value=None):\n    " + snippet + "\n",
    )
    details = _details(gate, tmp_path)
    assert details, snippet
    assert all("outside the service" in d for d in details)


def test_a_subscript_read_is_not_a_write(gate: Any, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/demo/src/demo/reader.py",
        "import stores\n\n\ndef read(key):\n    row = stores.agents.get(key)\n"
        "    other = stores.agents[key]\n    present = key in stores.agents\n"
        "    names = [a.name for a in stores.agents.values()]\n"
        "    return row, other, present, names\n",
    )
    assert _details(gate, tmp_path) == []


def test_the_service_may_mutate(gate: Any, tmp_path: Path) -> None:
    _write(tmp_path, _SERVICE_RELPATH, ROGUE)
    assert _details(gate, tmp_path) == []


def test_flags_a_container_agents_rebinding(gate: Any, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/demo/src/demo/bridge.py",
        "class Bridge:\n    def start(self, agents):\n        self._container.agents = agents\n",
    )
    details = _details(gate, tmp_path)
    assert any("rebinds" in d for d in details)


def test_in_place_mutation_is_not_a_rebinding(gate: Any, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/demo/src/demo/bridge.py",
        "class Bridge:\n    def start(self, agents):\n"
        "        self._container.agents.clear()\n"
        "        self._container.agents.update(agents)\n",
    )
    assert _details(gate, tmp_path) == []


def test_the_maistro_server_exception_is_documented_and_scoped(gate: Any, tmp_path: Path) -> None:
    source = (
        "def _build_container():\n"
        "    ...\n"
        "    container.agents = {CONDUCTOR_AGENT_NAME: ConductorAgent()}\n"
    )
    # At the documented exception path: silent.
    _write(tmp_path, _SERVER_RELPATH, source)
    assert _details(gate, tmp_path) == []
    # The same code anywhere else: flagged.
    _write(tmp_path, "packages/demo/src/demo/other.py", source)
    assert any("rebinds" in d for d in _details(gate, tmp_path))


def test_the_definition_module_holds_only_the_demo_seed(gate: Any, tmp_path: Path) -> None:
    stores_src = (
        "from services.model_store import ModelStore\n\n"
        'agents: ModelStore = ModelStore("agents", object)\n\n\n'
        "def _seed_agents() -> None:\n"
        '    agents["agent-1"] = object()\n\n\n'
        "def rogue() -> None:\n"
        '    agents["rogue"] = object()\n'
    )
    _write(tmp_path, "packages/hive-conductor/backend/stores.py", stores_src)
    details = _details(gate, tmp_path)
    assert len(details) == 1
    assert "non-seed site" in details[0]


def test_importing_the_store_by_name_is_flagged(gate: Any, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/demo/src/demo/smuggler.py",
        "from stores import agents\n\n\ndef go(key):\n    return agents.get(key)\n",
    )
    details = _details(gate, tmp_path)
    assert any("imports the agents store by name" in d for d in details)


def test_this_tree_is_clean(gate: Any) -> None:
    """The integration property: the real script passes on the tree as it
    stands -- stores.agents is written only by the materialization service,
    and container.agents is mutated in place, never rebound."""
    assert gate.find_violations(gate.ROOT) == []


def test_the_script_runs_as_a_gate_on_this_tree() -> None:
    """And as CI runs it: exit 0 with the OK banner."""
    done = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "Agent store write path OK" in done.stdout


# --------------------------------------------------------------------------- #
# The main() entry point itself
#
# Everything above drives find_violations, which is the gate's half that
# finds. main() is the half that decides: a violations run must render the
# sites and exit 1, a clean run must say so and exit 0 -- and an unparseable
# production file must degrade to "no findings from this file", not a crash.
# --------------------------------------------------------------------------- #


def test_main_exits_0_with_the_ok_banner_over_this_tree(
    gate: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The in-process twin of the subprocess gate run CI performs."""
    assert gate.main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert (
        "Agent store write path OK: stores.agents is mutated only by "
        "services/agent_materialization.py."
    ) in captured.out


def test_main_renders_violations_and_exits_1(
    gate: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A violating tree gets the FAIL banner, every site rendered file:line,
    the routing guidance, and an exit code a CI step can gate on."""
    _write(tmp_path, "packages/demo/src/demo/rogue.py", ROGUE)

    assert gate.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (f"FAIL: 1 agent-roster write(s) outside {_SERVICE_RELPATH}:") in captured.err
    assert (
        "  packages/demo/src/demo/rogue.py:5 item-assigns stores.agents outside the service"
    ) in captured.err
    assert "`stores.agents` has exactly one writer" in captured.err


def test_an_unparseable_production_file_degrades_to_no_findings(
    gate: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A production file that does not parse is tolerated -- the gate reports
    the violations it can see rather than crashing the run."""
    _write(tmp_path, "packages/demo/src/demo/broken.py", "def broken(:\n")

    assert gate.main(["--root", str(tmp_path)]) == 0
    assert "Agent store write path OK" in capsys.readouterr().out


def test_a_violation_outside_the_scan_root_renders_its_absolute_path(
    gate: Any, tmp_path: Path
) -> None:
    """`_file_violations` scores any file it is handed, even one outside the
    scanned root; `_relative` then falls back to the absolute path so the
    rendered site still names a real file instead of raising."""
    scan_root = tmp_path / "scan-root"
    scan_root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    rogue = outside / "rogue.py"
    rogue.write_text(ROGUE, encoding="utf-8")

    violations = gate._file_violations(rogue, scan_root)

    assert len(violations) == 1
    assert violations[0].path == str(rogue)
    assert violations[0].render() == (f"  {rogue}:5 item-assigns stores.agents outside the service")


def test_a_subscript_write_that_is_not_an_assignment_or_delete_is_not_scored(
    gate: Any, tmp_path: Path
) -> None:
    """Only Assign/AugAssign/Delete are writes. A Store-context subscript the
    grammar allows as a loop target is neither, so the gate stays quiet about
    it -- while a real item-assign in the same file is still flagged, proving
    the file was parsed and the silence is a decision, not a blind spot."""
    _write(
        tmp_path,
        "packages/demo/src/demo/for_target.py",
        "import stores\n"
        "\n"
        "\n"
        "def go(key, value):\n"
        "    for stores.agents[key] in []:\n"
        "        pass\n"
        "    stores.agents[key] = value\n",
    )

    violations = gate.find_violations(tmp_path)

    assert [(v.path, v.line, v.detail) for v in violations] == [
        (
            "packages/demo/src/demo/for_target.py",
            7,
            "item-assigns stores.agents outside the service",
        )
    ]


def test_the_console_entry_point_runs_the_gate_and_exits_0_on_a_clean_root(
    gate: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`python scripts/check-agent-store-writes.py` executes under the
    `__main__` guard: argv is the CLI's, and the SystemExit carries main()'s
    verdict."""
    monkeypatch.setattr(sys, "argv", ["check-agent-store-writes.py", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert excinfo.value.code == 0
    assert "Agent store write path OK" in capsys.readouterr().out
