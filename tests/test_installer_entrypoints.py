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

#: Generic unfilled ``<slot>`` argument: any lowercase slot token standing
#: alone between angle brackets. This is the shape of the defect class above
#: under any spelling (e.g. ``git clone <maistro-engine-url>``), so the
#: detector cannot be evaded by renaming the placeholder. Shell redirection
#: (``< file``, ``<<EOF``) never matches: a slot opens with a letter.
GENERIC_SLOT = re.compile(r"(?<![\w<])<[a-z][a-z0-9._-]*>")

#: Angled tokens that are conventional notation rather than an unfilled slot
#: a user would run verbatim, each quoted verbatim from the surface:
#: a usage metavariable in prose/warnings, the ADR naming convention, and the
#: legacy key formats quoted by install.sh's migration hint (bare and inside
#: the ``[...]`` list brackets, shell-escaped as ``API_KEYS=[\"<secret>\"]``).
#: Proof the widened entry strips the real lines lives in the surface test:
#: drop it and install.sh:839/840 fail the scan.
NOTATION_SLOTS = (
    r"-Distro <name>",
    r"ADR-NNN-<slug>\.md",
    r"API_KEYS=\[?\\?[\"'](ops:)?<secret>\\?[\"']\]?",
)

#: Comment prefixes for the executable surfaces; slots inside comments
#: describe third-party syntax and are never run verbatim.
_COMMENT = re.compile(r"^\s*#")


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
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _COMMENT.match(line):
                continue
            for allowed in NOTATION_SLOTS:
                line = re.sub(allowed, "", line)
            offenders += (
                f"{rel}:{lineno}: unfilled slot {match.group(0)}"
                for match in GENERIC_SLOT.finditer(line)
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


def test_slot_detector_catches_renamed_placeholders() -> None:
    """The generic detector must flag slots the historical tokens would miss.

    ``git clone <maistro-engine-url>`` is the #401 shape under a renamed
    placeholder: a paste-verbatim command whose argument is an unfilled
    slot. The token list alone reports the surface as placeholder-free
    here; only the generic detector enforces the invariant.
    """
    renamed = '  info "Example: git clone <maistro-engine-url> "$TARGET""'
    assert not any(token in renamed for token in PLACEHOLDER_TOKENS)
    assert GENERIC_SLOT.search(renamed)
