"""External `COPY --from=` sources are covered by the retrying pre-pull (#204).

`tests/test_prepull_base_images.py` holds the `FROM` half of the coverage
contract. This file holds the other half: an image a Dockerfile reaches through
`COPY --from=<external image>` is pulled exactly like a base image, and is
missed by the pre-pull step just as silently.

The shipped case this file was written for has since changed shape, and the
change is the reason the assertions below are derived rather than named. The
`docker` CLI used to arrive as `COPY --from=docker:29-cli /usr/local/bin/docker`
— an unpinned external binary image. It is now built from source in a
digest-pinned `golang` stage (`dockerclibuild`) because the published 29-cli
binary embedded a Go stdlib Trivy reported HIGHs against. A test that asserted
the literal string `docker:29-cli` went red on that repair while the property it
existed to protect — the image the CLI actually comes from is fetched under
retry — was still true of its replacement. So these tests resolve the reference
through the Dockerfile instead of hardcoding it, and fail on the property.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepull-base-images.sh"

#: The Dockerfiles `docker-build` gives the pre-pull step (ci.yml). This is the
#: set a `--list` omission would silently stop retrying, so it is the set the
#: coverage assertion below is scoped to. `Dockerfile.research` is built by
#: security.yml through `buildx-build-retry.sh`, whose own retry covers it, and
#: is therefore asserted for provenance only — never against this list.
PREPULLED_DOCKERFILES = (
    "Dockerfile",
    "packages/hive-conductor/Dockerfile",
    "Dockerfile.rsi-runner",
)

#: Every shipped Dockerfile that installs the `docker` CLI into the final image.
DOCKER_CLI_DOCKERFILES = ("Dockerfile", "Dockerfile.research")

_FROM_RE = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)
_COPY_RE = re.compile(r"^\s*COPY\s+(?P<rest>.+?)\s*$", re.IGNORECASE)


def _list_images(*dockerfiles: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--list", *(str(path) for path in dockerfiles)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _tokens(rest: str) -> list[str]:
    """Instruction operands, with `--platform=`/`--chown=` flags dropped."""
    return [token for token in rest.split() if not token.startswith("--")]


def _stages_and_images(text: str) -> tuple[dict[str, str], list[str]]:
    """Map each stage alias to its base image, and list every `COPY --from` ref.

    Stage *indices* resolve too: Docker numbers stages from 0, so `COPY
    --from=0` names the first `FROM`. Those are recorded under their decimal
    string so a reference to one is recognised as internal rather than mistaken
    for a pullable image.
    """
    aliases: dict[str, str] = {}
    copies: list[str] = []
    index = 0
    for line in text.splitlines():
        from_match = _FROM_RE.match(line)
        if from_match is not None:
            tokens = _tokens(from_match.group("rest"))
            image = tokens[0]
            lowered = [token.lower() for token in tokens]
            if "as" in lowered:
                position = lowered.index("as")
                if position + 1 < len(tokens):
                    aliases[tokens[position + 1].lower()] = image
            aliases[str(index)] = image
            index += 1
            continue
        copy_match = _COPY_RE.match(line)
        if copy_match is not None:
            for token in copy_match.group("rest").split():
                if token.startswith("--from="):
                    copies.append(token.removeprefix("--from="))
    return aliases, copies


def test_external_copy_source_is_pre_pulled(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.13 AS builder\n"
        "COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker\n"
        "COPY --from=builder /app /app\n"
        "COPY --from=0 /other /other\n",
        encoding="utf-8",
    )

    result = _list_images(dockerfile)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["docker:29-cli", "python:3.13"]


def test_every_shipped_copy_from_source_is_covered_by_retry() -> None:
    """No external `COPY --from=` in a pre-pulled Dockerfile escapes the retry.

    A stage reference is not an image and must not be demanded of the list; an
    external reference is fetched by `docker build` whether or not the pre-pull
    step covered it, so omitting one costs nothing until the next registry blip
    turns into a red build nobody can explain.
    """
    result = _list_images(*PREPULLED_DOCKERFILES)
    assert result.returncode == 0, result.stderr
    pulled = set(result.stdout.split())

    externals: dict[str, list[str]] = {}
    for name in PREPULLED_DOCKERFILES:
        aliases, copies = _stages_and_images((ROOT / name).read_text())
        for ref in copies:
            if ref.lower() in aliases or ref.lower() == "scratch":
                continue
            externals.setdefault(name, []).append(ref)

    # The assertion must have something to bite on: if no shipped Dockerfile
    # carries an external COPY source any more, this test would pass vacuously
    # and the coverage it claims to hold would be unmeasured.
    assert externals, (
        f"no external COPY --from source in {PREPULLED_DOCKERFILES}; this test "
        "no longer proves anything — delete it deliberately rather than leave "
        "it green and empty"
    )
    for name, refs in sorted(externals.items()):
        for ref in refs:
            assert ref in pulled, (
                f"{name} copies from external image {ref!r}, which the pre-pull "
                f"step does not cover. It pulls: {sorted(pulled)}"
            )


def test_shipped_docker_cli_source_is_covered_by_retry() -> None:
    """The `docker` CLI's real source is pinned, and its fetch is retried.

    Resolved through the Dockerfile rather than named, so this holds for the
    source-build stage it uses today and for whatever replaces it — and so
    reintroducing an unpinned external binary image (`COPY --from=docker:29-cli`)
    fails here on the property that motivated the source build, not on a string.
    """
    for name in DOCKER_CLI_DOCKERFILES:
        text = (ROOT / name).read_text()
        aliases, _ = _stages_and_images(text)

        sources = [
            ref
            for line in text.splitlines()
            if (match := _COPY_RE.match(line)) is not None
            and "/usr/local/bin/docker" in _tokens(match.group("rest"))
            for ref in match.group("rest").split()
            if ref.startswith("--from=")
        ]
        assert len(sources) == 1, f"{name} installs the docker CLI from {sources!r}"
        ref = sources[0].removeprefix("--from=")

        # An external binary image would be a published artifact this repo
        # cannot pin to a commit; the CLI is built here so its Go toolchain is
        # the pinned, Trivy-scanned one.
        assert ref.lower() in aliases, (
            f"{name} takes /usr/local/bin/docker from external image {ref!r} "
            f"instead of building it in a stage of its own"
        )
        base = aliases[ref.lower()]
        assert "@sha256:" in base, f"{name} builds the docker CLI on unpinned {base!r}"

        if name in PREPULLED_DOCKERFILES:
            listed = _list_images(*PREPULLED_DOCKERFILES).stdout.split()
            assert base in listed, (
                f"{name}'s docker CLI stage base {base!r} is not covered by the "
                f"retrying pre-pull, which pulls: {sorted(listed)}"
            )
