"""M7-A11 architecture fitness: no model path outside the governed Invocation.

The negative controls here fail the suite the moment a design explore/judge
path is added as a raw chat completion — a provider SDK import, a model-host
HTTP call inside ``maistro_design``, or a Design Studio page fetching a model
host directly. The same rules are enforced in CI by
``scripts/check-design-model-egress.py``; this test keeps the proof running
next to the code it governs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DESIGN_SRC = Path(__file__).resolve().parents[1] / "src" / "maistro_design"
FRONTEND_PAGES = (
    Path(__file__).resolve().parents[2] / "hive-conductor" / "frontend" / "src" / "pages"
)

#: Provider SDKs a design module must never import, directly or via alias.
FORBIDDEN_PROVIDER_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "cohere",
        "google.generativeai",
        "google.genai",
        "xai",
        "dashscope",
        "mistralai",
    }
)

#: Model-completion endpoint fragments; combined with an HTTP call below they
#: are the shape of a raw chat completion.
EGRESS_ENDPOINT_FRAGMENTS = ("chat/completions", "/completions", "/v1/responses")
HTTP_CALL_ATTRS = frozenset({"post", "stream", "send", "request"})

#: What a Design Studio page may never do: talk to a model host from the
#: browser. Pages speak to the Hive API (``apiGet``/``apiPost``), never to a
#: provider. A raw model-host string or completion endpoint is always a
#: failure; a bare ``fetch(`` outside the recorded baseline is one too.
MODEL_HOST_MARKERS = (
    "chat/completions",
    "/completions",
    "api.openai.com",
    "api.x.ai",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
)
BARE_EGRESS_MARKERS = ("XMLHttpRequest", "EventSource(", "axios", "fetch(")

#: The Design Studio surfaces this gate covers. DeckBuilder's in-editor slide
#: assistant is a pre-existing caller of the governed Hive chat admission
#: (``/v1/chat/complete``), recorded here ratchet-style: it may not grow, and
#: any other page (or any second occurrence) fails the gate. It is a Hive chat
#: surface, not a design explore/judge path — and it must never become one.
DESIGN_STUDIO_PAGES = (
    "DesignStudio.tsx",
    "FixedPageEditor.tsx",
    "FixedPageArtifactEditor.tsx",
    "DeckBuilder.tsx",
)
RAW_COMPLETION_BASELINE: dict[tuple[str, str], int] = {
    ("DeckBuilder.tsx", "/v1/chat/complete"): 1,
    ("DeckBuilder.tsx", "fetch("): 1,
}


def _iter_python_modules() -> list[Path]:
    return sorted(DESIGN_SRC.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _performs_model_egress(tree: ast.AST, source: str) -> bool:
    """The raw chat-completion shape: a model endpoint fragment plus an HTTP call."""

    if not any(fragment in source for fragment in EGRESS_ENDPOINT_FRAGMENTS):
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in HTTP_CALL_ATTRS
        for node in ast.walk(tree)
    )


def test_no_provider_sdk_imports_anywhere_in_maistro_design() -> None:
    offenders: list[str] = []
    for path in _iter_python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            root = imported.split(".")[0]
            if imported in FORBIDDEN_PROVIDER_MODULES or root in FORBIDDEN_PROVIDER_MODULES:
                offenders.append(f"{path.name}: imports {imported}")
    assert offenders == [], f"provider SDK imports found: {offenders}"


def test_no_module_performs_raw_model_egress() -> None:
    offenders: list[str] = []
    for path in _iter_python_modules():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if _performs_model_egress(tree, source):
            offenders.append(path.name)
    assert offenders == [], f"raw model egress found in: {offenders}"


def test_governed_egress_is_the_only_model_seam() -> None:
    """Positive control: explore/judge reach models through ModelChatEgress."""

    from maistro_design import explore, governance, judge

    for module in (explore, judge):
        assert module.build_model_egress is governance.build_model_egress
        assert module.resolve_design_binding is governance.resolve_design_binding
    source = (DESIGN_SRC / "governance.py").read_text(encoding="utf-8")
    assert "ModelChatEgress" in source
    assert "effects.bindings.resolve" in source


def _design_studio_violations() -> list[str]:
    offenders: list[str] = []
    for name in DESIGN_STUDIO_PAGES:
        page = FRONTEND_PAGES / name
        if not page.exists():
            offenders.append(f"{name}: missing — update DESIGN_STUDIO_PAGES")
            continue
        source = page.read_text(encoding="utf-8")
        for marker in (*MODEL_HOST_MARKERS, *BARE_EGRESS_MARKERS):
            count = source.count(marker)
            allowed = RAW_COMPLETION_BASELINE.get((name, marker), 0)
            if count > allowed:
                offenders.append(f"{name}: {marker!r} occurs {count}x (baseline allows {allowed})")
    return offenders


def test_design_studio_pages_fetch_no_model_host() -> None:
    offenders = _design_studio_violations()
    assert offenders == [], f"Design Studio pages bypass the API boundary: {offenders}"


def test_design_studio_pages_use_the_api_boundary() -> None:
    """Positive control: the pages that exist talk to the Hive API, not raw HTTP."""

    page = FRONTEND_PAGES / "DesignStudio.tsx"
    assert page.exists(), "Design Studio page moved; update DESIGN_STUDIO_PAGES"
    source = page.read_text(encoding="utf-8")
    assert "apiGet" in source and "apiPost" in source


def test_design_engine_keeps_adr061_invariant() -> None:
    """ADR-061: DesignEngine assembles prompt stacks; it never calls a model."""

    engine_source = (DESIGN_SRC / "engine.py").read_text(encoding="utf-8")
    engine_tree = ast.parse(engine_source, filename="engine.py")

    imported = _imported_modules(engine_tree)
    governance_free = imported.isdisjoint(
        {"maistro.capabilities", "maistro.capabilities.model_chat", "maistro.providers"}
    )
    assert governance_free, "engine.py reached into capability/provider internals"
    assert not _performs_model_egress(engine_tree, engine_source)
    assert "class DesignEngine" in engine_source  # the class is still here


@pytest.mark.parametrize(
    "snippet",
    [
        "import openai\nopenai.chat.completions.create()",
        "from litellm import completion",
        'httpx.post("https://gw/v1/chat/completions")',
    ],
)
def test_negative_controls_catch_raw_completions(snippet: str) -> None:
    """The scanner really fires on the forbidden shapes (anti-bit-rot)."""

    tree = ast.parse(snippet)
    imported = _imported_modules(tree)
    sdk_hit = imported.isdisjoint(FORBIDDEN_PROVIDER_MODULES) is False
    assert sdk_hit or _performs_model_egress(tree, snippet)
