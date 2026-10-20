"""Contract versioning — acceptance criterion 5 of #949.

"contract version is queryable and independently versioned from the MAIstro
application version"

The independence half is proven structurally: the contract version is a
string literal in contract.py, and that module references neither the
package ``__version__`` nor any metadata lookup it could be derived from.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import maistro_ext_sdk
from maistro_ext_sdk import contract as contract_module
from maistro_ext_sdk.contract import (
    EXTENSION_CONTRACT_VERSION,
    ContractVersion,
    contract_version,
    parse_contract_version,
)
from maistro_ext_sdk.ranges import VersionRange


class TestQueryable:
    def test_contract_version_is_queryable(self) -> None:
        assert contract_version() == EXTENSION_CONTRACT_VERSION

    def test_public_reexport_is_queryable_without_knowing_the_module(self) -> None:
        assert maistro_ext_sdk.contract_version() == contract_version()

    def test_published_version_is_semver_shaped(self) -> None:
        parse_contract_version(contract_version())  # must not raise
        assert re.fullmatch(r"\d+\.\d+\.\d+", contract_version())

    def test_published_major_is_supported_by_this_sdk(self) -> None:
        assert parse_contract_version(contract_version()).supported

    def test_parse_rejects_malformed_versions_explicitly(self) -> None:
        for bad in ("1", "1.0", "one.two.three", "1.0.0.0", "-1.0.0"):
            try:
                parse_contract_version(bad)
            except ValueError as exc:
                assert bad in str(exc)
            else:  # pragma: no cover - guard for the loop itself
                raise AssertionError(f"{bad!r} parsed but must not")


class TestIndependenceFromApplicationVersion:
    def test_contract_version_is_a_literal_not_a_derivation(self) -> None:
        """AST over contract.py: EXTENSION_CONTRACT_VERSION is assigned a
        single string constant, and the module's *code* never references the
        package ``__version__`` or imports anything that could re-derive it
        (importlib/metadata, file reads). Docstring mentions are prose, not
        derivation, so the check is on the tree, not the text."""
        source_path = Path(contract_module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        assigned: list[str] = []
        names_referenced: set[str] = set()
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EXTENSION_CONTRACT_VERSION"
                for t in node.targets
            ):
                assert isinstance(node.value, ast.Constant), (
                    f"EXTENSION_CONTRACT_VERSION must be a literal, not {ast.dump(node.value)}"
                )
                assigned.append(node.value.value)
            elif isinstance(node, ast.Name):
                names_referenced.add(node.id)
            elif isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        assert assigned == [contract_version()]
        assert "__version__" not in names_referenced, (
            "contract.py reads the package __version__; the contract version "
            "must not be derived from the application version"
        )
        derivation_imports = imported_roots & {"importlib", "tomllib", "pathlib"}
        assert not derivation_imports, (
            f"contract.py imports {sorted(derivation_imports)}; nothing that can "
            f"re-derive a version belongs in the contract module"
        )

    def test_contract_version_semantics_differ_from_package_version_semantics(
        self,
    ) -> None:
        """They are different axes even when the strings collide: the package
        version moves in lockstep with releases (ADR-073126-c4e1); the
        contract version moves only when the schema breaks. Neither may be
        computed from the other."""
        contract = contract_version()
        package = maistro_ext_sdk.__version__
        # The contract version is strict semver and queryable as such...
        assert re.fullmatch(r"\d+\.\d+\.\d+", contract)
        # ...while the package version may carry the -dev lockstep fallback.
        assert package.split("-")[0].count(".") == 2
        # The SDK's own docstring documents the two-axis split.
        assert maistro_ext_sdk.__doc__ is not None
        assert "independently" in maistro_ext_sdk.__doc__


class TestRangeSemantics:
    """The capping convention ADR-073126-c4e1 uses everywhere: >=X,<X+1."""

    def test_standard_capping_range_contains_current_contract(self) -> None:
        rng = VersionRange.parse(">=1.0.0,<2.0.0")
        assert rng.satisfied_by(parse_contract_version(contract_version()))

    def test_range_boundaries(self) -> None:
        rng = VersionRange(">=1.0.0,<2.0.0")
        assert rng.satisfied_by(ContractVersion(1, 0, 0))
        assert rng.satisfied_by(ContractVersion(1, 9, 9))
        assert not rng.satisfied_by(ContractVersion(2, 0, 0))
        assert not rng.satisfied_by(ContractVersion(0, 9, 0))

    def test_inclusive_and_equality_specifiers(self) -> None:
        assert VersionRange("<=1.0.0").satisfied_by(ContractVersion(1, 0, 0))
        assert not VersionRange("<1.0.0").satisfied_by(ContractVersion(1, 0, 0))
        assert VersionRange("==1.2.3").satisfied_by(ContractVersion(1, 2, 3))
        assert not VersionRange("==1.2.3").satisfied_by(ContractVersion(1, 2, 4))
        assert VersionRange(">0.9.0").satisfied_by(ContractVersion(1, 0, 0))

    def test_multi_specifier_range_requires_all(self) -> None:
        assert not VersionRange(">=1.0.0,==1.5.0").satisfied_by(ContractVersion(1, 9, 0))
        assert VersionRange(">=1.0.0,==1.5.0").satisfied_by(ContractVersion(1, 5, 0))

    def test_strictly_greater_specifier(self) -> None:
        rng = VersionRange(">1.0.0")
        assert not rng.satisfied_by(ContractVersion(1, 0, 0))
        assert rng.satisfied_by(ContractVersion(1, 0, 1))

    def test_inclusive_upper_bound_specifier(self) -> None:
        rng = VersionRange("<=2.0.0")
        assert rng.satisfied_by(ContractVersion(2, 0, 0))
        assert not rng.satisfied_by(ContractVersion(2, 0, 1))

    def test_range_comparison_and_round_trip(self) -> None:
        """Ranges compare by their parsed specifiers (not their spelling) and
        carry the original text for error messages."""
        a = VersionRange(">=1.0.0, <2.0.0")
        b = VersionRange(">=1.0.0,<2.0.0")
        assert a == b
        assert hash(a) == hash(b)
        assert a != ">=1.0.0,<2.0.0"
        assert str(a) == ">=1.0.0, <2.0.0"

    def test_parse_classmethod_and_module_function_agree(self) -> None:
        from maistro_ext_sdk.ranges import parse_version_range

        assert parse_version_range(">=1.0.0") == VersionRange.parse(">=1.0.0")
        assert parse_version_range(">=1.0.0") == VersionRange(">=1.0.0")

    def test_unsupported_specifier_fails_explicitly(self) -> None:
        for bad in ("~=1.0", ">= 1.*", "1.0.0", "latest", ">=1.0.0,,<2.0.0", ""):
            try:
                VersionRange(bad)
            except ValueError:
                continue
            raise AssertionError(f"{bad!r} parsed but must fail explicitly")
