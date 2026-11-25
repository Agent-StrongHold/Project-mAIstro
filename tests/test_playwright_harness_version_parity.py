"""The e2e harness's npm Playwright version must equal the base-image version.

The ``mcr.microsoft.com/playwright:<version>-noble`` image ships exactly the
browser revisions that version's playwright-core expects, and any other npm
version of ``@playwright/test`` fails every browser launch with
"Executable doesn't exist" -- deterministically, and only at runtime inside
ci.yml's ``hive-conductor-e2e-ui`` job. The raw dependabot head of #2444
bumped the Dockerfile's FROM line to v1.65.1-noble while the build-time pin
``@playwright/test@1.64.1`` stayed behind (playwright-core 1.64.1 wants
chromium-1248; the image ships chromium-1255), so a change that only moved a
Docker image tag red-handedly failed the whole UI suite.

``scripts/check-image-pins.py`` closes the digest against the registry, and
``tests/test_check_image_pins.py`` closes the registry against the tree;
neither looks at the npm install. This suite closes the harness npm pin (and
the repo-side e2e manifest/lockfile annotations) against the image tag, so
the next Playwright version bump cannot land half-done.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "packages/hive-conductor/tests/Dockerfile.playwright"
E2E_DIR = REPO_ROOT / "packages/hive-conductor/tests/e2e"

# `FROM mcr.microsoft.com/playwright:vX.Y.Z-noble@sha256:<64 hex>` -- the
# digest-pinned base (the digest itself is check-image-pins.py's contract).
IMAGE_REF = re.compile(
    r"^FROM mcr\.microsoft\.com/playwright:v(\d+\.\d+\.\d+)-noble@sha256:[0-9a-f]{64}\s*$",
    re.MULTILINE,
)
# The build-time npm pin inside the harness `npm install`.
NPM_PIN = re.compile(r"@playwright/test@(\d+\.\d+\.\d+)\b")


def _image_version() -> str:
    refs = IMAGE_REF.findall(DOCKERFILE.read_text(encoding="utf-8"))
    assert refs, (
        "Dockerfile.playwright lost its mcr.microsoft.com/playwright base "
        "reference entirely; the harness parity contract has nothing to anchor"
    )
    assert len(refs) == 1, (
        f"expected exactly one playwright base image reference, found {refs}; "
        "which one is the harness built from is now ambiguous"
    )
    return refs[0]


def _harness_npm_versions() -> list[str]:
    pins = NPM_PIN.findall(DOCKERFILE.read_text(encoding="utf-8"))
    assert pins, "Dockerfile.playwright installs no @playwright/test npm pin"
    return pins


def test_dockerfile_npm_pin_equals_the_base_image_version() -> None:
    """The build-time `@playwright/test` pin must equal the image tag version.

    This is the #2444 regression: the FROM line moved to v1.65.1-noble while
    the npm pin stayed at 1.64.1, and the mismatch only surfaced as e2e-ui's
    "Executable doesn't exist" failures inside the compose run.
    """
    image = _image_version()
    pins = _harness_npm_versions()
    assert len(set(pins)) == 1, (
        f"Dockerfile.playwright pins conflicting @playwright/test versions {pins}; "
        "one npm install must carry exactly one version"
    )
    assert pins[0] == image, (
        f"@playwright/test@{pins[0]} does not match the "
        f"mcr.microsoft.com/playwright:v{image}-noble base. The image ships "
        "exactly the browser revisions its own version's playwright-core "
        "expects, so every other npm version fails browser launch at runtime "
        "(#2444: image 1.65.1 + npm 1.64.1 -> chromium-1248 not found in an "
        "image shipping chromium-1255). Move the npm pin in the same change "
        "as the FROM line."
    )


def test_e2e_package_manifest_equals_the_harness_pin() -> None:
    """The repo-side e2e manifest documents the same Playwright version."""
    image = _image_version()
    manifest = json.loads((E2E_DIR / "package.json").read_text(encoding="utf-8"))
    declared = manifest["dependencies"]["@playwright/test"]
    assert declared == image, (
        f"packages/hive-conductor/tests/e2e/package.json declares "
        f"@playwright/test {declared} while the harness image/pin is "
        f"{image}; keep the manifest annotation in lockstep"
    )


def test_e2e_lockfile_equals_the_harness_pin() -> None:
    """The e2e lockfile's installed @playwright/test matches the image."""
    image = _image_version()
    lock = json.loads((E2E_DIR / "package-lock.json").read_text(encoding="utf-8"))
    installed = lock["packages"]["node_modules/@playwright/test"]["version"]
    assert installed == image, (
        f"packages/hive-conductor/tests/e2e/package-lock.json installs "
        f"@playwright/test {installed} while the harness image/pin is "
        f"{image}; regenerate the lockfile (`npm install --package-lock-only` "
        "in packages/hive-conductor/tests/e2e) with the bump"
    )
