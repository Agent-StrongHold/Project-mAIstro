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

Round 9 extends the same surface: the drivers' *bundled* Node binaries
(playwright 1.65.2 -> v26.13.1, patchright 1.64.1 -> v24.21.0, both measured
from the locked wheels) carried the grype HIGH/CRITICAL findings that red
the container-scan gate, so the image swaps them for a checksum-pinned
system Node reached through ``PLAYWRIGHT_NODEJS_PATH`` and deletes the
bundled binaries. Three further tests below hold that swap closed.
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


# --- round 9: the drivers' bundled Node binaries are replaced by a ---
# --- checksum-pinned system Node reached through PLAYWRIGHT_NODEJS_PATH ---

_NODE_TARBALL_URL = "https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz"
_NODE_TARBALL_SHA256 = "6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6"


def test_bundled_driver_node_binaries_are_dropped_for_a_pinned_system_node() -> None:
    """The round-9 regression: the wheels' bundled Node must not ship.

    playwright 1.65.2 bundles Node v26.13.1 and patchright 1.64.1 bundles
    Node v24.21.0 (both measured from the locked wheels); those binaries
    carried the grype HIGH/CRITICAL findings that red the container-scan
    gate inside a *published* image. Both driver binaries must be deleted
    and PLAYWRIGHT_NODEJS_PATH must point at the system Node that replaces
    them (both packages consult that variable before driver/node). npm's
    vendored tree goes with it: nothing in the image uses npm at runtime
    and its bundled dependencies are pure scan surface.
    """
    text = _dockerfile()
    assert _NODE_TARBALL_URL in text
    assert f'expected = "{_NODE_TARBALL_SHA256}"' in text
    assert "ENV PLAYWRIGHT_NODEJS_PATH=/usr/local/bin/node" in text
    rm = re.search(
        r"RUN rm -f (?P<paths>(?:[^\n]*driver/node[^\n]*\\\n)*[^\n]*driver/node[^\n]*)", text
    )
    assert rm, "the driver-node removal RUN must exist"
    paths = rm.group("paths")
    assert "playwright/driver/node" in paths
    assert "patchright/driver/node" in paths
    assert "/usr/local/lib/node_modules/npm" in text


def test_system_node_tarball_fetch_verifies_the_checksum() -> None:
    """The Node tarball fetch must be checksum-verified, not trusted.

    The same hash-pinning posture as the venv install (``--require-hashes``)
    and the patched age/dockercli builds: a dist URL alone is not an
    integrity guarantee, so the downloader must assert the tarball's sha256
    against a literal expected digest before extracting anything.
    """
    text = _dockerfile()
    fetch = re.search(
        r"import hashlib.*?assert hashlib\.sha256\(data\)\.hexdigest\(\) == expected",
        text,
        re.DOTALL,
    )
    assert fetch, "the node downloader must verify the tarball sha256"


def test_playwright_in_lock_requires_the_node_runtime_swap() -> None:
    """The coupling: playwright in the lock implies the node swap exists.

    If playwright ships in this image, its bundled Node ships with it
    unless the swap block removes it. Losing any leg of the swap (pinned
    fetch, PLAYWRIGHT_NODEJS_PATH override, driver-binary removal, npm
    pruning) re-exposes the grype findings without failing the build, so
    it must red here instead. Vacuously satisfied if playwright leaves
    the lock.
    """
    if _lock_playwright_version() is not None:
        text = _dockerfile()
        assert _NODE_TARBALL_URL in text
        assert "ENV PLAYWRIGHT_NODEJS_PATH=/usr/local/bin/node" in text
        assert "patchright/driver/node" in text
        assert "/usr/local/lib/node_modules/npm" in text
