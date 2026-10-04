"""The installer surface stays placeholder-free and single-owned (#401).

``scripts/install-maestro.sh`` was a curl-pipe-bash advertisement that
installed nothing: its usage line pointed at a literal
``https://raw.githubusercontent.com/<org>/...`` placeholder and its clone
step said ``git clone ... <YOUR_REPO_URL>``. A user or agent following it got
instructions, not an install, while the real entrypoints — ``get.sh`` /
``install.sh`` (POSIX), ``get.ps1`` (Windows/WSL), and ``maistro-install``
in-repo — sat nearby. #401 removed the file; these tests pin the properties
whose loss would recreate the defect class, against the real tree rather
than a fixture list.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Product install entrypoints: the repo-root launchers. One per platform:
#: ``get.sh``/``install.sh`` for POSIX, ``get.ps1`` for Windows.
#: ``scripts/install-quality-scanners.sh`` installs dev tooling, not the
#: product, and is deliberately not part of this set.
ENTRYPOINTS = ("get.sh", "get.ps1", "install.sh")

#: Every documented/executable installer path: the entrypoints themselves
#: plus the prose that advertises them and the planner constant that names
#: the hosted payload.
SURFACE = (
    *(REPO / name for name in ENTRYPOINTS),
    REPO / "README.md",
    REPO / "docs" / "install" / "default-installer.md",
    REPO / "docs" / "install" / "resolver-matrix.md",
    REPO / "packages" / "maistro-bootstrap" / "src" / "maistro_bootstrap" / "plan.py",
)

#: A URL with an unfilled ``<...>`` slot is the exact shape that shipped in
#: ``install-maestro.sh`` (``https://raw.githubusercontent.com/<org>/...``).
URL_WITH_SLOT = re.compile(r"https?://[^\s\"'`)]*[<>]")

#: Bare placeholder tokens from the same file
#: (``git clone ... <YOUR_REPO_URL> "$TARGET"``).
PLACEHOLDER_TOKENS = ("<YOUR", "YOUR_REPO", "<org>", "<ORG>")


def test_removed_placeholder_installer_stays_removed() -> None:
    """The dead curl-pipe-bash helper #401 deleted must not come back."""
    assert not (REPO / "scripts" / "install-maestro.sh").exists()


def test_product_install_entrypoints_are_exactly_the_supported_ones() -> None:
    """One authoritative entrypoint per platform, and no strays at the root."""
    found = {
        path.name for pattern in ("get.sh", "get.ps1", "install*.sh") for path in REPO.glob(pattern)
    }
    assert found == set(ENTRYPOINTS)


def test_installer_surface_has_no_placeholder_urls() -> None:
    """No documented/executable installer path contains a placeholder URL."""
    offenders: list[str] = []
    for path in SURFACE:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO)
        offenders += (f"{rel}: {match.group(0)}" for match in URL_WITH_SLOT.finditer(text))
        offenders += (
            f"{rel}: placeholder token {token!r}" for token in PLACEHOLDER_TOKENS if token in text
        )
    assert not offenders, "placeholder installer content:\n" + "\n".join(offenders)


def test_placeholder_detector_catches_the_removed_shape() -> None:
    """The detector above must flag the literal content that was removed.

    Pins the detector against the regression itself, not only against the
    already-clean tree: both shapes below are quoted verbatim from the
    deleted ``scripts/install-maestro.sh``.
    """
    historical = (
        "#   curl -fsSL https://raw.githubusercontent.com/<org>/maistro-engine"
        "/main/scripts/install-maestro.sh | bash\n"
        '  info "Example: git clone --branch \\"$BRANCH\\" <YOUR_REPO_URL>'
        ' \\"$TARGET\\""\n'
    )
    assert URL_WITH_SLOT.search(historical)
    assert any(token in historical for token in PLACEHOLDER_TOKENS)
