"""The source-built docker CLI must carry the fixed go-jose, x/net and
klauspost/compress releases.

`docker/cli` ships a vendored module set pinned to `go-jose/v4 v4.1.5`,
`golang.org/x/net v0.60.0` and `github.com/klauspost/compress v1.20.1`, all
with fixed releases (CVE-2026-116587, CVE-2026-78661 — HIGH; GO-2026-6865 —
the High that failed the Grype cross-check `--fail-on high` on
`maistro-engine:pr-2059`, security.yml run 43878205511 job 133336745388).
The Container scan reads the built `/usr/local/bin/docker` binary twice —
Trivy (HIGH/CRITICAL, exit-code 1) and Grype — so an unraised pin fails the
image scan even though no Python dependency is at fault. Each Dockerfile that
builds that CLI must raise all three modules in the same `go get`, then
re-sync `vendor/` with `go mod vendor`: `go get` alone leaves
`vendor/modules.txt` inconsistent and the build fails with "inconsistent
vendoring".

Structural assertions over the Dockerfile text, not a build, so the test is
fast and machine-independent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCKERFILES_BUILDING_DOCKER_CLI = (
    REPO_ROOT / "Dockerfile",
    REPO_ROOT / "Dockerfile.research",
)

FIXED_GO_JOSE = "github.com/go-jose/go-jose/v4@v4.1.6"
FIXED_X_NET = "golang.org/x/net@v0.62.0"
FIXED_KLAUSPOST_COMPRESS = "github.com/klauspost/compress@v1.20.2"


def _docker_cli_stage(text: str) -> str:
    match = re.search(
        r"^FROM golang:[^\n]*AS dockerclibuild\n(.*?)(?=^FROM |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, "no dockerclibuild stage found"
    # Join shell line continuations first: a `go get` wrapped across RUN lines
    # would otherwise hide the continuation-line modules from a single-line
    # match (exactly how a v1.20.2 bump on a wrapped line would evade this
    # test while still building correctly).
    return match.group(1).replace("\\\n", " ")


@pytest.mark.parametrize("dockerfile", DOCKERFILES_BUILDING_DOCKER_CLI, ids=lambda p: p.name)
def test_docker_cli_stage_raises_go_jose_and_x_net_to_fixed_releases(dockerfile: Path) -> None:
    stage = _docker_cli_stage(dockerfile.read_text(encoding="utf-8"))
    go_get = re.search(r"go get ([^&\n]*)", stage)
    assert go_get, f"{dockerfile.name}: docker CLI stage has no `go get` upgrade"
    args = go_get.group(1)
    assert FIXED_GO_JOSE in args, f"{dockerfile.name}: go-jose not raised to v4.1.6"
    assert FIXED_X_NET in args, f"{dockerfile.name}: x/net not raised to v0.62.0"


@pytest.mark.parametrize("dockerfile", DOCKERFILES_BUILDING_DOCKER_CLI, ids=lambda p: p.name)
def test_docker_cli_stage_raises_klauspost_compress_to_fixed_release(dockerfile: Path) -> None:
    stage = _docker_cli_stage(dockerfile.read_text(encoding="utf-8"))
    go_get = re.search(r"go get ([^&\n]*)", stage)
    assert go_get, f"{dockerfile.name}: docker CLI stage has no `go get` upgrade"
    assert FIXED_KLAUSPOST_COMPRESS in go_get.group(1), (
        f"{dockerfile.name}: klauspost/compress not raised to v1.20.2 "
        "(GO-2026-6865 High fails the Grype cross-check)"
    )


@pytest.mark.parametrize("dockerfile", DOCKERFILES_BUILDING_DOCKER_CLI, ids=lambda p: p.name)
def test_docker_cli_stage_resyncs_vendor_after_the_upgrade(dockerfile: Path) -> None:
    stage = _docker_cli_stage(dockerfile.read_text(encoding="utf-8"))
    upgrade = stage.index("go get ")
    resync = stage.index("go mod vendor")
    assert resync > upgrade, (
        f"{dockerfile.name}: `go mod vendor` must follow the `go get`, or the "
        "vendored tree is inconsistent with go.mod and the build fails"
    )


def test_degenerate_stage_without_upgrade_is_rejected() -> None:
    bare = "RUN git clone x && CGO_ENABLED=0 go build -o /out/docker ./cmd/docker\n"
    text = f"FROM golang:1.27.3-alpine AS dockerclibuild\n{bare}FROM alpine\n"
    stage = _docker_cli_stage(text)
    assert re.search(r"go get ([^&\n]*)", stage) is None
