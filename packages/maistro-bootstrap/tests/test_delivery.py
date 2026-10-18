"""Tests for delivery-mode renderers (SPEC-072726-3439 Phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from maistro_bootstrap.delivery import (
    pinned_images,
    render_image_pull_compose,
    render_makefile,
)
from maistro_bootstrap.materialize import _plan_runtime, materialize_install_artifacts
from maistro_bootstrap.plan import build_install_plan
from maistro_bootstrap.schema import parse_answers_dict

BASE_COMPOSE = {
    "services": {
        "maistro-engine": {"build": ".", "ports": ["8000:8000"]},
        "hive-conductor": {
            "build": {"context": ".", "dockerfile": "packages/hive-conductor/Dockerfile"},
            "ports": ["8101:8101"],
        },
        "postgres": {"image": "pgvector/pgvector:pg17"},
    }
}


@pytest.fixture(autouse=True)
def _unpinned_image_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test in this module to the unset-MAISTRO_IMAGE_TAG case.

    The tag is read from the environment (E5/#298), so a developer who has
    exported it — or a CI runner that inherits it from an installer — would
    otherwise silently change what these tests assert.
    """
    monkeypatch.delenv("MAISTRO_IMAGE_TAG", raising=False)


def test_image_pull_compose_has_no_build_keys() -> None:
    doc = render_image_pull_compose(BASE_COMPOSE)
    services = doc["services"]
    assert all("build" not in svc for svc in services.values())
    assert services["maistro-engine"]["image"] == pinned_images()["maistro-engine"]
    assert services["hive-conductor"]["image"] == pinned_images()["hive-conductor"]
    # image-only services pass through untouched
    assert services["postgres"]["image"] == "pgvector/pgvector:pg17"
    # non-build keys survive
    assert services["maistro-engine"]["ports"] == ["8000:8000"]
    # the input is not mutated
    assert "build" in BASE_COMPOSE["services"]["maistro-engine"]


def test_image_tag_follows_the_installed_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get.sh --version v1.0.0` must not hand you `:latest` images.

    Pinning the source tree to a release while the compose stack pulls a
    moving tag is the failure this exists to prevent: it looks pinned and
    isn't.
    """
    monkeypatch.setenv("MAISTRO_IMAGE_TAG", "v1.0.0")
    services = render_image_pull_compose(BASE_COMPOSE)["services"]
    assert services["maistro-engine"]["image"] == "ghcr.io/agent-stronghold/maistro-engine:v1.0.0"
    assert services["hive-conductor"]["image"] == "ghcr.io/agent-stronghold/hive-conductor:v1.0.0"


def test_blank_image_tag_falls_back_to_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty or whitespace value is 'unset', not a tag named ''."""
    monkeypatch.setenv("MAISTRO_IMAGE_TAG", "   ")
    services = render_image_pull_compose(BASE_COMPOSE)["services"]
    assert services["maistro-engine"]["image"] == "ghcr.io/agent-stronghold/maistro-engine:latest"


def test_unpinned_built_service_is_an_error() -> None:
    base = {"services": {"mystery": {"build": "."}}}
    with pytest.raises(ValueError, match="mystery"):
        render_image_pull_compose(base)


def test_makefile_image_pull_never_builds() -> None:
    text = render_makefile(
        "image_pull", base_compose_path="../docker-compose.yml", revision="abc123"
    )
    assert "--build" not in text
    assert "compose.install.yml" in text
    assert "--project-directory .." in text
    assert "# source revision: abc123" in text
    assert "\n\t" in text  # recipes are tab-indented


def test_makefile_source_build_builds_from_root_compose() -> None:
    text = render_makefile("source_build", base_compose_path="../docker-compose.yml", revision=None)
    assert "up -d --build" in text
    assert "-f ../docker-compose.yml -f compose.override.yml" in text
    assert "# source revision: (unknown)" in text


def _fake_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.yml").write_text(yaml.safe_dump(BASE_COMPOSE), encoding="utf-8")
    return root


def test_materialize_image_pull_writes_standalone_compose(tmp_path: Path) -> None:
    root = _fake_repo(tmp_path)
    answers = parse_answers_dict({"delivery_mode": "image_pull"})
    plan = build_install_plan(answers, repo_root=root)
    target = tmp_path / "out"
    written = materialize_install_artifacts(plan, target)
    names = {p.name for p in written}
    assert "Makefile" in names
    assert "compose.install.yml" in names
    text = (target / "compose.install.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert all("build" not in svc for svc in doc["services"].values())


def test_materialize_source_build_skips_standalone_compose(tmp_path: Path) -> None:
    root = _fake_repo(tmp_path)
    answers = parse_answers_dict({"delivery_mode": "source_build"})
    plan = build_install_plan(answers, repo_root=root)
    target = tmp_path / "out"
    written = materialize_install_artifacts(plan, target)
    names = {p.name for p in written}
    assert "Makefile" in names
    assert "compose.install.yml" not in names
    assert "--build" in (target / "Makefile").read_text(encoding="utf-8")


# --- generated commands name the selected runtime (#1820) -------------------


def test_makefile_names_only_the_selected_runtime() -> None:
    """Restart/recovery recipes invoke `<runtime> compose` — emitting docker
    commands for a selected Podman runtime is the silent switch #1820
    forbids."""
    for runtime in ("docker", "podman"):
        other = "podman" if runtime == "docker" else "docker"
        for mode in ("image_pull", "source_build"):
            text = render_makefile(
                mode,
                base_compose_path="../docker-compose.yml",
                revision=None,
                runtime=runtime,
            )
            assert f"{runtime} compose --project-directory" in text, (runtime, mode)
            assert f"{other} compose" not in text, (runtime, mode)
            assert f"container_runtime={runtime}" in text, (runtime, mode)


def test_makefile_rejects_an_unsupported_runtime_instead_of_guessing() -> None:
    """An unknown runtime is a contract violation, not a docker default."""
    with pytest.raises(ValueError, match="unsupported container runtime"):
        render_makefile("image_pull", base_compose_path=None, revision=None, runtime="nerdctl")


def test_makefile_defaults_to_docker_for_callers_that_pass_no_runtime() -> None:
    """The keyword default keeps existing direct callers working; the planner
    path always passes the resolved runtime explicitly."""
    text = render_makefile("image_pull", base_compose_path=None, revision=None)
    assert "docker compose --project-directory" in text


def test_materialized_artifacts_name_the_plan_runtime(tmp_path: Path) -> None:
    """A plan that resolved podman must materialize a Makefile and both
    entrypoint hints naming podman — the operator's first restart command
    comes from these files, and it must match the selected runtime."""
    root = _fake_repo(tmp_path)
    answers = parse_answers_dict({"container_runtime": "podman", "delivery_mode": "source_build"})
    plan = build_install_plan(answers, repo_root=root)
    target = tmp_path / "out"
    materialize_install_artifacts(plan, target)
    makefile = (target / "Makefile").read_text(encoding="utf-8")
    assert "podman compose" in makefile
    assert "docker compose" not in makefile
    assert "podman compose" in (target / "install.sh").read_text(encoding="utf-8")
    assert "podman compose" in (target / "install.ps1").read_text(encoding="utf-8")


def test_materialize_falls_back_to_docker_only_for_legacy_plans(tmp_path: Path) -> None:
    """A plan written before the delivery artifact carried a runtime (pre-#1820)
    still materializes: the reader defaults to docker rather than crashing.
    Fresh plans always carry the field, so the fallback only serves old plan
    directories being re-materialized."""
    root = _fake_repo(tmp_path)
    answers = parse_answers_dict({"delivery_mode": "source_build"})
    plan = build_install_plan(answers, repo_root=root)
    del plan["generated_artifacts"]["delivery"]["container_runtime"]
    target = tmp_path / "out"
    materialize_install_artifacts(plan, target)
    assert "docker compose" in (target / "Makefile").read_text(encoding="utf-8")


def test_plan_runtime_rejects_unexpected_delivery_shapes() -> None:
    """_plan_runtime's guards are total over arbitrary plan-shaped dicts: a
    missing/non-dict generated_artifacts and a missing/non-dict delivery each
    fall back to docker (and an unrecognized token is not passed through).
    materialize_install_artifacts raises earlier for a non-dict artifacts, so
    the first two guards are reachable only through this reader directly."""
    assert _plan_runtime({}) == "docker"
    assert _plan_runtime({"generated_artifacts": None}) == "docker"
    assert _plan_runtime({"generated_artifacts": {"delivery": None}}) == "docker"
    assert _plan_runtime({"generated_artifacts": {"delivery": ["podman"]}}) == "docker"
    assert (
        _plan_runtime({"generated_artifacts": {"delivery": {"container_runtime": "nerdctl"}}})
        == "docker"
    )


def test_plan_runtime_reads_the_delivery_recording() -> None:
    """The happy path the fallback exists to protect: the delivery artifact's
    recording is the resolved runtime, verbatim."""
    plan = {"generated_artifacts": {"delivery": {"container_runtime": "podman"}}}
    assert _plan_runtime(plan) == "podman"


def test_materialize_survives_a_corrupted_delivery_artifact(tmp_path: Path) -> None:
    """generated_artifacts present but delivery not a mapping (a hand-edited or
    truncated plan file): materialization still completes on the docker
    default instead of crashing the installer mid-write."""
    root = _fake_repo(tmp_path)
    answers = parse_answers_dict({"delivery_mode": "source_build"})
    plan = build_install_plan(answers, repo_root=root)
    plan["generated_artifacts"]["delivery"] = ["corrupted"]
    target = tmp_path / "out"
    materialize_install_artifacts(plan, target)
    assert "docker compose" in (target / "Makefile").read_text(encoding="utf-8")
    assert "docker compose" in (target / "install.sh").read_text(encoding="utf-8")
