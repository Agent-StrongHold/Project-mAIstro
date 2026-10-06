#!/usr/bin/env python3
"""The reference gallery's shared publish workflow (#980, M9-J2).

One command takes this repository from sources to a platform-consumable
catalog snapshot:

1. **derive** the publisher's Ed25519 signing identity from the fixed fixture
   seed and verify it against ``keys/reference-publisher.pub`` — the gallery
   is a fixture, so the seed is documented and committed, and a key file that
   disagrees with the seed fails the publish instead of silently re-keying
   the catalog. A real publisher generates and guards a private key; every
   other step is identical.
2. **build** every package under ``packages/`` into a wheel (``uv build``);
3. **bind** each package's ``manifest.json`` to its built artifact: the
   manifest source never names a digest (it cannot — the digest describes a
   wheel that does not exist until the manifest is inside its final form);
   publishing computes the wheel's SHA-256 and size and writes the
   ``artifact`` claim, producing the exact bytes the platform's
   ``inspect_manifest`` validates and the manifest digest the signature
   covers;
4. **sign** the canonical install payload — the same byte string
   ``maistro.extensions.verify_package_signature`` checks against the
   *registered* publisher key at install time;
5. **emit** ``catalog.json``: one entry per package (identity, signature,
   declared dependencies, final manifest, artifact filename) plus the
   snapshot digest over the canonical entry set. Deterministic: the same
   sources always produce byte-identical output, which is what makes the
   lock resolution downstream reproducible.

Usage (from the repository root or anywhere):

    uv run python extensions/reference-gallery/tools/publish.py --out-dir <dir>

The output directory receives ``catalog.json`` and ``artifacts/*.whl``.
Nothing in the gallery tree is mutated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GALLERY_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = GALLERY_ROOT / "packages"
KEY_FILE = GALLERY_ROOT / "keys" / "reference-publisher.pub"

#: The fixture signing seed. Committed on purpose: this identity proves the
#: signing workflow, it does not protect anything, and a deterministic seed
#: makes the published catalog reproducible byte-for-byte. Production
#: publishers replace exactly this step (generate + guard a real key) and
#: change nothing else.
SEED_PHRASE = (
    "maistro reference gallery fixture signing seed (#980) — "
    "proof-of-workflow identity, not a production key"
)

#: The platform's canonical signature payload, mirrored from
#: ``maistro.extensions.types.canonical_install_payload`` (which the gallery,
#: as an external repository, cannot import). Version-tagged and
#: newline-delimited there so fields cannot run together; kept byte-identical
#: here so the platform verifies what this tool signed.
SIGNATURE_PAYLOAD_VERSION = "maistro-extension-install:v1"

CATALOG_FORMAT = "maistro-extension-catalog:v1"
PUBLISHER_ID = "gallery"
SOURCE_LABEL = "reference-gallery:catalog"

_SUBPROCESS_TIMEOUT_S = 600


class PublishError(RuntimeError):
    """A packaging, manifest, or signing failure of the publish workflow."""


def canonical_json(obj: object) -> bytes:
    """The one JSON serialization every digest in the catalog is computed over.

    Sorted keys, no whitespace, UTF-8. Both the publisher and the consumer
    must canonicalize identically or no digest can ever agree; this function
    is the agreement.
    """

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256, the only digest algorithm the platform accepts."""
    return hashlib.sha256(data).hexdigest()


def canonical_install_payload(identity: dict[str, str]) -> bytes:
    """The exact bytes a publisher signs for one package identity."""

    return "\n".join(
        (
            SIGNATURE_PAYLOAD_VERSION,
            identity["extension_name"],
            identity["semantic_version"],
            identity["package_sha256"],
            identity["manifest_sha256"],
        )
    ).encode("utf-8")


def publisher_private_key():  # type: ignore[no-untyped-def]
    """Derive the fixture publisher's Ed25519 private key from the seed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = hashlib.sha256(SEED_PHRASE.encode("utf-8")).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def publisher_public_key_hex() -> str:
    """The hex public key the fixture seed implies."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = publisher_private_key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key.hex()


def check_key_file() -> None:
    """Fail loudly if the committed key file and the seed disagree."""
    if not KEY_FILE.is_file():
        raise PublishError(f"publisher key file missing: {KEY_FILE}")
    committed = KEY_FILE.read_text(encoding="utf-8").strip()
    derived = publisher_public_key_hex()
    if committed != derived:
        raise PublishError(
            "keys/reference-publisher.pub does not match the documented fixture seed; "
            "re-derive it with tools/publish.py rather than hand-editing either side"
        )


def build_wheel(package_dir: Path, out_dir: Path) -> Path:
    """Build one package into ``out_dir`` and return the wheel path."""
    before = {p.name for p in out_dir.glob("*.whl")}
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    result = subprocess.run(
        ("uv", "build", "--wheel", "--out-dir", str(out_dir)),
        cwd=package_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise PublishError(
            f"building {package_dir.name} failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    produced = sorted(p for p in out_dir.glob("*.whl") if p.name not in before)
    if len(produced) != 1:
        raise PublishError(
            f"building {package_dir.name} produced {len(produced)} wheels, expected exactly one"
        )
    return produced[0]


def load_manifest_source(package_dir: Path) -> dict[str, object]:
    """Read one package's manifest source (no artifact claim yet)."""
    source = package_dir / "manifest.json"
    if not source.is_file():
        raise PublishError(f"{package_dir.name} ships no manifest.json; it cannot be published")
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"{package_dir.name}/manifest.json is unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PublishError(f"{package_dir.name}/manifest.json must be a JSON object")
    if "artifact" in manifest:
        raise PublishError(
            f"{package_dir.name}/manifest.json carries an artifact claim; the artifact "
            "digest is bound at publish time, never authored (a manifest cannot know "
            "the digest of the wheel it describes)"
        )
    return manifest


def build_catalog(out_dir: Path) -> dict[str, object]:
    """Run the full workflow into ``out_dir`` and return the catalog document."""
    check_key_file()
    package_dirs = sorted(p for p in PACKAGES_DIR.iterdir() if (p / "pyproject.toml").is_file())
    if not package_dirs:
        raise PublishError(f"no publishable packages under {PACKAGES_DIR}")

    artifacts_dir = out_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    signing_key = publisher_private_key()

    entries: list[dict[str, object]] = []
    for package_dir in package_dirs:
        manifest = load_manifest_source(package_dir)
        wheel = build_wheel(package_dir, artifacts_dir)
        wheel_bytes = wheel.read_bytes()

        # `uv build` drops a .gitignore next to its output; it is build
        # furniture, not a published artifact.
        uv_gitignore = artifacts_dir / ".gitignore"
        if uv_gitignore.is_file():
            uv_gitignore.unlink()

        manifest["artifact"] = {"sha256": sha256_hex(wheel_bytes), "size": len(wheel_bytes)}
        manifest_bytes = canonical_json(manifest)

        identity = {
            "extension_name": str(manifest["id"]),
            "semantic_version": str(manifest["version"]),
            "package_sha256": manifest["artifact"]["sha256"],
            "manifest_sha256": sha256_hex(manifest_bytes),
        }
        dependencies = [
            {"target": str(dep["id"]), "range_text": str(dep["range"]), "required": True}
            for dep in manifest.get("dependencies", [])
        ]
        entries.append(
            {
                "identity": identity,
                "source": SOURCE_LABEL,
                "publisher_id": PUBLISHER_ID,
                "signature": signing_key.sign(canonical_install_payload(identity)).hex(),
                "dependencies": dependencies,
                "manifest": manifest,
                "manifest_bytes": manifest_bytes.decode("utf-8"),
                "artifact_file": f"artifacts/{wheel.name}",
            }
        )

    snapshot = {
        "format": CATALOG_FORMAT,
        "publisher": PUBLISHER_ID,
        "signing_public_key": publisher_public_key_hex(),
        "entries": entries,
    }
    catalog = {
        **snapshot,
        "catalog_snapshot_sha256": sha256_hex(canonical_json(snapshot)),
    }
    (out_dir / "catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True, help="catalog output directory")
    args = parser.parse_args(argv)
    out_dir = args.out_dir.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="gallery-publish-") as tmp:
            staging = Path(tmp) / "publish"
            catalog = build_catalog(staging)
            # Stage-then-move: a failed build must not leave a half-written
            # catalog (or stale wheels from an earlier run) behind.
            out_dir.mkdir(parents=True, exist_ok=True)
            for stale in out_dir.glob("*"):
                if stale.is_dir():
                    shutil.rmtree(stale)
                else:
                    stale.unlink()
            shutil.move(str(staging / "catalog.json"), str(out_dir / "catalog.json"))
            shutil.move(str(staging / "artifacts"), str(out_dir / "artifacts"))
    except PublishError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    names = sorted(str(entry["identity"]["extension_name"]) for entry in catalog["entries"])
    print(f"published {len(catalog['entries'])} extension(s) to {out_dir}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
