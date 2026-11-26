"""The shipped temporalio Rust bridge must not link a vulnerable `zip` crate.

The `temporalio` wheel ships the Rust bridge it was built from: a
`bridge/Cargo.lock` plus the compiled `bridge/temporal_sdk_bridge.abi3.so`.
The 1.34.0 wheel pins `zip` 8.6.0 there, and that crate is not merely named
in the manifest -- its code is linked into the shared object, whose
`/root/.cargo/registry/src/.../zip-8.6.0/src/*.rs` paths are inside the
binary. Trivy reads the manifest and reports four findings against the RSI
runner image (CVE-2026-115905 CRITICAL, CVE-2026-115907/115908/115909 HIGH;
the fix versions are 9.0.5 and 9.0.0), so the "Container scan + SBOM + cosign"
gate fails on the image.

The fix is upstream, not cosmetic: 1.35.0 is the first published release whose
wheel bundles a bridge built against `zip` 9.1.2, above every fix version
above. Deleting the `Cargo.lock` would leave the vulnerable code in the
shipped `.so` and hide the finding, so the floor is raised instead and the
lock follows it.

The assertions read the installed wheel and the declared/locked versions, so
they fail on the 1.34.0 state for the intended reason without a network or an
image build.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: CVE-2026-115905 (zip: Critical Parser Differential & Security Control
#: Bypass via Dual-Header Inconsistencies) is fixed in 9.0.5;
#: CVE-2026-115907/115908/115909 are fixed in 9.0.0. The highest fix version
#: is the floor that clears all four.
ZIP_FIXED_VERSION = (9, 0, 5)

#: The first temporalio release whose published wheel bundles a bridge built
#: against a `zip` above ZIP_FIXED_VERSION (1.35.0 bundles zip 9.1.2).
TEMPORALIO_FIXED_RELEASE = (1, 35, 0)

#: A `[[package]]` block of a Rust lockfile.
_CARGO_PACKAGE = re.compile(r'name = "(?P<name>[^"]+)"\nversion = "(?P<version>[^"]+)"')

#: The crate path a compiled Rust binary carries for a linked dependency:
#: `/root/.cargo/registry/src/index.crates.io-<hash>/<crate>-<version>/src/...`.
_LINKED_CRATE = re.compile(rb"/(?P<crate>[a-z0-9_]+)-(?P<version>\d+\.\d+\.\d+)/")


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _cargo_lock_versions(text: str, crate: str) -> list[str]:
    return [
        match.group("version")
        for match in _CARGO_PACKAGE.finditer(text)
        if match.group("name") == crate
    ]


def _linked_crate_versions(binary: bytes, crate: str) -> set[str]:
    return {
        match.group("version").decode()
        for match in _LINKED_CRATE.finditer(binary)
        if match.group("crate") == crate.encode()
    }


def _bridge_dir() -> Path:
    spec = importlib.util.find_spec("temporalio")
    assert spec is not None and spec.origin, "temporalio is not installed in this environment"
    return Path(spec.origin).parent / "bridge"


def _declared_floor() -> tuple[int, ...]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = next(
        requirement
        for requirement in pyproject["project"]["dependencies"]
        if requirement.startswith("temporalio")
    )
    match = re.fullmatch(r"temporalio>=(?P<version>[\d.]+)", declared)
    assert match, f"unexpected temporalio requirement: {declared!r}"
    return _version_tuple(match.group("version"))


def _locked_version() -> tuple[int, ...]:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(entry for entry in lock["package"] if entry["name"] == "temporalio")
    return _version_tuple(package["version"])


def test_declared_floor_is_at_least_the_first_fixed_release() -> None:
    assert _declared_floor() >= TEMPORALIO_FIXED_RELEASE, (
        "temporalio's floor must be at least the first release whose published "
        "wheel bundles a Rust bridge built against a fixed zip; 1.34.0 ships "
        "zip 8.6.0, which the container-scan gate reports against the RSI "
        "runner image"
    )


def test_locked_release_satisfies_the_declared_floor() -> None:
    assert _locked_version() >= _declared_floor()


def test_shipped_bridge_manifest_pins_no_vulnerable_zip() -> None:
    cargo_lock = _bridge_dir() / "Cargo.lock"
    assert cargo_lock.exists(), "the installed temporalio wheel ships no bridge/Cargo.lock"
    versions = _cargo_lock_versions(cargo_lock.read_text(encoding="utf-8"), "zip")
    assert versions, "the bridge manifest names no zip crate"
    for version in versions:
        assert _version_tuple(version) >= ZIP_FIXED_VERSION, (
            f"the temporalio bridge manifest pins zip {version}, below the fixed "
            f"version {'.'.join(str(part) for part in ZIP_FIXED_VERSION)}"
        )


def test_shipped_bridge_binary_links_no_vulnerable_zip() -> None:
    binaries = sorted(_bridge_dir().glob("temporal_sdk_bridge*.so"))
    assert binaries, "the installed temporalio wheel ships no compiled Rust bridge"
    for binary in binaries:
        versions = _linked_crate_versions(binary.read_bytes(), "zip")
        # Not vacuous: the crate path must be found, or the check below would
        # pass on a binary that links no zip at all -- and would also pass on a
        # binary whose paths stopped being readable.
        assert versions, (
            f"{binary.name} exposes no linked zip crate path; the manifest check "
            "is then the only signal, and this assertion must be revisited"
        )
        for version in versions:
            assert _version_tuple(version) >= ZIP_FIXED_VERSION, (
                f"{binary.name} links zip {version}, below the fixed version "
                f"{'.'.join(str(part) for part in ZIP_FIXED_VERSION)}"
            )


def test_vulnerable_bridge_state_is_rejected() -> None:
    """The negative control: the 1.34.0 wheel's manifest and binary are rejected."""
    vulnerable_manifest = (
        '[[package]]\nname = "zip"\nversion = "8.6.0"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
    )
    versions = _cargo_lock_versions(vulnerable_manifest, "zip")
    assert versions == ["8.6.0"]
    for version in versions:
        assert _version_tuple(version) < ZIP_FIXED_VERSION

    vulnerable_binary = (
        b"/root/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/zip-8.6.0/src/read.rs"
    )
    linked = _linked_crate_versions(vulnerable_binary, "zip")
    assert linked == {"8.6.0"}
    for version in linked:
        assert _version_tuple(version) < ZIP_FIXED_VERSION


def test_unrelated_crates_are_not_matched_as_zip() -> None:
    """`gzip`/`zips` must not be read as the `zip` crate."""
    binary = b"/root/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/gzip-1.3.1/src/lib.rs"
    assert _linked_crate_versions(binary, "zip") == set()
