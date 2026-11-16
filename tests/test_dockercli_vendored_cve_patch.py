"""The shipped docker CLI is built with the trivy-fixed vendored modules (#2304).

docker/cli v29.9.1's vendor tree pins go-jose v4.1.5 (CVE-2026-116587, HIGH,
fixed v4.1.6) and golang.org/x/net v0.60.0 (CVE-2026-78661, HIGH, fixed
v0.62.0). Both have upstream fixes, so the container-scan gate
("Container scan + SBOM + cosign") fails on any image embedding the release
tag's own vendor state. The `dockerclibuild` stages therefore override the two
modules to their fixed versions and re-vendor before building — the same
patched-toolchain policy the age stage in the Conductor Dockerfile already
applies.

These tests hold that repair closed structurally:

- the override must exist in BOTH stages that copy `/usr/local/bin/docker`
  (maistro-engine and maistro-engine-research); the failed gate's scan order
  means fixing only the engine image would leave the research image red, and
  vice versa;
- the overridden versions must be the fixed ones the scanner DB names — an
  ARG bumped to an unrelated version would silently re-expose the CVE;
- the stage must re-vendor and build with `-mod=vendor`, so the build reads
  the patched module set instead of failing on (or silently ignoring)
  inconsistent vendoring.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The Dockerfiles that build and ship a docker CLI from the dockerclibuild
#: stage. Every one of these images is scanned by security.yml, so a stage
#: that loses the override re-reds the gate on the next DB refresh.
DOCKERFILES = (
    ROOT / "Dockerfile",
    ROOT / "Dockerfile.research",
)

#: The fixed versions the trivy DB names for the two CVEs (see the stage
#: comments): CVE-2026-116587 -> go-jose v4.1.6; CVE-2026-78661 -> x/net v0.62.0.
FIXED_GO_JOSE = "v4.1.6"
FIXED_X_NET = "v0.62.0"


def _dockercli_run_body(dockerfile: Path) -> str:
    """The RUN body of the file's dockerclibuild stage, with continuations joined."""
    text = dockerfile.read_text()
    stage = re.search(
        r"FROM golang:[^\n]*AS dockerclibuild\n(?:(?!^FROM ).)*",
        text,
        re.S | re.M,
    )
    assert stage is not None, f"{dockerfile.name}: no dockerclibuild stage"
    return stage.group(0)


def test_every_docker_cli_stage_overrides_both_vulnerable_modules() -> None:
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        go_get = re.search(r"go get ([^\n]+) &&", body)
        assert go_get is not None, (
            f"{dockerfile.name}: dockerclibuild lost the vendored-module override"
        )
        assert "github.com/go-jose/go-jose/v4@" in go_get.group(1), (
            f"{dockerfile.name}: go-jose is no longer overridden in dockerclibuild"
        )
        assert "golang.org/x/net@" in go_get.group(1), (
            f"{dockerfile.name}: golang.org/x/net is no longer overridden in dockerclibuild"
        )


def test_override_versions_are_the_trivy_reported_fixed_versions() -> None:
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        jose_arg = re.search(r"ARG GO_JOSE_FIXED_VERSION=(\S+)", body)
        net_arg = re.search(r"ARG GO_X_NET_FIXED_VERSION=(\S+)", body)
        assert jose_arg is not None and jose_arg.group(1) == FIXED_GO_JOSE, (
            f"{dockerfile.name}: GO_JOSE_FIXED_VERSION must stay {FIXED_GO_JOSE} "
            "(CVE-2026-116587's fix); bump only with a re-triage"
        )
        assert net_arg is not None and net_arg.group(1) == FIXED_X_NET, (
            f"{dockerfile.name}: GO_X_NET_FIXED_VERSION must stay {FIXED_X_NET} "
            "(CVE-2026-78661's fix); bump only with a re-triage"
        )


def test_stage_revendors_and_builds_in_vendor_mode() -> None:
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        # go get rewrites go.mod/go.sum; without `go mod vendor` the vendor
        # tree is inconsistent with them and the build either fails or, worse,
        # is forced off vendor mode entirely.
        assert re.search(r"go get .+ && \\\n\s*go mod vendor", body), (
            f"{dockerfile.name}: dockerclibuild must `go mod vendor` after the override"
        )
        assert "go build -mod=vendor" in body, (
            f"{dockerfile.name}: dockerclibuild must build the re-vendored tree (-mod=vendor)"
        )


def test_engine_and_research_stages_stay_in_sync() -> None:
    bodies = [_dockercli_run_body(dockerfile) for dockerfile in DOCKERFILES]
    normalized: list[str] = []
    for body in bodies:
        # Normalize the comment blocks away (they may diverge in wording) and
        # keep only executable instructions.
        lines = [
            line for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")
        ]
        normalized.append("\n".join(lines))
    assert len(set(normalized)) == 1, (
        "the dockerclibuild stages of the engine and research images diverged; "
        "both images are scanned, so a fix applied to one leaves the other red"
    )
