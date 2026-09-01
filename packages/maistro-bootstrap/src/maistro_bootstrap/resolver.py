"""Map feature ids to suggested shell commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

CANONICAL_ENGINE_SRC = "https://github.com/Agent-StrongHold/Project-mAIstro.git"


@dataclass(frozen=True)
class Feature:
    """One installable slice."""

    id: str
    label: str
    commands: tuple[str, ...]
    copier_hint: str | None = None


FEATURES: dict[str, Feature] = {
    "core_lib": Feature(
        id="core_lib",
        label="Core library (maistro-core, default dev sync)",
        commands=("uv sync",),
    ),
    "tui": Feature(
        id="tui",
        label="TUI helpers (Typer + Rich on maistro-core)",
        commands=('uv pip install -e "./packages/maistro-core[tui]"',),
    ),
    "server": Feature(
        id="server",
        label="HTTP API (maistro-server)",
        commands=("uv pip install -e ./packages/maistro-server",),
    ),
    "canvas": Feature(
        id="canvas",
        label="Canvas package (maistro-canvas)",
        commands=("uv pip install -e ./packages/maistro-canvas",),
    ),
    "turing": Feature(
        id="turing",
        label="Turing extensions (maistro-turing)",
        commands=("uv pip install -e ./packages/maistro-turing",),
    ),
    "webui": Feature(
        id="webui",
        label="Compose: Open WebUI (see root docker-compose.yml)",
        commands=(
            "# WebUI is enabled in default docker-compose.yml",
            "docker compose up -d open-webui",
        ),
    ),
    "data": Feature(
        id="data",
        label="Compose: Postgres (see docs/install/compose-slices.example.yml for profile naming)",
        commands=("docker compose up -d postgres",),
    ),
    "llm_proxy": Feature(
        id="llm_proxy",
        label="Compose: LiteLLM proxy",
        commands=("docker compose up -d litellm",),
    ),
    "observability": Feature(
        id="observability",
        label="Compose: Langfuse",
        commands=("docker compose up -d langfuse",),
    ),
    "hive_conductor": Feature(
        id="hive_conductor",
        label="Hive Conductor package (API + UI dev; base compose in package)",
        commands=(
            "uv pip install -r packages/hive-conductor/backend/requirements.txt",
            "# Optional UI build: (cd packages/hive-conductor/frontend && npm ci && npm run build)",
            "# Base compose file: packages/hive-conductor/docker-compose.yml",
        ),
    ),
}


@dataclass(frozen=True)
class ComposeAddon:
    """Optional compose fragment: validate with Docker, run with Podman."""

    id: str
    label: str
    validate: tuple[str, ...]
    run_with_podman: tuple[str, ...]


COMPOSE_ADDONS: dict[str, ComposeAddon] = {
    "hive_phoenix": ComposeAddon(
        id="hive_phoenix",
        label="Hive: merge Arize Phoenix fragment (see compose/fragments/phoenix.yml)",
        validate=(
            "# Validate merged compose (Hive + Phoenix, observe profile):",
            "docker compose -f packages/hive-conductor/docker-compose.yml \\",
            "  -f packages/hive-conductor/compose/fragments/phoenix.yml --profile observe config",
        ),
        run_with_podman=(
            "# Bring the stack up (requires Podman):",
            "podman compose -f packages/hive-conductor/docker-compose.yml \\",
            "  -f packages/hive-conductor/compose/fragments/phoenix.yml --profile observe up -d",
        ),
    ),
}

PRODUCTS: dict[str, tuple[str, str]] = {
    "single-tenant-multi-user": (
        "Single-tenant multi-user product",
        "templates/single-tenant-multi-user",
    ),
    "autonoetic": (
        "Autonoetic product",
        "templates/autonoetic",
    ),
    "multi-tenant": (
        "Stronghold-shaped product",
        "templates/multi-tenant",
    ),
}


def commands_for(features: set[str]) -> list[str]:
    lines: list[str] = []
    for fid in sorted(features):
        if fid not in FEATURES:
            lines.append(f"# Unknown feature id: {fid}")
            continue
        feat = FEATURES[fid]
        lines.append(f"# --- {feat.label} ---")
        lines.extend(feat.commands)
    return lines


def commands_for_compose_addons_validate(addons: set[str]) -> list[str]:
    """`docker compose … config` (or similar) before installing Podman."""
    lines: list[str] = []
    if not addons:
        return lines
    lines.append("# --- Compose add-ons: validate merge (Docker) ---")
    for aid in sorted(addons):
        if aid not in COMPOSE_ADDONS:
            lines.append(f"# Unknown compose addon id: {aid}")
            continue
        addon = COMPOSE_ADDONS[aid]
        lines.append(f"# --- {addon.label} ---")
        lines.extend(addon.validate)
    return lines


def commands_for_compose_addons_run_podman(addons: set[str]) -> list[str]:
    """`podman compose` lines; print after Podman install preface."""
    if not addons:
        return []
    body: list[str] = []
    has_podman = False
    for aid in sorted(addons):
        if aid not in COMPOSE_ADDONS:
            body.append(f"# Unknown compose addon id: {aid}")
            continue
        addon = COMPOSE_ADDONS[aid]
        if not addon.run_with_podman:
            continue
        body.append(f"# --- {addon.label} ---")
        body.extend(addon.run_with_podman)
        has_podman = True
    if not body:
        return []
    if has_podman:
        return ["# --- Compose add-ons: run stack (Podman) ---", *body]
    return body


def podman_install_preface_lines() -> list[str]:
    return [
        "# --- Install Podman *before* `podman compose` (pick one recipe) ---",
        "# Fedora/RHEL: sudo dnf install -y podman",
        "# Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y podman",
        "# macOS: brew install podman && podman machine init && podman machine start",
    ]


def should_print_podman_preface(compose_addons: set[str]) -> bool:
    for aid in compose_addons:
        addon = COMPOSE_ADDONS.get(aid)
        if addon is not None and addon.run_with_podman:
            return True
    return False


def copier_command(product: str, dest: str) -> str | None:
    if product not in PRODUCTS:
        return None
    # SECURITY-REVIEW: Product is allowlisted above and the only caller prints
    # this command for a human; quote the configurable destination regardless.
    if product == "multi-tenant":
        _title, path = PRODUCTS[product]
        return f"uv run copier copy {path} {shlex.quote(dest)}"
    return (
        f"uv run copier copy --data product_template={product} "
        f"{CANONICAL_ENGINE_SRC} {shlex.quote(dest)}"
    )
