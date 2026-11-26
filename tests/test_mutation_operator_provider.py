"""Tests for the in-repo cosmic-ray operator provider (PR #1994).

The PR mutation gate fails closed when a changed critical line yields zero
mutants ("a configuration error, not a pass", pinned in
tests/test_mutation_diff_scope.py). Cosmic-ray's core provider has no string
mutator, so a line whose only runtime tokens are string literals — a pure
rename's return statement, exactly PR #1994's privilege.py diff — was
structurally un-passable. ``maistro/ReplaceStringWithEmpty`` closes that
operator gap by ADDING mutational power; these tests pin the operator's
surface and the wiring that puts it in every ``cosmic-ray init``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import parso
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "packages" / "maistro-core" / "src" / "maistro" / "mutation_operator_provider.py"
GATE_SCRIPT = ROOT / "scripts" / "mutation_pr_gate.py"


@pytest.fixture(scope="module")
def mod():
    """The real installed module — the same class object the entry point yields."""
    import maistro.mutation_operator_provider as module

    return module


@pytest.fixture(scope="module")
def gate():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("_mutation_pr_gate_fp", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ast_nodes(tree: Any):
    """cosmic_ray.ast.ast_nodes' walk: every node, leaves included."""
    import parso.tree

    yield tree
    if isinstance(tree, parso.tree.BaseNode):
        for child in tree.children:
            yield from _ast_nodes(child)


def _positions(mod, source: str) -> list[int]:
    """The line numbers the operator yields as mutation positions."""
    tree = parso.parse(source)
    operator = mod.ReplaceStringWithEmpty()
    return sorted(
        {start[0] for node in _ast_nodes(tree) for start, _end in operator.mutation_positions(node)}
    )


def _mutated_token(mod, source: str) -> str:
    """The mutated token for a module with exactly one targeted literal."""
    tree = parso.parse(source)
    operator = mod.ReplaceStringWithEmpty()
    node = next(
        node for node in _ast_nodes(tree) if any(True for _ in operator.mutation_positions(node))
    )
    return operator.mutate(node, 0).value


class TestEntryWiring:
    def test_the_provider_is_registered_under_the_maistro_namespace(self, mod):
        """The pin that keeps the operator real: stevedore must discover it,
        or the gate still fails closed on rename-only critical diffs."""
        from cosmic_ray.plugins import get_operator, operator_names

        assert "maistro/ReplaceStringWithEmpty" in sorted(operator_names())
        assert get_operator("maistro/ReplaceStringWithEmpty") is mod.ReplaceStringWithEmpty

    def test_the_provider_exposes_its_operators_like_the_core_provider(self, mod):
        provider = mod.MaistroMutationOperators()
        assert list(provider) == ["ReplaceStringWithEmpty"]
        assert provider["ReplaceStringWithEmpty"] is mod.ReplaceStringWithEmpty


class TestMutationSurface:
    def test_a_runtime_string_literal_is_mutated_to_the_empty_string(self, mod):
        assert _positions(mod, 'ROLE = "user"\n') == [1]
        assert _mutated_token(mod, 'ROLE = "user"\n') == '""'

    def test_a_single_quoted_literal_is_mutated(self, mod):
        assert _mutated_token(mod, "ROLE = 'user'\n") == '""'

    def test_a_prefixed_bytes_literal_is_mutated(self, mod):
        assert _positions(mod, 'MAGIC = b"hex"\n') == [1]

    def test_an_empty_literal_is_never_mutated(self, mod):
        """Mutating "" to "" is the no-op NumberReplacer refuses to emit."""
        assert _positions(mod, 'ROLE = ""\n') == []

    def test_module_class_and_function_docstrings_are_never_mutated(self, mod):
        source = (
            '"""Module doc."""\n'
            "\n"
            "class Widget:\n"
            '    """Class doc."""\n'
            "\n"
            "    def spin(self):\n"
            '        """Function doc."""\n'
            '        return "runtime"\n'
        )
        assert _positions(mod, source) == [8], "only the runtime return string is a mutation target"

    def test_an_assignment_on_the_first_line_is_not_a_docstring(self, mod):
        """The first line being a string is not what makes a docstring; being
        the first *bare* string statement is."""
        assert _positions(mod, 'NAME = "first"\n') == [1]

    def test_a_string_that_follows_a_real_docstring_still_mutates(self, mod):
        source = '"""Module doc."""\nNAME = "second"\n'
        assert _positions(mod, source) == [2]

    def test_fstring_literal_parts_are_not_mutated(self, mod):
        assert _positions(mod, 'GREETING = f"hello {NAME}!"\n') == []

    def test_a_plain_string_nested_inside_an_fstring_expression_is_not_mutated(self, mod):
        """Strings inside {...} replacement fields are runtime strings, but the
        f-string machinery is outside this operator's measured surface."""
        assert _positions(mod, "CHOICE = f\"{'a' if flag else 'b'}\"\n") == []

    def test_a_keyword_argument_string_is_mutated(self, mod):
        """The exact shape PR #1994's privilege.py diff left unpassable."""
        source = 'return _SubsystemCredential(role="user", public_key=self._user_key)\n'
        assert _positions(mod, source) == [1]
        assert _mutated_token(mod, source) == '""'


class TestFingerprintCoversTheOperatorSet:
    def test_a_changed_operator_set_changes_the_fingerprint(self, gate, monkeypatch):
        import cosmic_ray.plugins

        real = sorted(cosmic_ray.plugins.operator_names())
        monkeypatch.setattr(cosmic_ray.plugins, "operator_names", lambda: list(real))
        baseline = gate.tool_fingerprint()
        monkeypatch.setattr(
            cosmic_ray.plugins,
            "operator_names",
            lambda: [name for name in real if not name.startswith("maistro/")],
        )
        assert gate.tool_fingerprint() != baseline, (
            "a cached result from before an operator landed must not survive"
        )
