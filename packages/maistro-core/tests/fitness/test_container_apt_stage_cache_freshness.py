"""The container gate's apt security-patch stage must not be layer-cached.

Issue #795 CI-repair round, 2026-10-22: the "Container scan + SBOM + cosign"
job failed on maistro-engine carrying ``libexpat1 2.5.0-1+deb12u4`` —
CVE-2025-59375 / CVE-2026-77214 are HIGH and fixed in ``deb12u5`` — in a
build whose Dockerfile nobody had touched. The CI log shows why: the image's
``RUN apt-get update && ... && apt-get upgrade -y`` layer came back ``CACHED``
from the GHA build cache. An apt layer's cache key (base digest + instruction
text) never changes, so once cached it replays whatever the Debian security
mirror served when it was first built — the Dockerfile comment claimed "the
apt layer also applies the security patches", and the cache silently
invalidated that claim.

The fix pairs each Debian runtime's security-patch layer in its own named
``*-apt`` stage with a ``--no-cache-filter <stage>`` on the build that gates
on the result (``security.yml``'s containers job). This suite freezes both
halves of that pairing:

- every governed Debian-runtime Dockerfile keeps its security-patch layer in
  the expected named stage, and that stage is actually consumed by a later
  ``FROM`` (otherwise the re-run would build a stage nothing ships);
- every ``buildx-build-retry.sh`` build in the containers job that gates an
  image passes ``--no-cache-filter`` naming that image's stage.

``release.yml`` is deliberately out of scope: it builds its release
candidates cold (no ``--cache-from``), so there is no stale layer to bypass.
If it ever grows a cache, the pairing must move with it — but that is a
change to review, not one this fence needs to anticipate.

Local proof the mechanism works (2026-10-22, docker buildx v0.37.2): a warm
rebuild *without* the flag reports the apt stage ``CACHED``; with the flag
the stage re-executes and the shipped ``maistro-engine`` carries
``libexpat1 2.5.0-1+deb12u5`` and scans clean under trivy 0.73.0 with the
gate's exact flags (all four scanned images do).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

#: The Debian-runtime Dockerfiles the containers job scans, mapped to the
#: stage that must own the security-patch layer. All four share the same
#: hazard: an ``apt-get upgrade`` layer whose cache key never changes.
_APT_STAGE_BY_DOCKERFILE: tuple[tuple[str, str], ...] = (
    ("Dockerfile", "runtime-apt"),
    ("Dockerfile.research", "production-apt"),
    ("Dockerfile.rsi-runner", "runtime-apt"),
    ("packages/hive-conductor/Dockerfile", "runtime-apt"),
)

_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)

#: security.yml's scanning job — the only place where a stale apt layer is a
#: gate bypass rather than a slower build.
_CONTAINERS_JOB = "containers"


def _stages(dockerfile: Path) -> list[tuple[str | None, list[str]]]:
    """Parse (name, body-lines) for each stage of a Dockerfile."""
    stages: list[tuple[str | None, list[str]]] = []
    current_name: str | None = None
    body: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        match = _FROM_RE.match(line)
        if match:
            if current_name is not None or body:
                stages.append((current_name, body))
            current_name = match.group(2)
            body = []
        else:
            body.append(line)
    if current_name is not None or body:
        stages.append((current_name, body))
    return stages


@pytest.mark.parametrize(
    ("dockerfile_rel", "expected_stage"),
    _APT_STAGE_BY_DOCKERFILE,
    ids=[f"{df}->{stage}" for df, stage in _APT_STAGE_BY_DOCKERFILE],
)
def test_security_patch_layer_lives_in_named_consumed_stage(
    dockerfile_rel: str, expected_stage: str
) -> None:
    dockerfile = _REPO_ROOT / dockerfile_rel
    stages = _stages(dockerfile)
    names = [name for name, _ in stages]

    assert expected_stage in names, (
        f"{dockerfile_rel}: the apt security-patch layer must live in the "
        f"named stage '{expected_stage}' so CI can --no-cache-filter it (#795)"
    )

    stage_body = next(body for name, body in stages if name == expected_stage)
    joined = "\n".join(stage_body)
    assert "apt-get update" in joined and "apt-get upgrade" in joined, (
        f"{dockerfile_rel}: stage '{expected_stage}' must run apt-get update "
        "+ apt-get upgrade — it is the layer that re-consults the Debian "
        "security mirror on every gated build (#795)"
    )

    consumed = re.search(
        rf"^\s*FROM\s+{re.escape(expected_stage)}\s*$",
        "\n".join(line for line in dockerfile.read_text(encoding="utf-8").splitlines()),
        re.IGNORECASE | re.MULTILINE,
    )
    assert consumed is not None, (
        f"{dockerfile_rel}: no later 'FROM {expected_stage}' consumes the "
        "security-patch stage — re-running it would build layers nothing "
        "ships (#795)"
    )


def test_containers_job_bypasses_cache_for_every_gated_apt_stage() -> None:
    import yaml

    workflow = yaml.safe_load(
        (_REPO_ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"][_CONTAINERS_JOB]["steps"]

    build_runs: list[tuple[str, str]] = []
    for step in steps:
        run = step.get("run") or ""
        if "buildx-build-retry.sh" in run:
            file_match = re.search(r"-f\s+(\S+)", run)
            assert file_match is not None, f"containers step {step.get('name')!r} builds without -f"
            build_runs.append((file_match.group(1), run))

    gated = {df for df, _ in _APT_STAGE_BY_DOCKERFILE}
    built = {df for df, _ in build_runs}
    assert gated <= built, (
        f"containers job no longer builds every gated Dockerfile: missing {sorted(gated - built)}"
    )

    for dockerfile_rel, run in build_runs:
        expected_stage = dict(_APT_STAGE_BY_DOCKERFILE).get(dockerfile_rel)
        if expected_stage is None:
            continue
        assert f"--no-cache-filter {expected_stage}" in run, (
            f"containers build of {dockerfile_rel} must pass "
            f"'--no-cache-filter {expected_stage}': without it the GHA layer "
            "cache can replay a pre-advisory apt state forever, and the "
            "trivy gate then fails on a tree nobody changed (#795)"
        )
