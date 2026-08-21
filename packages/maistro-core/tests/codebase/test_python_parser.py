"""Behavioral tests for the AST-based syntactic parser."""

from __future__ import annotations

from maistro.codebase.python_parser import parse_python_module


def test_parses_plain_import() -> None:
    mod = parse_python_module("import os\n", module_path="m", file_path="m.py")
    assert mod.imports == (mod.imports[0],)
    imp = mod.imports[0]
    assert imp.module == "os"
    assert imp.names == ()
    assert imp.is_relative is False
    assert imp.line_number == 1


def test_parses_from_import_with_multiple_names() -> None:
    mod = parse_python_module("from a.b import c, d\n", module_path="m", file_path="m.py")
    assert len(mod.imports) == 1
    imp = mod.imports[0]
    assert imp.module == "a.b"
    assert imp.names == ("c", "d")
    assert imp.is_relative is False


def test_parses_relative_import() -> None:
    mod = parse_python_module("from .sibling import Thing\n", module_path="m", file_path="m.py")
    imp = mod.imports[0]
    assert imp.module == "sibling"
    assert imp.names == ("Thing",)
    assert imp.is_relative is True


def test_parses_bare_dot_relative_import() -> None:
    mod = parse_python_module("from . import Thing\n", module_path="m", file_path="m.py")
    imp = mod.imports[0]
    assert imp.module == ""
    assert imp.names == ("Thing",)
    assert imp.is_relative is True


def test_captures_imports_nested_under_type_checking() -> None:
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from a.b import C\n"
    mod = parse_python_module(source, module_path="m", file_path="m.py")
    modules = [imp.module for imp in mod.imports]
    assert "a.b" in modules


def test_bare_protocol_base_marks_class_as_protocol() -> None:
    mod = parse_python_module(
        "from typing import Protocol\nclass Store(Protocol):\n    pass\n",
        module_path="m",
        file_path="m.py",
    )
    cls = next(c for c in mod.classes if c.name == "Store")
    assert cls.bases == ("Protocol",)
    assert cls.is_protocol is True


def test_dotted_typing_protocol_base_marks_class_as_protocol() -> None:
    mod = parse_python_module(
        "import typing\nclass Store(typing.Protocol):\n    pass\n",
        module_path="m",
        file_path="m.py",
    )
    cls = next(c for c in mod.classes if c.name == "Store")
    assert cls.bases == ("typing.Protocol",)
    assert cls.is_protocol is True


def test_non_protocol_dotted_base_is_not_protocol() -> None:
    mod = parse_python_module(
        "import maistro.protocols.tools\nclass Impl(maistro.protocols.tools.ToolExecutor):\n    pass\n",
        module_path="m",
        file_path="m.py",
    )
    cls = next(c for c in mod.classes if c.name == "Impl")
    assert cls.bases == ("maistro.protocols.tools.ToolExecutor",)
    assert cls.is_protocol is False


def test_syntax_error_yields_parse_error_without_raising() -> None:
    mod = parse_python_module("def broken(:\n", module_path="m", file_path="m.py")
    assert mod.parse_error != ""
    assert mod.imports == ()
    assert mod.classes == ()
