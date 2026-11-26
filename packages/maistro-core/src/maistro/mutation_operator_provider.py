"""In-repo cosmic-ray mutation operator provider (#330; dev toolchain only).

Why this exists
---------------
The PR mutation gate (``scripts/mutation_pr_gate.py``, #330) mutates exactly
the changed lines of changed mutation-critical files and fails closed when a
changed critical line yields zero mutants — "a configuration error, not a
pass", pinned in ``tests/test_mutation_diff_scope.py``. Cosmic-ray's core
provider covers numbers, booleans, binary/unary/comparison operators,
break/continue, decorators, and exceptions, but no string mutator. A pure
rename of an identity class (PR #1994: ``_SubsystemIdentity`` ->
``_SubsystemCredential``) therefore leaves its one executable diff line
(``return _SubsystemCredential(role="user", ...)``) without a single mutable
token: the gate is structurally un-passable for that diff, whatever the tests
do. This provider supplies the one standard mutator the core set lacks so the
line is scored instead of unreachable-by-construction.

What it registers
-----------------
``MaistroMutationOperators`` through the ``cosmic_ray.operator_providers``
stevedore entry-point group — the same surface cosmic-ray's own ``core``
provider uses — so every ``cosmic-ray init`` in this repository (PR gate and
nightly alike) enumerates string mutants alongside the core set. That
strictly ADDS mutational power: any verdict the gate could produce before
remains producible, and previously invisible lines now get scored against
their selected tests.

Loading contract
----------------
Instantiation needs the dev toolchain (``cosmic-ray`` pulls ``parso``); the
module is deliberately NOT exported from :mod:`maistro.testing` and nothing
in the runtime import graph references it — production installs never import
it. ``scripts/check-reachability.py`` roots it as an entry-point module (the
``maistro_registry.cli`` precedent), and the PR gate's tool fingerprint
includes the registered operator set so a result cached before an operator
landed can never be accepted for a session enumerating different mutants.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from cosmic_ray.operators.operator import Example, Operator
from parso.python.tree import String
from parso.tree import BaseNode, Node

#: A quoted literal's raw token: optional string prefix, quotes, inner text.
_LITERAL_TOKEN = re.compile(
    r"^(?P<prefix>[A-Za-z]*)(?P<quote>['\"])(?P<inner>.*)(?P=quote)$", re.DOTALL
)

#: Statement containers whose first string statement is a docstring.
_BODY_TYPES = frozenset({"file_input", "suite"})

#: Parso trivia nodes that never carry a mutation target.
_TRIVIA = frozenset({"newline", "indent", "dedent"})

#: Mutation position: ((start_line, start_col), (end_line, end_col)).
MutationPosition = tuple[tuple[int, int], tuple[int, int]]


def _literal_inner(raw: str) -> str | None:
    """The text inside a quoted literal token, or None for non-literals."""
    match = _LITERAL_TOKEN.match(raw)
    return match.group("inner") if match else None


def _in_fstring(node: BaseNode) -> bool:
    """True when the node sits inside an f-string's replacement or literal part.

    Parso models f-string internals with dedicated node types; mutating them
    is not part of this operator's measured surface.
    """
    parent: BaseNode | None = node.parent
    while parent is not None:
        if parent.type == "fstring":
            return True
        parent = parent.parent
    return False


def _is_docstring(node: BaseNode) -> bool:
    """True for a module/class/function docstring.

    A docstring is a bare string statement (the string is the whole statement,
    not an operand of an assignment or call) that is the first statement of its
    body. Its value is observable (``__doc__``) but no test suite is expected
    to kill mutants of its own documentation, so the operator refuses them
    rather than manufacturing unkillable survivors. Parso wraps an assigned
    string as ``simple_stmt > expr_stmt > string`` but collapses a bare one to
    ``simple_stmt > string``, so both shapes are recognized here.
    """
    statement = node.parent
    if statement is None:
        return False
    if statement.type == "expr_stmt":
        simple = statement.parent
    elif statement.type == "simple_stmt":
        simple = statement
    else:
        return False
    if simple is None or simple.type != "simple_stmt":
        return False
    body = simple.parent
    if body is None or body.type not in _BODY_TYPES:
        return False
    # A bare string statement: the string is the only non-trivia child of its
    # statement node (trailing newlines are parso trivia on simple_stmt).
    content = [child for child in statement.children if child.type not in _TRIVIA]
    return len(content) == 1 and content[0] is node


class ReplaceStringWithEmpty(Operator):
    """Replace a runtime string literal with the empty string.

    ``role="user"`` -> ``role=""`` is a behavior change any test exercising
    the value can kill; an empty literal is skipped because mutating it to
    the empty string changes nothing (the same no-op rule NumberReplacer
    applies to its offsets).
    """

    def mutation_positions(self, node: Node) -> Iterator[MutationPosition]:
        """Yield the position of every mutatable runtime string literal."""
        if not isinstance(node, String):
            return
        if _in_fstring(node) or _is_docstring(node):
            return
        if _literal_inner(node.value):
            yield (node.start_pos, node.end_pos)

    def mutate(self, node: Node, index: int) -> Node:
        """Replace the string literal at ``node`` with the empty string."""
        assert isinstance(node, String), "received a position that is not a string literal"
        assert index == 0, "received an occurrence this operator never produced"
        return String('""', node.start_pos)

    @classmethod
    def examples(cls) -> tuple[Example, ...]:
        """Before/after pairs cosmic-ray renders in its diff reports."""
        return (Example('x = "alive"', 'x = ""'),)


class MaistroMutationOperators:
    """The provider cosmic-ray instantiates from the entry point.

    Stevedore resolves the entry-point value, imports it, and CALLS it — the
    same contract ``core = cosmic_ray.operators.provider:OperatorProvider``
    uses, so this class doubles as its own factory.
    """

    def __iter__(self) -> Iterator[str]:
        """The registered operator names, ``provider/name`` prefixed by cosmic-ray."""
        return iter(_OPERATORS)

    def __getitem__(self, name: str) -> type[ReplaceStringWithEmpty]:
        """Resolve an operator class, failing fast on an incomplete contract."""
        operator_class = _OPERATORS[name]
        # Cosmic-ray calls this contract on every enumerated mutant and for
        # its diff reports; fail fast on a misregistered operator instead of
        # dying mid-session.
        for contract in (
            operator_class.mutation_positions,
            operator_class.mutate,
            operator_class.examples,
        ):
            assert callable(contract), f"{name} is missing part of the operator contract"
        return operator_class


_OPERATORS: dict[str, type[ReplaceStringWithEmpty]] = {
    "ReplaceStringWithEmpty": ReplaceStringWithEmpty,
}

# The entry-point surface: stevedore discovers these by string name in
# packages/maistro-core/pyproject.toml, invisible to a static scan.
__all__ = ["MaistroMutationOperators", "ReplaceStringWithEmpty"]
