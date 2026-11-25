"""The shipped docker CLI is built with a scanner-clean vendored module set (#2304).

docker/cli v29.9.1's vendor tree pinned go-jose v4.1.5 (CVE-2026-116587,
HIGH, fixed v4.1.6), golang.org/x/net v0.60.0 (CVE-2026-78661, HIGH, fixed
v0.62.0) and klauspost/compress v1.20.1 (GO-2026-6865, HIGH, fixed v1.20.2;
flagged by the gate's grype cross-check, which trivy's DB does not carry
yet). All have upstream fixes, so the container-scan gate
("Container scan + SBOM + cosign") fails on any image embedding the release
tag's own vendor state.

The repair now rides the CR1373 tag refresh (2026-11-16): docker/cli
v29.9.3's upstream vendor tree already carries go-jose v4.1.7 and
klauspost/compress v1.20.2 (verified against v29.9.3's vendor/modules.txt;
v29.9.2 still vendors both vulnerable versions), so only golang.org/x/net
still needs the local override — the stage patches the pinned tag to
x/net v0.62.0 and re-vendors before building, the same patched-toolchain
policy the age stage in the Conductor Dockerfile already applies.

These tests hold that repair closed structurally:

- BOTH stages that copy `/usr/local/bin/docker` (maistro-engine and
  maistro-engine-research) must pin the same CLI release whose vendor tree
  carries the fixed go-jose/klauspost versions; a tag moved to a release
  that reverts either module would silently re-expose the CVEs in both
  images;
- the x/net override must exist at the fixed version the scanner DB names —
  v29.9.3 upstream still pins the vulnerable v0.60.0, so losing the
  override re-reds both images;
- the stage must re-vendor and build from the patched module set
  (`-mod=mod`: the patched go.mod supersedes the tag's stale vendor tree,
  so the built binary carries the fixed modules; the engine and research
  stages keep this posture byte-identical);
- the CLI source is commit-pinned, so the vendor-tree facts above stay
  bound to the exact upstream snapshot the tag claims to be.
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

#: The CLI release the stages pin, and the fixed versions the scanner DBs
#: name for the three advisories (see the stage comments): CVE-2026-116587
#: -> go-jose v4.1.6 (v29.9.3 vendors v4.1.7 upstream); CVE-2026-78661 ->
#: x/net v0.62.0 (v29.9.3 vendors v0.60.0, hence the override); GO-2026-6865
#: -> klauspost/compress v1.20.2 (v29.9.3 vendors it upstream).
CLI_RELEASE = "29.9.3"
CLI_COMMIT_SHORT = "5457199"
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


def test_every_docker_cli_stage_pins_the_release_with_fixed_upstream_modules() -> None:
    """go-jose and klauspost/compress ride the CLI tag, so pin the right tag.

    The stage no longer overrides go-jose or klauspost/compress: v29.9.3's
    upstream vendor tree already carries their fixed versions (v4.1.7 and
    v1.20.2 respectively, per that tag's vendor/modules.txt — v29.9.2 still
    vendors v4.1.5/v1.20.1). Their CVE posture therefore binds to the pinned
    release: move the tag and this test fails, forcing the re-triage that a
    silent vendor-tree regression (fixed modules dropped between releases)
    must not survive.
    """
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        version_arg = re.search(r"ARG DOCKER_CLI_VERSION=(\S+)", body)
        assert version_arg is not None and version_arg.group(1) == CLI_RELEASE, (
            f"{dockerfile.name}: DOCKER_CLI_VERSION must stay {CLI_RELEASE} — it is "
            "the release whose vendor tree carries go-jose >= v4.1.6 "
            "(CVE-2026-116587's fix) and klauspost/compress >= v1.20.2 "
            "(GO-2026-6865's fix); bump only with a re-triage of that tag's "
            "vendor/modules.txt"
        )
        commit_arg = re.search(r"ARG DOCKER_CLI_COMMIT_SHORT=(\S+)", body)
        assert commit_arg is not None and commit_arg.group(1) == CLI_COMMIT_SHORT, (
            f"{dockerfile.name}: DOCKER_CLI_COMMIT_SHORT must stay {CLI_COMMIT_SHORT} — "
            "the vendor-tree facts above hold for that exact snapshot"
        )


def test_every_docker_cli_stage_still_overrides_x_net() -> None:
    """v29.9.3 upstream still vendors the vulnerable x/net v0.60.0.

    CVE-2026-78661 (HIGH) is fixed in golang.org/x/net v0.62.0 and v29.9.3
    does not carry it, so the stage's `go get` override is load-bearing for
    both scanned images. If a future CLI release vendors v0.62.0 itself,
    this test's failure is the scheduled re-triage point — drop the override
    in the same commit that pins that release.
    """
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        go_get = re.search(r"go get ([^\n]+) &&", body)
        assert go_get is not None, (
            f"{dockerfile.name}: dockerclibuild lost the vendored-module override"
        )
        assert "golang.org/x/net@" in go_get.group(1), (
            f"{dockerfile.name}: golang.org/x/net is no longer overridden in "
            "dockerclibuild (v29.9.3 upstream vendors the CVE-2026-78661-vulnerable "
            "v0.60.0)"
        )


def test_override_versions_are_the_trivy_reported_fixed_versions() -> None:
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        go_get = re.search(r"go get ([^\n]+) &&", body)
        assert go_get is not None, (
            f"{dockerfile.name}: dockerclibuild lost the vendored-module override"
        )
        net_pin = re.search(r"golang\.org/x/net@(\S+)", go_get.group(1))
        assert net_pin is not None and net_pin.group(1) == FIXED_X_NET, (
            f"{dockerfile.name}: the x/net override must stay {FIXED_X_NET} "
            "(CVE-2026-78661's fix); bump only with a re-triage"
        )


def test_stage_revendors_and_builds_the_patched_module_set() -> None:
    for dockerfile in DOCKERFILES:
        body = _dockercli_run_body(dockerfile)
        # go get rewrites go.mod/go.sum; `go mod vendor` re-syncs the tag's
        # stale vendor/ directory to the patched module set either way.
        assert re.search(r"go get .+ && \\\n\s*go mod vendor", body), (
            f"{dockerfile.name}: dockerclibuild must `go mod vendor` after the override"
        )
        # -mod=mod: the build resolves per the patched go.mod (the sum-verified
        # module cache), superseding the vendor/ tree the tag shipped. The
        # build mode is part of the byte-identical engine/research posture
        # (test_engine_and_research_stages_stay_in_sync); flipping it back to
        # -mod=vendor is allowed only as the same two-file change.
        assert re.search(r"go build [^\n]*-mod=mod", body), (
            f"{dockerfile.name}: dockerclibuild must build from the patched go.mod (-mod=mod)"
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
