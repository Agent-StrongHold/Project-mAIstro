"""The production images' dependency contract is the lock (#348).

Issue #348 asks for four things the Dockerfiles can each break silently:
every image installs the *locked* versions and hashes of the set it selects;
the build fails on lock drift; the build fails on an unresolvable locked
artifact; and nothing resolves implicitly at build time. A Dockerfile is not
executable by pytest, so these are asserted the way the rest of the
repository asserts image contracts — by reading the file and naming the
string that would have to change for the defect to come back.

Three of the assertions here are about defects that were live in this
repository when the test was written, and each one names the failure it
prevents:

* The engine image's export must select a PACKAGE and an EXTRA. An export
  with neither selects the workspace root — which exports the dev dependency
  group too, so pytest, ruff and mypy would ship in the image while the
  scanners audited the lock. The set the image ships would no longer be the
  set the lock describes.

* The builder stage must put the venv on PATH. The prune step
  (`prune-dependency-namespaces.py`) prunes the purelib of the interpreter
  that runs it; with the base image's python on PATH it would patch the base
  image's site-packages, leave the venv's payload in place, and then assert
  the prune on an environment nobody ships.

* The research image must not select the identity extra. The identity stack
  drags in pytoniq-core-fork, whose wheel installs a generic top-level
  `examples` namespace package; the images that ship identity prune it, and
  the research image has no prune step to prune it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Every Dockerfile that installs Python dependencies for an image that ships.
IMAGE_DOCKERFILES = [
    ROOT / "Dockerfile",
    ROOT / "Dockerfile.research",
    ROOT / "Dockerfile.rsi-runner",
    ROOT / "packages/hive-conductor/Dockerfile",
    ROOT / "deploy/sbx/template/Dockerfile",
    ROOT / "deploy/sbx/template/Dockerfile.tests",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _commands(text: str) -> list[str]:
    """The RUN lines of a Dockerfile, joined back into logical commands.

    A Dockerfile splits a long RUN across `\\` continuations; the contract
    lives in the joined form ("uv export --locked --package maistro-server
    --extra image --no-dev"), so the continuations are folded here.
    """
    joined = re.sub(r"\\\n\s*", " ", text)
    return [line.strip() for line in joined.splitlines() if line.strip().startswith("RUN ")]


@pytest.mark.parametrize("dockerfile", IMAGE_DOCKERFILES, ids=lambda p: p.name)
class TestLockedInstalls:
    def test_no_bare_pip_install_of_a_requirement(self, dockerfile):
        """`pip install <requirement>` re-resolves at build time.

        The failure this prevents is the one #348 exists to close: pip
        picks whatever the index serves that day, so the image ships a
        dependency set that no lock describes and no scan audited.
        """
        offenders = [
            line
            for line in _commands(_read(dockerfile))
            if re.search(r"(?<!uv )\bpip install\b", line)
            and not re.search(r"\bpip install\s+(--\S+\s+)*-r\b", line)
        ]
        assert not offenders, f"{dockerfile.name} resolves at build time: {offenders}"

    def test_the_lock_is_the_only_source(self, dockerfile):
        """Every image install names the lock, one way or the other."""
        text = _read(dockerfile)
        assert "--locked" in text or "uv sync --locked" in text or "--frozen" in text, (
            f"{dockerfile.name} names no locked install"
        )

    def test_the_hashed_install_consumes_the_export_and_nothing_else(self, dockerfile):
        """`uv pip install` run inside the project reads the project.

        The root pyproject.toml carries `constraint-dependencies =
        ["aiohttp>=3.14.4"]` — the CVE-2026-111064 floor the pip-audit gate
        needs over the dev environment, where aiohttp arrives through the
        cosmic-ray tool. `uv pip install` run in the project directory folds
        that floor into the install request, and `--require-hashes` rejects
        an unpinned requirement:

            error: In `--require-hashes` mode, all requirements must have
            their versions pinned with `==`, but found: aiohttp>=3.14.4

        So an install that reads the project fails the build on a floor for
        a package these images do not ship aiohttp for — every production
        image, for a constraint that binds where it belongs (the lock).
        `--no-config` makes the install consume the exported file verbatim.
        """
        offenders = [
            line
            for line in _commands(_read(dockerfile))
            if "uv pip install" in line and "--require-hashes" in line and "--no-config" not in line
        ]
        assert not offenders, f"{dockerfile.name} reads the project at install time: {offenders}"


class TestEngineImage:
    """The root Dockerfile — the image the API server ships in."""

    @property
    def text(self) -> str:
        return _read(ROOT / "Dockerfile")

    def test_the_export_selects_a_package_and_an_extra(self):
        """`uv export --locked` with neither `--package` nor `--extra`
        exports the workspace ROOT, dev group included."""
        exports = [c for c in _commands(self.text) if "uv export" in c]
        assert exports, "the engine image has no export step"
        for command in exports:
            assert "--package " in command, command
            assert "--extra " in command, command
            assert "--no-dev" in command, command
            assert "--no-emit-workspace" in command, command
            assert "--locked" in command, command

    def test_the_hashed_install_is_hashed(self):
        installs = [c for c in _commands(self.text) if "uv pip install" in c]
        assert installs, "the engine image has no uv pip install"
        for command in installs:
            if "-r " in command:  # the third-party export
                assert "--require-hashes" in command, command
            else:  # a workspace member, installed from the copied sources
                assert "--no-deps" in command, command

    def test_the_three_shipped_members_are_installed(self):
        """core, server and canvas: the API server, its core, and the Canvas
        package the supported image ships (#1825)."""
        installs = [c for c in _commands(self.text) if "uv pip install" in c]
        members = " ".join(installs)
        assert "./packages/maistro-core" in members
        assert "./packages/maistro-server" in members
        assert "./packages/maistro-canvas" in members

    def test_the_builder_puts_the_venv_on_path(self):
        """Otherwise the prune patches the base image, not the venv."""
        builder = self.text.split("AS builder", 1)[1]
        assert 'PATH="/app/venv/bin:$PATH"' in builder.split("FROM", 1)[0] or (
            'PATH="/app/venv/bin:$PATH"' in builder
        ), "the builder stage does not put the venv first on PATH"

    def test_the_prune_and_its_assertion_are_in_the_builder(self):
        builder = self.text.split("AS builder", 1)[1]
        prune_at = builder.index("prune-dependency-namespaces.py")
        check_at = builder.index("check-dependency-namespaces.py --production")
        assert prune_at < check_at, "the prune must be asserted in the same layer"


class TestResearchImage:
    """Dockerfile.research — the browser worker."""

    def test_it_does_not_select_the_identity_extra(self):
        """The identity stack ships pytoniq-core-fork's `examples` namespace
        package; the images that select identity prune it, and this one does
        not prune (it has no identity stack to prune)."""
        text = _read(ROOT / "Dockerfile.research")
        assert "identity" not in text

    def test_it_does_select_the_browser_extra(self):
        """The browser stack is this image's reason to exist."""
        exports = [c for c in _commands(_read(ROOT / "Dockerfile.research")) if "uv export" in c]
        assert exports
        for command in exports:
            assert "--extra browser" in command, command
            assert "--require-hashes" in command or "--no-deps" in command, command


class TestWorkspaceMetadataIsPresent:
    """Every --locked install resolves the WHOLE workspace.

    `uv export --locked --package ...` resolves the selection by building the
    workspace root, and `uv sync --locked` (the runner image) builds every
    member. Without the extension members' pyproject.toml in the build
    context both fail outright ("reference-greeter references a workspace in
    tool.uv.sources ... but is not a workspace member"), so the image cannot
    be built at all. The members are metadata for the lock check; they are
    never installed.
    """

    @pytest.mark.parametrize(
        "dockerfile",
        [
            ROOT / "Dockerfile",
            ROOT / "Dockerfile.research",
            ROOT / "Dockerfile.rsi-runner",
            ROOT / "packages/hive-conductor/Dockerfile",
            ROOT / "deploy/sbx/template/Dockerfile",
        ],
        ids=lambda p: p.name,
    )
    def test_the_extension_members_are_copied(self, dockerfile):
        assert "COPY extensions/" in _read(dockerfile), (
            f"{dockerfile.name} exports with --package but does not copy the "
            "workspace's extension members; the export cannot resolve the "
            "selection without them"
        )
