"""M7-A14 contract-forbid: no second design product (#990).

Contract under test: #990 (M7-A14), extending #790 (ADR-092926-7a01 kind
fencing) and #796 (Evolve/RSI consumer guards). Where #790 fences the
*runtime* registry against a competing Goal/Rubric/EvalRun kind, this suite
freezes the *product boundary* in CI: M7 is continued development of the Hive
Conductor Design Studio plus the maistro-core Goal/Rubric/Run loop — not a
new project, not a Canvas product, and not an app called Atelier.

Each test names one forbidden product shape and fails the PR that adds it:

1. Package/app identity — ``packages/maistro-atelier``/``packages/atelier``,
   an ``Atelier.tsx`` page, a ``/atelier`` route, or product copy naming
   Atelier as a shipped surface.
2. Execution identity — a ``DesignRun`` / ``EvalRun`` / ``VariantStore``
   declared in production code as a second execution lifecycle.
3. Client persistence — ``zustand/persist`` or a ``localStorage`` /
   ``sessionStorage`` / ``IndexedDB`` key carrying design-loop state
   (Goal, Rubric, eval, waves, fence). UI may cache; APIs own truth.
4. Director/judge egress — a provider SDK or raw chat-completions client in
   Design Studio or ``maistro_design`` (ADR-061: the DesignEngine does not
   call an LLM), or a provider API key read by the Hive frontend outside the
   declared credential-authority route.
5. Pack-as-product — ``packages/maistro-book`` / ``packages/maistro-game``
   or ``/book`` / ``/game`` / ``/product`` routes as product identity.
6. Simulated execution — ``setTimeout``/``setInterval`` stage animation in
   the Design Studio surfaces presented as pipeline progress (#286 / #465).
7. Prototype import — a sandbox/legacy prototype tree imported as the
   implementation (SPEC-178 removed those trees; ``sbx/`` kits are Docker
   sandbox *specs*, never imported runtime code).

The scans are static (regex + path) and deliberately syntactically shallow:
these are tripwires against whole product shapes reappearing, not style
lints. Every allowlist below is a named, documented exception that passes on
``develop`` today.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACKAGES = _REPO_ROOT / "packages"
_FRONTEND_SRC = _PACKAGES / "hive-conductor" / "frontend" / "src"
_HIVE_BACKEND = _PACKAGES / "hive-conductor" / "backend"
_DESIGN_SRC = _PACKAGES / "maistro-design" / "src" / "maistro_design"

#: The Design Studio loop host plus the editors it composes. These are the
#: surfaces a second product would restyle or re-wire (#986: chrome that
#: projects canonical state), so they get the strictest scans.
_DESIGN_STUDIO_PAGES = (
    "DesignStudio.tsx",
    "DeckBuilder.tsx",
    "FixedPageEditor.tsx",
    "FixedPageArtifactEditor.tsx",
)

#: Competing execution-lifecycle names (#990 forbidden shape 2). Word-boundary
#: matched, so ``DesignRunner`` is not a violation but ``DesignRun`` is.
_COMPETING_LIFECYCLE_NAMES = ("DesignRun", "EvalRun", "VariantStore")

#: Loop-state nouns that may never become a browser-storage key (#990
#: forbidden shape 3). Keys are split on non-alphanumerics and matched on
#: whole segments, so ``hive_retrieval_cache`` is not a false positive.
_LOOP_STATE_NOUNS = frozenset(
    {
        "goal",
        "goals",
        "rubric",
        "rubrics",
        "eval",
        "evals",
        "evaluation",
        "evaluations",
        "wave",
        "waves",
        "fence",
        "fences",
    }
)

#: Provider SDK roots whose import in a design surface is a director/judge
#: egress (#990 forbidden shape 4; ADR-061).
_PY_PROVIDER_SDK_ROOTS = frozenset(
    {
        "openai",
        "anthropic",
        "litellm",
        "mistralai",
        "cohere",
        "groq",
        "xai",
        "google.genai",
        "google.generativeai",
    }
)

_JS_PROVIDER_SDK_IMPORTS = re.compile(
    r"""\bfrom\s+["'](@anthropic-ai/sdk|openai|litellm|groq-sdk|"""
    r"""@mistralai/mistralai|@google/generative-ai|@google/genai|"""
    r"""cohere-ai|xai-sdk|@ai-sdk/openai|@ai-sdk/anthropic)["']""",
)

#: Raw chat-completions / model-host endpoint fragments (#987).
_MODEL_ENDPOINT_FRAGMENTS = (
    "/chat/completions",
    "/v1/completions",
    "/v1/responses",
    "api.x.ai",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "api.mistral.ai",
    "api.together.xyz",
    "api.deepseek.com",
    "openrouter.ai",
)

#: Provider API-key env names. The Hive frontend may never read one; the Hive
#: backend may only name them inside the declared credential/provider
#: configuration surface (routes/providers.py advertises which env key each
#: provider needs — it does not loop egress through them).
_PROVIDER_KEY_NAMES = (
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "OPENROUTER_API_KEY",
)

#: Backend files allowed to name provider keys: the credential/provider
#: configuration route plus its tests (quality/credential-authority.json
#: owns the deeper authority analysis).
_HIVE_BACKEND_KEY_FILE_ALLOWLIST = frozenset({"routes/providers.py"})

#: Routes that would be a second product's identity, never a Hive page
#: (#990 forbidden shapes 1 and 5). Exact path segment, case-insensitive.
_FORBIDDEN_ROUTE_SEGMENTS = frozenset({"atelier", "book", "game", "product"})

#: Package names a second product would ship under.
_FORBIDDEN_PACKAGE_DIRS = (
    "atelier",
    "maistro-atelier",
    "book",
    "maistro-book",
    "game",
    "maistro-game",
)

#: Legacy prototype trees removed by SPEC-178; re-importing them as the
#: implementation is forbidden shape 7.
_LEGACY_SNAPSHOT_DIRS = ("code-worth-implementing-from-legacy-maistro-site", "legacy-maistro-site")

_SKIP_DIR_PARTS = frozenset({"node_modules", "__pycache__", ".venv", "dist", "build"})

# Design-system catalog data (ADR-100 bundled open design systems, #793
# registry): slugs like ``atelier-zero`` are design-system identities inside
# the maistro-design registry, not shipped product surfaces. Everything else
# under production source is scanned.
_CATALOG_DATA_MARKER = "systems/catalog"


def _iter_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        p
        for p in root.rglob("*")
        if p.suffix in suffixes and not _SKIP_DIR_PARTS.intersection(p.parts)
    ]


@cache
def _frontend_files() -> list[Path]:
    return _iter_files(_FRONTEND_SRC, (".ts", ".tsx"))


@cache
def _frontend_pages() -> list[Path]:
    return [p for p in _frontend_files() if p.parent.name == "pages"]


@cache
def _design_studio_files() -> list[Path]:
    return [p for p in _frontend_files() if p.name in _DESIGN_STUDIO_PAGES]


@cache
def _production_python_files() -> list[Path]:
    """``packages/*/src`` trees plus the flat hive-conductor backend app."""
    files: list[Path] = []
    for pkg in sorted(_PACKAGES.iterdir()):
        src = pkg / "src"
        if src.is_dir():
            files.extend(_iter_files(src, (".py",)))
    if _HIVE_BACKEND.is_dir():
        files.extend(_iter_files(_HIVE_BACKEND, (".py",)))
    return files


def _is_test_path(path: Path) -> bool:
    return "test" in path.parts or path.name.startswith("test_")


def _production_py_without_tests() -> list[Path]:
    return [p for p in _production_python_files() if not _is_test_path(p)]


def _relative(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1. Package / app identity: no Atelier product, no pack-as-product packages
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_no_second_product_package_directories() -> None:
    """No ``packages/atelier`` / ``maistro-atelier`` / pack-as-product package."""
    existing = [
        d.name
        for d in sorted(_PACKAGES.iterdir())
        if d.is_dir() and d.name in _FORBIDDEN_PACKAGE_DIRS
    ]
    assert not existing, f"second-product package directories must not exist (#990): {existing}"


@pytest.mark.contract("boundary")
def test_no_atelier_page_file() -> None:
    """No ``Atelier.tsx`` page anywhere under ``packages/``."""
    offenders = [
        _relative(p) for p in _iter_files(_PACKAGES, (".tsx",)) if p.stem.lower() == "atelier"
    ]
    assert not offenders, f"Atelier page files are a forbidden product identity (#990): {offenders}"


@pytest.mark.contract("boundary")
def test_no_forbidden_product_routes() -> None:
    """No ``/atelier`` (or ``/book`` / ``/game`` / ``/product``) Hive route.

    The frontend route table lives in ``App.tsx`` (``<Route path="...">``);
    the backend exposes ``APIRouter(prefix=...)`` mounts. Either surface
    registering a forbidden segment is a second product identity.
    """
    offenders: list[str] = []

    app_tsx = _FRONTEND_SRC / "App.tsx"
    for match in re.finditer(r"""path=["']([^"']+)["']""", _read(app_tsx)):
        for segment in match.group(1).split("/"):
            if segment.lower() in _FORBIDDEN_ROUTE_SEGMENTS:
                offenders.append(f"{_relative(app_tsx)}: path {match.group(1)!r}")

    for path in _production_py_without_tests():
        if _CATALOG_DATA_MARKER in path.parts:
            continue
        for match in re.finditer(r"""prefix=["']([^"']+)["']""", _read(path)):
            for segment in match.group(1).strip("/").split("/"):
                if segment.lower() in _FORBIDDEN_ROUTE_SEGMENTS:
                    offenders.append(f"{_relative(path)}: prefix {match.group(1)!r}")

    assert not offenders, f"forbidden product routes registered (#990): {offenders}"


@pytest.mark.contract("boundary")
def test_no_atelier_product_copy_in_hive_surfaces() -> None:
    """No product copy naming Atelier as a shipped Hive surface.

    Scan the Hive frontend and backend for a standalone ``Atelier`` token.
    The maistro-design *catalog data* (``systems/catalog/``, ADR-100) is
    excluded: a design-system slug like ``atelier-zero`` is registry content,
    not product identity — but no Python or TS source outside that data may
    name the product.
    """
    pattern = re.compile(r"\bAtelier\b")
    offenders: list[str] = []
    for path in [*_frontend_files(), *_production_py_without_tests()]:
        if _CATALOG_DATA_MARKER in path.parts:
            continue
        if pattern.search(_read(path)):
            offenders.append(_relative(path))
    assert not offenders, (
        f"Atelier product copy outside the design-system catalog (#990): {offenders}"
    )


# ---------------------------------------------------------------------------
# 2. Execution identity: no DesignRun / EvalRun / VariantStore
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.parametrize("name", _COMPETING_LIFECYCLE_NAMES)
def test_no_competing_execution_lifecycle_name(name: str) -> None:
    """Production code may not declare a second execution lifecycle (#990).

    Run/NodeRun/Attempt is the one execution identity (#36, #542); #790
    fences the registry at runtime. This is the static twin: the *name* of a
    competing design-loop lifecycle must not appear anywhere in production
    source — a declaration, export, or stray reference all count.
    """
    pattern = re.compile(rf"\b{name}\b")
    offenders: list[str] = []
    for path in [
        *_production_py_without_tests(),
        *_frontend_files(),
    ]:
        if pattern.search(_read(path)):
            offenders.append(_relative(path))
    assert not offenders, (
        f"{name!r} is a forbidden second execution lifecycle; Run/NodeRun/Attempt "
        f"is the one execution identity (#990, #790): {offenders}"
    )


# ---------------------------------------------------------------------------
# 3. Client persistence: no browser system of record for loop state
# ---------------------------------------------------------------------------


def _segments(key: str) -> set[str]:
    return {part for part in re.split(r"[^a-zA-Z0-9]+", key.lower()) if part}


def _module_string_constants(source: str) -> dict[str, str]:
    """``const NAME = "..."`` bindings a storage call may pass as its key."""
    constants: dict[str, str] = {}
    for match in re.finditer(
        r"""\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*["']([^"']*)["']""",
        source,
    ):
        constants[match.group(1)] = match.group(2)
    return constants


@pytest.mark.contract("boundary")
def test_no_client_persist_of_design_loop_state() -> None:
    """No browser storage key carries Goal/Rubric/eval/wave/fence state.

    ``localStorage`` for UI conveniences (theme, onboarding, active
    workspace tab, sanitized artifact markup cache) is allowed — the Hive
    frontend already owns such keys and they are explicitly *not* the record
    (#1418). What this forbids is a client-persist loop: a storage key whose
    name carries design-loop state, or the ``zustand/persist`` middleware
    that was the disposable prototype's system of record.
    """
    offenders: list[str] = []

    for path in _frontend_files():
        source = _read(path)
        if "zustand/persist" in source:
            offenders.append(f"{_relative(path)}: zustand/persist import")

        constants = _module_string_constants(source)
        for api in re.finditer(
            r"""(?:window\.)?(?:localStorage|sessionStorage)\.(?:getItem|setItem|"""
            r"""removeItem)\(\s*["']?([A-Za-z_$][\w$]*)""",
            source,
        ):
            raw = api.group(1)
            key = raw if raw[0] in "\"'" else constants.get(raw, raw)
            hit = _segments(key) & _LOOP_STATE_NOUNS
            if hit:
                offenders.append(
                    f"{_relative(path)}: storage key {key!r} carries loop state {sorted(hit)}"
                )

        for open_call in re.finditer(
            r"""\bindexedDB\.(?:open|deleteDatabase)\(\s*["']([^"']+)["']""",
            source,
        ):
            hit = _segments(open_call.group(1)) & _LOOP_STATE_NOUNS
            if hit:
                offenders.append(
                    f"{_relative(path)}: IndexedDB {open_call.group(1)!r} carries loop state {sorted(hit)}"
                )

    assert not offenders, (
        "browser storage must never be the system of record for design-loop "
        f"state (#990): {offenders}"
    )


# ---------------------------------------------------------------------------
# 4. Director/judge egress: no provider SDK, no raw chat completions
# ---------------------------------------------------------------------------


def _imported_roots(path: Path) -> set[str]:
    try:
        tree = ast.parse(_read(path), filename=str(path))
    except SyntaxError:  # pragma: no cover - not expected in-tree
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module)
    return roots


@pytest.mark.contract("boundary")
def test_maistro_design_has_no_provider_sdk_or_model_egress() -> None:
    """``maistro_design`` gains no provider SDK / raw chat-completions client.

    ADR-061: the DesignEngine builds the prompt stack and hands it to
    maistro-core's conduit; it never calls a model. The Open Design provider
    (``providers/open_design.py``) fetches design-system bundles over HTTP
    and stays allowed — it targets no model endpoint and reads no provider
    key. A provider SDK import, a chat-completions/completions endpoint
    fragment, or a provider-key read anywhere in the package fails here.
    """
    offenders: list[str] = []
    for path in _iter_files(_DESIGN_SRC, (".py",)):
        rel = _relative(path)
        for module in _imported_roots(path):
            if module.split(".")[0] in _PY_PROVIDER_SDK_ROOTS or module in _PY_PROVIDER_SDK_ROOTS:
                offenders.append(f"{rel}: provider SDK import {module!r}")
        source = _read(path)
        for fragment in _MODEL_ENDPOINT_FRAGMENTS:
            if fragment in source:
                offenders.append(f"{rel}: model endpoint fragment {fragment!r}")
        for key in _PROVIDER_KEY_NAMES:
            if key in source:
                offenders.append(f"{rel}: provider key {key!r}")
    assert not offenders, (
        "maistro_design must not call a model; egress belongs to maistro-core's "
        f"conduit (ADR-061, #990): {offenders}"
    )


def _design_studio_offenses(path: Path) -> list[str]:
    """Egress/simulation violations in one Design Studio surface file."""
    rel = _relative(path)
    source = _read(path)
    found: list[str] = []
    for call in re.finditer(r"""\bfetch\s*\(\s*[\"']([^\"']+)[\"']""", source):
        target = call.group(1)
        if re.match(r"^(?:[a-zA-Z][\w+.-]*:|//)", target):
            found.append(f"fetch to non-same-origin target {target!r}")
    if _JS_PROVIDER_SDK_IMPORTS.search(source):
        found.append("provider SDK import")
    for fragment in _MODEL_ENDPOINT_FRAGMENTS:
        if fragment in source:
            found.append(f"model endpoint fragment {fragment!r}")
    for key in _PROVIDER_KEY_NAMES:
        if key in source:
            found.append(f"provider key {key!r}")
    for timer in ("setTimeout", "setInterval"):
        if re.search(rf"\b{timer}\s*\(", source):
            found.append(f"{timer}( — simulated pipeline progress")
    return [f"{rel}: {offense}" for offense in found]


@pytest.mark.contract("boundary")
def test_design_studio_has_no_direct_model_client() -> None:
    """Design Studio stays chrome: no model-host fetch, SDK, key, or fake pipeline.

    The canonical host projects state through ``lib/api`` (``apiGet`` /
    ``apiPost``). Forbidden here (#987, forbidden shape 4): a provider SDK
    import, a model-host endpoint fragment, a provider API key, or a
    ``fetch`` whose target leaves the Hive origin. Same-origin calls to the
    Hive backend's own chat route stay allowed: the backend owns the provider
    key and is the ledgered egress (``maistro_server.api.chat_completions``
    in ``quality/model-egress.json``), so the browser never talks to a model
    host. ``setTimeout``/``setInterval`` is the client stage-animation shape
    that presents animation as pipeline progress (#286 / #465).
    """
    offenders = [
        offense for path in _design_studio_files() for offense in _design_studio_offenses(path)
    ]
    assert not offenders, f"Design Studio must project, not orchestrate (#990): {offenders}"


@pytest.mark.contract("boundary")
def test_no_provider_sdk_anywhere_in_hive_frontend() -> None:
    """The Hive frontend never imports a provider SDK or model endpoint."""
    offenders: list[str] = []
    for path in _frontend_files():
        rel = _relative(path)
        source = _read(path)
        if _JS_PROVIDER_SDK_IMPORTS.search(source):
            offenders.append(f"{rel}: provider SDK import")
        for fragment in _MODEL_ENDPOINT_FRAGMENTS:
            if fragment in source:
                offenders.append(f"{rel}: model endpoint fragment {fragment!r}")
    assert not offenders, f"provider egress in the Hive frontend (#990): {offenders}"


@pytest.mark.contract("boundary")
def test_provider_keys_read_only_by_credential_authority() -> None:
    """Provider API keys stay inside the declared configuration surface.

    The Hive frontend may never read a provider key. The Hive backend may
    only *name* them where it advertises provider configuration
    (``routes/providers.py`` and its tests) — a key read anywhere else is a
    private loop's egress path (#987).
    """
    offenders: list[str] = []

    for path in _frontend_files():
        source = _read(path)
        for key in _PROVIDER_KEY_NAMES:
            if key in source:
                offenders.append(f"{_relative(path)}: frontend reads {key}")

    for path in _production_py_without_tests():
        if not path.is_relative_to(_HIVE_BACKEND):
            continue
        rel = path.relative_to(_HIVE_BACKEND).as_posix()
        if rel in _HIVE_BACKEND_KEY_FILE_ALLOWLIST:
            continue
        source = _read(path)
        for key in _PROVIDER_KEY_NAMES:
            if key in source:
                offenders.append(
                    f"{_relative(path)}: backend names {key} outside the provider config route"
                )

    assert not offenders, (
        f"provider keys must stay inside the credential authority (#990): {offenders}"
    )


# ---------------------------------------------------------------------------
# 7. Prototype import: no sandbox/legacy tree as implementation
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
def test_no_sandbox_prototype_tree_imported() -> None:
    """Legacy snapshot trees stay removed; ``sbx`` kits stay out of imports.

    SPEC-178 removed the ``code-worth-implementing-from-*`` and
    ``legacy-maistro-site`` snapshots; their reappearance as implementation
    is forbidden shape 7. ``sbx/`` holds Docker Sandboxes *kit specs* (RSI
    execution substrate) — production code importing it as a module would be
    importing a prototype tree instead of the packages.
    """
    present = [d for d in _LEGACY_SNAPSHOT_DIRS if (_REPO_ROOT / d).is_dir()]
    assert not present, f"legacy prototype trees must not reappear (SPEC-178, #990): {present}"

    offenders: list[str] = []
    for path in _production_py_without_tests():
        for module in _imported_roots(path):
            if module == "sbx" or module.startswith("sbx."):
                offenders.append(f"{_relative(path)}: imports {module!r}")
    assert not offenders, f"production code importing the sandbox kit tree (#990): {offenders}"
