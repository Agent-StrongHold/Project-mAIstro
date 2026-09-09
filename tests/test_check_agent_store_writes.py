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
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-agent-store-writes.py"

#: The gate's allowlist paths are fixed relative to the scanned root, so a
#: synthetic tree exercises them by recreating these exact locations.
_SERVICE_RELPATH = "packages/hive-conductor/backend/services/agent_materialization.py"
_SERVER_RELPATH = "packages/maistro-server/src/maistro_server/main.py"


@pytest.fixture(scope="module")
def gate():
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


def _details(gate, tmp_path: Path) -> list[str]:
    return [v.detail for v in gate.find_violations(tmp_path)]


ROGUE = 'import stores\n\n\ndef make(key: str) -> None:\n    stores.agents[key] = object()\n'


def test_flags_an_item_assignment_outside_the_service(gate, tmp_path):
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
def test_flags_mutating_calls_and_deletes_outside_the_service(gate, tmp_path, snippet):
    _write(
        tmp_path,
        "packages/demo/src/demo/rogue.py",
        "import stores\n\n\ndef go(key, value=None):\n    " + snippet + "\n",
    )
    details = _details(gate, tmp_path)
    assert details, snippet
    assert all("outside the service" in d for d in details)


def test_a_subscript_read_is_not_a_write(gate, tmp_path):
    _write(
        tmp_path,
        "packages/demo/src/demo/reader.py",
        "import stores\n\n\ndef read(key):\n    row = stores.agents.get(key)\n"
        "    other = stores.agents[key]\n    present = key in stores.agents\n"
        "    names = [a.name for a in stores.agents.values()]\n"
        "    return row, other, present, names\n",
    )
    assert _details(gate, tmp_path) == []


def test_the_service_may_mutate(gate, tmp_path):
    _write(tmp_path, _SERVICE_RELPATH, ROGUE)
    assert _details(gate, tmp_path) == []


def test_flags_a_container_agents_rebinding(gate, tmp_path):
    _write(
        tmp_path,
        "packages/demo/src/demo/bridge.py",
        "class Bridge:\n    def start(self, agents):\n"
        "        self._container.agents = agents\n",
    )
    details = _details(gate, tmp_path)
    assert any("rebinds" in d for d in details)


def test_in_place_mutation_is_not_a_rebinding(gate, tmp_path):
    _write(
        tmp_path,
        "packages/demo/src/demo/bridge.py",
        "class Bridge:\n    def start(self, agents):\n"
        "        self._container.agents.clear()\n"
        "        self._container.agents.update(agents)\n",
    )
    assert _details(gate, tmp_path) == []


def test_the_maistro_server_exception_is_documented_and_scoped(gate, tmp_path):
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


def test_the_definition_module_holds_only_the_demo_seed(gate, tmp_path):
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


def test_importing_the_store_by_name_is_flagged(gate, tmp_path):
    _write(
        tmp_path,
        "packages/demo/src/demo/smuggler.py",
        "from stores import agents\n\n\ndef go(key):\n    return agents.get(key)\n",
    )
    details = _details(gate, tmp_path)
    assert any("imports the agents store by name" in d for d in details)


def test_this_tree_is_clean(gate):
    """The integration property: the real script passes on the tree as it
    stands -- stores.agents is written only by the materialization service,
    and container.agents is mutated in place, never rebound."""
    assert gate.find_violations(gate.ROOT) == []


def test_the_script_runs_as_a_gate_on_this_tree():
    """And as CI runs it: exit 0 with the OK banner."""
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert "Agent store write path OK" in done.stdout
