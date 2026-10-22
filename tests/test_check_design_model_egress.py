"""Self-check for the design model-egress gate (#987, acceptance criterion 6).

The gate is what CI runs to keep design explore/judge on the governed
Invocation path: no provider SDK import under ``packages/maistro-design``, no
raw model-completion HTTP there, and no Design Studio page talking to a model
host. Two reasons it needs its own module here rather than only living in the
workflow:

- a gate nobody exercises is a gate that can rot — the detectors have to
  still catch the shapes they claim to catch;
- the root suite is the producer that measures ``scripts/``, so a gate file
  that no root-suite test executes is a file the coverage gate reports as
  "under a measured root but absent from the coverage report".

Every case below drives the shipped script by path, on the shipped tree and on
planted violations.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-design-model-egress.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_design_model_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_design_package(gate, tmp_path: Path, monkeypatch, source: str) -> Path:
    """A fake design package, rooted so the gate can name the breach."""

    design_src = tmp_path / "maestro_design"
    design_src.mkdir(parents=True, exist_ok=True)
    (design_src / "rogue.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "DESIGN_SRC", design_src)
    return design_src


def _fake_frontend_pages(
    gate, tmp_path: Path, monkeypatch, overrides: dict[str, str] | None = None
) -> Path:
    """A fake Design Studio page set, rooted so the gate can name the breach."""

    pages = tmp_path / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for name in (
        "DesignStudio.tsx",
        "FixedPageEditor.tsx",
        "FixedPageArtifactEditor.tsx",
        "DeckBuilder.tsx",
    ):
        (pages / name).write_text((overrides or {}).get(name, "export const Page = () => null;\n"))
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "FRONTEND_PAGES", pages)
    return pages


# --- the shipped tree --------------------------------------------------------


def test_the_shipped_tree_passes_the_gate(gate, capsys: pytest.CaptureFixture[str]) -> None:
    """The gate is green on the tree it ships with.

    A gate that fails on its own repository is a gate nobody can act on, and
    the failure would arrive as an unrelated CI break.
    """

    assert gate.main() == 0
    assert "design model egress: ok" in capsys.readouterr().out


def test_the_gate_checks_both_the_package_and_the_pages(gate) -> None:
    """The scope is the design package plus the Design Studio pages."""

    assert gate.DESIGN_SRC == ROOT / "packages" / "maistro-design" / "src" / "maistro_design"
    assert "DeckBuilder.tsx" in gate.DESIGN_STUDIO_PAGES
    assert "DesignStudio.tsx" in gate.DESIGN_STUDIO_PAGES


# --- python sources ----------------------------------------------------------


def test_a_provider_sdk_import_fails_the_gate(gate, tmp_path: Path, monkeypatch) -> None:
    """An ``openai`` import in the design package is a competing egress."""

    _fake_design_package(
        gate, tmp_path, monkeypatch, "import openai\n\nclient = openai.AsyncOpenAI()\n"
    )

    failures = gate._check_python_sources()

    assert any("provider SDK import 'openai'" in failure for failure in failures)


def test_a_from_import_of_a_provider_sdk_fails_the_gate(gate, tmp_path: Path, monkeypatch) -> None:
    """``from litellm import completion`` is the same escape in another shape."""

    _fake_design_package(gate, tmp_path, monkeypatch, "from litellm import completion\n")

    failures = gate._check_python_sources()

    assert any("provider SDK import 'litellm'" in failure for failure in failures)


def test_a_raw_model_completion_http_call_fails_the_gate(gate, tmp_path: Path, monkeypatch) -> None:
    """A design module that posts to a completions endpoint is a private LLM."""

    _fake_design_package(
        gate,
        tmp_path,
        monkeypatch,
        "import httpx\n\n"
        "async def ask(client: httpx.AsyncClient) -> None:\n"
        "    await client.post('https://gw/v1/chat/completions', json={})\n",
    )

    failures = gate._check_python_sources()

    assert any("raw model-completion HTTP call" in failure for failure in failures)


def test_naming_the_endpoint_without_calling_out_is_not_a_violation(
    gate, tmp_path: Path, monkeypatch
) -> None:
    """A module that only mentions the endpoint has not opened a private egress."""

    _fake_design_package(
        gate,
        tmp_path,
        monkeypatch,
        "PUBLIC_PATHS = {'/v1/chat/completions'}\n\n"
        "def is_public(path: str) -> bool:\n"
        "    return path in PUBLIC_PATHS\n",
    )

    assert gate._check_python_sources() == []


def test_the_governed_package_passes_the_python_check(gate) -> None:
    """The shipped design package holds no provider import and no raw egress."""

    assert gate._check_python_sources() == []


# --- frontend pages ----------------------------------------------------------


def test_a_design_studio_page_talking_to_a_model_host_fails_the_gate(
    gate, tmp_path: Path, monkeypatch
) -> None:
    """A browser must not call a model host directly."""

    _fake_frontend_pages(
        gate,
        tmp_path,
        monkeypatch,
        {
            "DesignStudio.tsx": (
                "export const call = () => fetch('https://api.openai.com/v1/chat/completions');\n"
            )
        },
    )

    failures = gate._check_frontend_pages()

    assert any(
        "DesignStudio.tsx" in failure and "api.openai.com" in failure for failure in failures
    )


def test_the_recorded_deck_builder_baseline_may_not_grow(gate, tmp_path: Path, monkeypatch) -> None:
    """DeckBuilder's one governed chat call is recorded; a second one fails.

    The recorded baseline is the shrinking half of the ratchet: the slide
    assistant may keep calling the Hive chat admission, and nothing else may
    start.
    """

    _fake_frontend_pages(
        gate,
        tmp_path,
        monkeypatch,
        {
            "DeckBuilder.tsx": (
                "export const a = () => fetch('/v1/chat/complete');\n"
                "export const b = () => fetch('/v1/chat/complete');\n"
            )
        },
    )

    failures = gate._check_frontend_pages()

    assert any(
        "DeckBuilder.tsx" in failure and "baseline allows 1" in failure for failure in failures
    )


def test_the_recorded_deck_builder_call_is_allowed(gate, tmp_path: Path, monkeypatch) -> None:
    """The recorded baseline itself passes."""

    _fake_frontend_pages(
        gate,
        tmp_path,
        monkeypatch,
        {"DeckBuilder.tsx": "export const a = () => fetch('/v1/chat/complete');\n"},
    )

    assert gate._check_frontend_pages() == []


def test_a_missing_design_studio_page_fails_the_gate(gate, tmp_path: Path, monkeypatch) -> None:
    """A renamed page must not silently escape the gate."""

    pages = _fake_frontend_pages(gate, tmp_path, monkeypatch)
    (pages / "DesignStudio.tsx").unlink()

    failures = gate._check_frontend_pages()

    assert any("is missing; update this gate" in failure for failure in failures)


def test_the_shipped_pages_pass_the_frontend_check(gate) -> None:
    """The shipped Design Studio pages hold no model-host call."""

    assert gate._check_frontend_pages() == []


# --- the gate as a whole -----------------------------------------------------


def test_main_reports_the_violations_it_finds(gate, tmp_path: Path, monkeypatch, capsys) -> None:
    """``main`` is the CI entry point: it must fail loudly and name the breach."""

    _fake_design_package(gate, tmp_path, monkeypatch, "import openai\n")
    _fake_frontend_pages(gate, tmp_path, monkeypatch)

    assert gate.main() == 1

    out = capsys.readouterr().out
    assert "DESIGN-MODEL-EGRESS:" in out
    assert "provider SDK import 'openai'" in out
    assert "governed" in out
