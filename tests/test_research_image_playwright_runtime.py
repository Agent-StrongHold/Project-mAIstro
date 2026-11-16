"""The research image's browser surface must carry playwright's libatomic runtime.

#2304 round 8: the advisory lock bumps moved playwright 1.64.0 -> 1.65.2.
Its bundled Node driver (v26.13.1) links ``libatomic.so.1`` -- the 1.64.0
driver did not -- and nothing else in the image's apt closure pulls
``libatomic1`` in, so ``python -m playwright install chromium`` died with
``error while loading shared libraries: libatomic.so.1`` (CI jobs
133267675340 "Container scan + SBOM + cosign" and 133270207586
"docker-build" at head ``094944a81``, 2026-11-16) before the browser ever
downloaded. The fix names ``libatomic1`` explicitly in the ``production-apt``
stage, the same "installed explicitly, not left to dependency resolution"
pattern the libbrotli1 entry above it documents.

These tests hold that structure closed: the apt stage must name libatomic1
whenever the lock ships playwright into this image, so a playwright bump or
re-introduction cannot silently red the image build (or worse, ship a
browser tool whose driver cannot start at runtime) without a red test here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.research"
UV_LOCK = ROOT / "uv.lock"

#: `FROM <ref> AS <stage>` -- the same shape every stage declaration takes.
_STAGE_FROM = re.compile(r"^FROM \S+ AS (?P<stage>\S+)$", re.MULTILINE)


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _production_apt_body() -> str:
    """The production-apt stage's body: its FROM line to the next FROM."""
    text = _dockerfile()
    matches = list(_STAGE_FROM.finditer(text))
    starts = [m for m in matches if m.group("stage") == "production-apt"]
    assert len(starts) == 1, f"expected exactly one production-apt stage, got {len(starts)}"
    start = starts[0]
    next_from = min((m.start() for m in matches if m.start() > start.start()), default=len(text))
    return text[start.start() : next_from]


def _apt_install_packages() -> set[str]:
    """The package names in the stage's `apt-get install` continuation block."""
    body = _production_apt_body()
    install = re.search(
        r"apt-get install -y --no-install-recommends \\\n(?P<block>(?:.+\n)+?)    && apt-get",
        body,
    )
    assert install, "production-apt must keep its apt-get install block"
    # Strip line continuations and inline-free package tokens: names only,
    # one per whitespace token, with trailing `\` removed.
    tokens = install.group("block").replace("\\\n", " ").split()
    return {t for t in tokens if "/" not in t and "=" not in t}


def _lock_playwright_version() -> str | None:
    """The locked playwright version, or None when it leaves the lock."""
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    for package in lock["package"]:
        if package["name"] == "playwright":
            return package["version"]
    return None


def test_production_apt_names_libatomic1() -> None:
    """The regression: playwright's Node driver needs libatomic.so.1 at startup.

    The stage must name the package explicitly -- the same posture as the
    libbrotli1 entry -- because no other apt dependency of this image pulls
    it in transitively. Without it the playwright driver cannot even start
    to download Chromium (CI: containers + docker-build, head 094944a81).
    """
    assert "libatomic1" in _apt_install_packages()


def test_playwright_in_lock_requires_libatomic1_in_the_image() -> None:
    """The coupling: playwright in the browser surface implies libatomic1.

    Every playwright release to date bundles a Node driver whose ELF links
    libatomic.so.1 on glibc systems, and the research image is the only
    shipped image that installs playwright (core's `browser` extra). If
    playwright ever leaves the lock the requirement is vacuous and this test
    stops demanding the package; until then the apt stage must keep naming
    it, so a playwright bump cannot silently reintroduce the exit-127 build.
    """
    if _lock_playwright_version() is not None:
        assert "libatomic1" in _apt_install_packages()
