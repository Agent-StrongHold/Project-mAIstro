"""Static halves of the shipped-image smoke contract.

The docker-build job supplies the behavioral half by booting the exact image.
These assertions prevent the Compose, installer, and image declarations from
drifting independently between those comparatively expensive runs.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

#: The security floors the browser stack must clear. These are develop's
#: floors, carried over unchanged: the aiohttp floor is the CVE-2026-111064
#: family (GHSA-2g87-pp6c-29x5 / CVE-2026-111063), the pillow floor is the
#: 12.x advisory set, and the rest are the versions develop's browser
#: install asserted at runtime.
BROWSER_SECURITY_FLOORS = {
    "aiohttp": "3.14.4",
    "anyio": "4.14.2",
    "browser-use": "0.1.40",
    "pillow": "13.0.0",
    "pypdf": "6.19.0",
}


def _locked_export(*selection: str) -> dict[str, str]:
    """The pinned set the research image installs, name -> version.

    This runs the very command `Dockerfile.research` runs — `uv export
    --locked` over the committed lock — so the answer is the artifact the
    image installs, not a re-resolution. `--offline` keeps it hermetic: the
    export is a projection of the committed lock, so it needs no index and
    no cache.
    """
    result = subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--offline",
            "--package",
            "maistro-server",
            *selection,
            "--no-dev",
            "--no-emit-workspace",
            "--format",
            "requirements-txt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    pins: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", line)
        if match:
            pins[match.group(1)] = match.group(2)
    return pins


def test_postgres_18_mount_and_pgdata_move_together() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]
    layout_check = compose["services"]["postgres-layout-check"]

    assert postgres["environment"]["PGDATA"] == "/var/lib/postgresql/18/docker"
    assert "pgdata:/var/lib/postgresql" in postgres["volumes"]
    assert all(not mount.endswith(":/var/lib/postgresql/data") for mount in postgres["volumes"])

    # An old install mounted the named volume directly at /var/lib/postgresql/data,
    # so its PG_VERSION lives at the volume root once mounted at the PG18 parent.
    # Startup must stop before PostgreSQL can initialize a second, empty cluster.
    command = "\n".join(layout_check["command"])
    assert "pgdata:/var/lib/postgresql:ro" in layout_check["volumes"]
    assert "/var/lib/postgresql/PG_VERSION" in command
    assert "/var/lib/postgresql/18/docker/PG_VERSION" in command
    assert "exit 78" in command
    assert postgres["depends_on"]["postgres-layout-check"]["condition"] == (
        "service_completed_successfully"
    )


def test_engine_compose_passes_every_required_auth_value() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["maistro-engine"]["environment"]
    socket_override = yaml.safe_load(
        (ROOT / "docker-compose.docker-sock.override.example.yml").read_text(encoding="utf-8")
    )
    override_environment = socket_override["services"]["maistro-engine"]["environment"]

    assert any(item.startswith("API_KEYS=") for item in environment)
    assert any(item.startswith("ROUTER_API_KEY=") for item in environment)
    assert "SANDBOX_READINESS_REQUIRED=false" in environment
    assert "SANDBOX_READINESS_REQUIRED=true" in override_environment


def test_installer_example_uses_the_settings_json_representation() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    raw = next(
        line.split("=", 1)[1].split("#", 1)[0].strip()
        for line in example.splitlines()
        if line.startswith("API_KEYS=")
    )

    assert json.loads(raw) == []
    assert "ROUTER_API_KEY=" in example


def test_image_pins_supported_python_and_installs_identity() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    python_tags = re.findall(r"^FROM python:(3\.\d+\.\d+)-slim-bookworm", dockerfile, re.MULTILINE)

    assert python_tags == ["3.13.16", "3.13.16"]
    # #348 moved the image's dependency contract out of a pip command line in
    # the Dockerfile and into maistro-server's `image` extra, which the
    # Dockerfile exports from the committed lock. The identity stack the
    # image ships is named there now — and the Dockerfile must select that
    # extra, or the contract is declared and never installed.
    #
    # The sqlite extra is runtime-required as well (the sqlite persistence
    # deployment, 2dfd3b97a): the container wires SqliteCampaignStore,
    # SqliteWorkspaceLogStore and backlog history, which import aiosqlite.
    server = tomllib.loads(
        (ROOT / "packages/maistro-server/pyproject.toml").read_text(encoding="utf-8")
    )
    image_extra = server["project"]["optional-dependencies"]["image"]
    assert any(
        "maistro-core[identity,llm,sandbox,observability,sqlite]" in item for item in image_extra
    ), image_extra
    assert "--extra image" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "maistro_server.entrypoint"]' in dockerfile


def test_research_ships_the_locked_browser_stack_above_the_security_floors() -> None:
    """The research image must not ship a browser stack below the security floors.

    This test used to be named `test_research_reasserts_pillow_security_floor_
    after_browser_install`, and it read the floors off a second, unpinned
    `uv pip install --system` block in `Dockerfile.research` — the step that
    ran AFTER the browser install and could therefore land a dependency set
    no scanner ever audited (#348). That step is gone: the research image
    installs the committed lock's export with `--require-hashes`, so the
    floors have to hold in the lock, and the image has to prove that what it
    ships IS the lock rather than a second resolution.

    Two failures are prevented:

    * A re-resolution sneaking back in. `uv pip install --system
      "browser-use>=0.1.40"` picks whatever the index serves that day, and it
      is exactly the step that let the image drift away from the lock. The
      image installs the locked export and the two workspace members
      (`--no-deps`) — nothing else may install anything.
    * The lock itself carrying a stack below the floors. The image installs
      the lock, so a floor that is not met in the lock is a floor the image
      ships unmet — whatever the Dockerfile says.
    """
    dockerfile = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")

    # No second install step: nothing may resolve against the index.
    assert "uv pip install --system" not in dockerfile
    # A Dockerfile splits a long RUN across `\` continuations; the contract
    # lives in the joined form, so fold the continuations first.
    joined = re.sub(r"\\\n\s*", " ", dockerfile)
    installs = [
        line.strip()
        for line in joined.splitlines()
        if line.strip().startswith("RUN ") and "uv pip install" in line
    ]
    assert installs, "the research image installs nothing"
    for command in installs:
        if "-r " in command:  # the third-party export
            assert "--require-hashes" in command, command
        else:  # a workspace member, installed from the copied sources
            assert "--no-deps" in command, command

    # The floors, checked against the committed lock: the artifact the image
    # installs. Lexical comparison would accept 9.x as newer than 13.x, so
    # compare as PEP 440 versions.
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = {package["name"]: package["version"] for package in lock["package"]}
    for name, floor in BROWSER_SECURITY_FLOORS.items():
        assert name in versions, f"{name} is not in the lock at all"
        assert Version(versions[name]) >= Version(floor), (
            f"{name} {versions[name]} is below the security floor {floor}"
        )

    # ... and the set the research image actually installs must carry the
    # browser stack it exists for, at or above the same floors.
    shipped = _locked_export("--extra", "observability", "--extra", "browser")
    assert "browser-use" in shipped, shipped.keys()
    assert "playwright" in shipped, shipped.keys()
    for name, version in shipped.items():
        floor = BROWSER_SECURITY_FLOORS.get(name)
        if floor is not None:
            assert Version(version) >= Version(floor), (
                f"the research image ships {name} {version}, below the floor {floor}"
            )


def test_docker_build_job_boots_the_image_it_built() -> None:
    """The job that builds maistro-engine:test must boot that exact image.

    Since #1825 the boot itself lives in scripts/smoke-engine-canvas.sh —
    shared with release.yml, which runs the same proof against the pushed
    digest — so the workflow-side half asserts the invocation follows the
    build, and the script-side half asserts the boot order (liveness before
    readiness) that used to be pinned inline here.
    """
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    build = workflow.index("-t maistro-engine:test")
    boot = workflow.index("scripts/smoke-engine-canvas.sh maistro-engine:test", build + 1)
    assert build < boot

    script = (ROOT / "scripts/smoke-engine-canvas.sh").read_text(encoding="utf-8")
    live = script.index("/health/live")
    ready = script.index("/health/ready", live)
    assert live < ready
