"""The research image's browser surface must be buildable and scanner-clean.

#2304 round 8: the advisory lock bumps moved playwright 1.64.0 -> 1.65.2.
Its bundled Node driver (v26.13.1) links ``libatomic.so.1`` -- the 1.64.0
driver did not -- and on the then-bookworm base nothing else in the apt
closure pulled ``libatomic1`` in, so ``python -m playwright install
chromium`` died with ``error while loading shared libraries:
libatomic.so.1`` before the browser ever downloaded (CI jobs 133267675340
"Container scan + SBOM + cosign" and 133270207586 "docker-build" at head
``094944a81``, 2026-11-16). That round installed ``libatomic1`` explicitly.

Develop has since moved this image's base to the floating
``python:3.12-slim`` digest, which resolves to Debian trixie, and there
``libglib2.0-0t64`` -- in the image through the Chromium X-stack below --
depends on ``libatomic1``, so the driver's ``libatomic.so.1`` is satisfied
transitively. Measured 2026-11-25 against the pinned base digest
(``docker run`` + this stage's exact apt list): ``libatomic1`` 14.2.0-19
installed as an auto (dependency) package, ``apt-cache rdepends
--installed libatomic1`` naming ``libglib2.0-0t64``, while the fresh base
does not ship the library; ``ldd`` on the locked playwright 1.65.2 wheel's
``driver/node`` confirms it still needs ``libatomic.so.1``. The explicit
install line is therefore gone, and the build gate (docker-build /
containers) remains the hard guard: re-pin a bookworm base and the driver
exit-127s there again. These tests hold the Chromium runtime stack itself
closed instead -- it is the image's reason to exist, not an implementation
detail of one libatomic resolution.

Round 9's driver-node swap -- network tarball fetch with a sha256 assert +
``PLAYWRIGHT_NODEJS_PATH`` + bundled-binary deletion -- has been superseded
by develop's narrower overlay (#2431 lineage): playwright 1.65.2 already
ships the fixed Node v26.13.1, and only patchright 1.64.4 still bundles the
grype-flagged v24.22.1 (seven HIGHs: CVE-2026-126051/123865/123866/123874/
123863/123872/123864, fixed in 24.22.3/26.13.1; no newer patchright wheel
on PyPI as of 2026-11-20). The image now copies a single ``node`` binary
out of the digest-pinned ``node:26.13.1-bookworm-slim`` donor image and
overwrites patchright's ``driver/node`` with it, asserting the resulting
version in-build so a moved wheel layout or a donor/wheel version mismatch
fails the build instead of shipping the vulnerable binary again. The tests
below hold that overlay closed.
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

#: The donor image whose ``/usr/local/bin/node`` replaces patchright's
#: bundled driver binary, and the version its overlay must assert.
_DONOR_NODE_VERSION = "26.13.1"

#: The Chromium runtime stack the production-apt stage must name explicitly.
#: These are the browser-surface packages this image has carried since the
#: split from the main API image; on the trixie base their closure is also
#: what transitively provides ``libatomic1`` (via ``libglib2.0-0t64``) for
#: playwright's bundled driver.
_CHROMIUM_RUNTIME_STACK = (
    "libnss3",
    "libnspr4",
    "libatk1.0-0",
    "libatk-bridge2.0-0",
    "libcups2",
    "libdrm2",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libpango-1.0-0",
    "libcairo2",
    "libasound2",
    "libatspi2.0-0",
    "fonts-liberation",
)


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


def _locked_version(package_name: str) -> str | None:
    """The locked version of ``package_name``, or None when it leaves the lock."""
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    for package in lock["package"]:
        if package["name"] == package_name:
            return package["version"]
    return None


def _lock_playwright_version() -> str | None:
    return _locked_version("playwright")


def _lock_patchright_version() -> str | None:
    return _locked_version("patchright")


def _missing_chromium_stack(packages: set[str]) -> list[str]:
    return [p for p in _CHROMIUM_RUNTIME_STACK if p not in packages]


def test_production_apt_keeps_the_chromium_runtime_stack() -> None:
    """The regression surface behind the old libatomic1 line, generalized.

    The stage must keep naming the browser runtime packages explicitly:
    they are why this image exists (the RESEARCH browser tool runs here;
    the main API image is Wolfi/browser-free), and their closure is what
    transitively provides libatomic1 -- playwright 1.65.2's bundled Node
    driver links libatomic.so.1 -- on the current trixie base. Dropping
    any of them breaks Chromium at runtime or, through the glib chain,
    the driver itself, without failing anything but the built image.
    """
    missing = _missing_chromium_stack(_apt_install_packages())
    assert not missing, f"production-apt lost Chromium runtime packages: {missing}"


def test_playwright_in_lock_requires_the_chromium_runtime_stack() -> None:
    """The coupling: playwright in the lock implies the browser runtime floor.

    Vacuously satisfied if playwright leaves the lock; until then every
    package in the stack must stay an explicit install requirement of the
    security-patch stage, so a base or dependency-list change cannot
    silently ship an image whose browser tool cannot start.
    """
    if _lock_playwright_version() is not None:
        missing = _missing_chromium_stack(_apt_install_packages())
        assert not missing, f"playwright ships in the lock but production-apt lost: {missing}"


# --- the patchright driver-node overlay (develop's #2431 lineage) ---
# --- supersedes round 9's tarball fetch + PLAYWRIGHT_NODEJS_PATH swap ---


def _donor_from_line() -> str:
    match = re.search(r"^FROM node:\S+ AS node-driver-patch$", _dockerfile(), re.MULTILINE)
    assert match, "the node-driver-patch donor stage must exist"
    return match.group(0)


def _overlay_run_body() -> str:
    """The heredoc body of the RUN that overlays patchright's driver node."""
    match = re.search(
        r"COPY --from=node-driver-patch /usr/local/bin/node \S+\n"
        r"RUN python - <<'PY'\n(?P<body>.*?)\nPY\n",
        _dockerfile(),
        re.DOTALL,
    )
    assert match, "the driver-node overlay (COPY + heredoc RUN) must exist"
    return match.group("body")


def test_patchright_driver_node_is_overlaid_from_the_pinned_donor() -> None:
    """The regression: patchright 1.64.4 bundles grype-flagged Node v24.22.1.

    The seven HIGHs fixed in 24.22.3/26.13.1 ship inside the published
    image unless the driver binary is replaced. playwright 1.65.2 already
    bundles the fixed v26.13.1, so the image only overwrites patchright's
    driver/node -- with the single ``node`` binary copied out of the
    bookworm-slim donor (Debian slim runtime, so the musl alpine build is
    the wrong ABI) -- and asserts the resulting version in-build, so a
    moved wheel layout (driver path changed) or a donor/wheel version
    mismatch fails the build instead of shipping the vulnerable binary
    again.
    """
    from_line = _donor_from_line()
    assert f"FROM node:{_DONOR_NODE_VERSION}-bookworm-slim@" in from_line, (
        "the donor must stay the bookworm (glibc) node image at the annotated version"
    )
    body = _overlay_run_body()
    assert "import patchright" in body, "the overlay must target patchright's driver"
    assert '"driver" / "node"' in body, "the overlay must overwrite driver/node, not add a copy"
    assert "shutil.copy2" in body and "os.chmod" in body, "the overlay must install the binary"
    assert f'ver != "v{_DONOR_NODE_VERSION}"' in body, (
        "the overlay must refuse to finish unless node -v reports the donor version"
    )


def test_donor_node_runtime_is_digest_pinned_and_version_asserted() -> None:
    """Integrity rides the donor image digest, not a tarball hash.

    Round 9 fetched the Node tarball over the network and asserted its
    sha256; the overlay instead takes the binary from a FROM whose digest
    is immutable, so the pin *is* the checksum. Both legs must hold: the
    donor FROM carries a ``@sha256:`` index digest, and the overlay's
    version assertion matches the donor version -- a donor bump that
    forgets the assertion (or vice versa) would ship an unverified swap.
    """
    from_line = _donor_from_line()
    assert re.search(r"@sha256:[0-9a-f]{64}", from_line), (
        "the node donor image must be digest-pinned, not tag-floating"
    )
    body = _overlay_run_body()
    assert "subprocess.check_output" in body and f'"v{_DONOR_NODE_VERSION}"' in body, (
        "the overlay must verify the installed driver node's version in-build"
    )


def test_patchright_in_lock_requires_the_driver_overlay() -> None:
    """The coupling: patchright in the lock implies the overlay exists.

    If patchright ships in this image, its bundled Node ships with it
    unless the overlay replaces it; losing any leg (donor stage, COPY,
    in-build version assertion) re-exposes the grype findings without
    failing the build, so it must red here instead. Vacuously satisfied if
    patchright leaves the lock. Symmetric guard: playwright staying in the
    lock keeps the browser-install step and its world-readable
    PLAYWRIGHT_BROWSERS_PATH (the non-root runtime user must be able to
    find Chromium).
    """
    text = _dockerfile()
    if _lock_patchright_version() is not None:
        _donor_from_line()
        assert "COPY --from=node-driver-patch /usr/local/bin/node" in text
        assert f'ver != "v{_DONOR_NODE_VERSION}"' in text
    if _lock_playwright_version() is not None:
        assert "RUN python -m playwright install chromium" in text
        assert "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright" in text
