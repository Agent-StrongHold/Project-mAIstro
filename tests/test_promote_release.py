"""The RC-artifact reuse path, tested rather than trusted (#89).

`scripts/promote_release.py` is the mechanism behind ADR-073126-c4e1 §6's
"the final release ships the artifacts the last rc already validated". Its
failure modes are exactly the ones that would quietly void the soak: a final
that rebuilds instead of adopting, a soak record that does not bind to the
promoted bytes, an unverified hash, and an invariant-invalidating finding
nobody filed. Each has a test here, over real files and real hashes — the
zip download path included — with GitHub access injected.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROMOTE = REPO / "scripts" / "promote_release.py"

ENGINE_DIGEST = "sha256:" + "a" * 64
CONDUCTOR_DIGEST = "sha256:" + "b" * 64
WHEEL_NAME = "maistro_core-1.0.0-py3-none-any.whl"
SDIST_NAME = "maistro_core-1.0.0.tar.gz"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return mod


@pytest.fixture(scope="module")
def promote_mod():
    return _load(PROMOTE, "_promote_release")


# Module-level handle for the shared builders below (the fixture returns the
# same loaded module; tests take it as a parameter to keep that explicit).
promote = _load(PROMOTE, "_promote_release_module")


def sha(name: str, content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


def make_evidence(
    *,
    version: str = "1.0.0",
    rc_tag: str = "v1.0.0-rc1",
    tree: str = "c" * 40,
    commit: str = "d" * 40,
    wheels: dict[str, str] | None = None,
    images: dict[str, str] | None = None,
    run_id: int = 42,
) -> dict:
    if wheels is None:
        wheels = {
            WHEEL_NAME: sha(WHEEL_NAME, b"wheel-bytes"),
            SDIST_NAME: sha(SDIST_NAME, b"sdist"),
        }
    evidence: dict = {
        "schema": 1,
        "tag": rc_tag,
        "version": version,
        "commit": commit,
        "tree": tree,
        "run_id": run_id,
        "run_url": f"https://github.com/org/repo/actions/runs/{run_id}",
        "wheels": wheels,
    }
    if images is not None:
        evidence["images"] = images
    return evidence


def make_soak(evidence: dict, *, config_digest: str = "e" * 64) -> dict:
    return {
        "schema": 1,
        "artifact_binding": {
            "wheels_sha256": evidence["wheels"],
            "image_digests": evidence.get(
                "images", {"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
            ),
            "config_digest": config_digest,
            "config": "deploy/soak/compose.yaml@" + config_digest[:12],
        },
        "checks": {
            name: {"status": "pass", "evidence": [f"logs/{name}.txt"]}
            for name in promote.REQUIRED_SOAK_CHECKS
        },
        "findings": [{"id": "F-1", "severity": "low", "invalidates_invariant": False}],
    }


# --- evidence record validation ---------------------------------------------


def test_valid_evidence_passes(promote_mod):
    assert (
        promote_mod.validate_evidence(make_evidence(), version="1.0.0", rc_tag="v1.0.0-rc1") == []
    )


def test_matching_tree_passes_and_mismatching_tree_fails(promote_mod):
    record = make_evidence(tree="c" * 40)
    assert (
        promote_mod.validate_evidence(record, version="1.0.0", rc_tag="v1.0.0-rc1", tree="c" * 40)
        == []
    )
    errors = promote_mod.validate_evidence(
        record, version="1.0.0", rc_tag="v1.0.0-rc1", tree="9" * 40
    )
    assert any("record describes" in message and "promoted tree" in message for message in errors)


@pytest.mark.parametrize(
    "field, value",
    [
        ("schema", 2),
        ("version", "0.9.0"),
        ("tag", "v1.0.0-rc9"),
        ("commit", "nothex"),
        ("tree", "z" * 40),
        ("run_id", 0),
        ("run_id", True),  # bools are ints; the record must not accept one
        ("run_id", "42"),
        ("run_url", "http://insecure/run"),
        ("run_url", 42),
    ],
)
def test_corrupt_evidence_fields_are_rejected(promote_mod, field, value):
    record = make_evidence()
    record[field] = value
    assert promote_mod.validate_evidence(record, version="1.0.0", rc_tag="v1.0.0-rc1") != []


def test_empty_or_pathy_wheel_names_are_rejected(promote_mod):
    record = make_evidence(wheels={"../escape.whl": sha("x", b"")})
    errors = promote_mod.validate_evidence(record, version="1.0.0", rc_tag="v1.0.0-rc1")
    assert any("plain artifact filename" in message for message in errors)


def test_wheel_map_must_be_nonempty_with_real_digests(promote_mod):
    for wheels in ({}, {"x.txt": "not-a-digest"}):
        record = make_evidence(wheels=wheels)
        errors = promote_mod.validate_evidence(record, version="1.0.0", rc_tag="v1.0.0-rc1")
        assert errors, f"wheels={wheels!r} must not validate"


def test_partial_images_must_name_both_published_images(promote_mod):
    record = make_evidence(images={"maistro-engine": ENGINE_DIGEST})
    errors = promote_mod.validate_evidence(record, version="1.0.0", rc_tag="v1.0.0-rc1")
    assert any("hive-conductor" in message for message in errors)
    complete = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    assert promote_mod.validate_evidence(complete, version="1.0.0", rc_tag="v1.0.0-rc1") == []


# --- soak evidence validation ------------------------------------------------


def test_complete_soak_passes(promote_mod):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    assert promote_mod.validate_soak(make_soak(evidence), evidence=evidence) == []


def test_soak_bound_to_different_bytes_is_rejected(promote_mod):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    soak = make_soak(evidence)
    soak["artifact_binding"]["wheels_sha256"] = {WHEEL_NAME: "0" * 64}
    errors = promote_mod.validate_soak(soak, evidence=evidence)
    assert any("soak did not run against these artifacts" in message for message in errors)


def test_soak_bound_to_a_stale_digest_is_rejected(promote_mod):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    soak = make_soak(evidence)
    soak["artifact_binding"]["image_digests"] = {
        "maistro-engine": "sha256:" + "0" * 64,
        "hive-conductor": CONDUCTOR_DIGEST,
    }
    errors = promote_mod.validate_soak(soak, evidence=evidence)
    assert any("image digests" in message for message in errors)


def test_soak_without_configuration_binding_is_rejected(promote_mod):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    soak = make_soak(evidence)
    soak["artifact_binding"]["config_digest"] = "short"
    assert any(
        "config_digest" in message for message in promote_mod.validate_soak(soak, evidence=evidence)
    )
    soak["artifact_binding"]["config_digest"] = "f" * 64
    soak["artifact_binding"]["config"] = "   "
    assert any(
        "configuration reference" in message
        for message in promote_mod.validate_soak(soak, evidence=evidence)
    )


@pytest.mark.parametrize(
    "mutation, fragment",
    [
        (lambda s, name: s["checks"].pop(name), "missing"),
        (lambda s, name: s["checks"][name].update(status="fail"), "must be 'pass'"),
        (lambda s, name: s["checks"][name].update(evidence=[]), "cite at least one"),
        (lambda s, name: s["checks"][name].update(evidence=["   "]), "cite at least one"),
    ],
)
def test_every_required_soak_check_gates_promotion(promote_mod, mutation, fragment):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    for name in promote.REQUIRED_SOAK_CHECKS:
        soak = make_soak(evidence)
        mutation(soak, name)
        errors = promote_mod.validate_soak(soak, evidence=evidence)
        assert any(name in message and fragment in message for message in errors), (
            f"{name}: {fragment} mutation was not rejected"
        )


def test_required_soak_checks_are_pinned_not_adaptive(promote_mod):
    """The gate demands exactly the soak coverage #89 pins — by name.

    `test_every_required_soak_check_gates_promotion` iterates
    REQUIRED_SOAK_CHECKS, so it passes vacuously if a check is dropped from
    the tuple: dropping `multi_replica_soak` today keeps all 44 promotion
    tests green while the final promotion stops demanding the #860 soak.
    This test pins the set itself (issue #89 acceptance: clean install,
    real-model execution, security hot path, backup/restore; #860:
    sustained multi-replica soak).
    """

    expected = {
        "clean_install",
        "real_model",
        "security_hot_path",
        "backup_restore",
        "multi_replica_soak",
    }
    actual = set(promote_mod.REQUIRED_SOAK_CHECKS)
    assert actual == expected, (
        "REQUIRED_SOAK_CHECKS drifted from the soak coverage issue #89 pins: "
        f"missing={sorted(expected - actual)} unexpected={sorted(actual - expected)}"
    )


def test_invalidated_invariant_must_be_routed_before_promotion(promote_mod):
    evidence = make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )
    soak = make_soak(evidence)
    soak["findings"].append({"id": "F-9", "severity": "high", "invalidates_invariant": True})
    errors = promote_mod.validate_soak(soak, evidence=evidence)
    assert any("routed_issue" in message for message in errors)

    soak["findings"][-1]["routed_issue"] = "issue 412"
    assert any(
        "routed_issue" in message for message in promote_mod.validate_soak(soak, evidence=evidence)
    )

    soak["findings"][-1]["routed_issue"] = "#412"
    assert promote_mod.validate_soak(soak, evidence=evidence) == []


# --- byte verification ---------------------------------------------------------


def test_verify_dist_accepts_exactly_the_recorded_bytes(promote_mod, tmp_path: Path):
    wheels = {
        WHEEL_NAME: sha(WHEEL_NAME, b"wheel-bytes"),
        SDIST_NAME: sha(SDIST_NAME, b"sdist-bytes"),
    }
    for name, content in ((WHEEL_NAME, b"wheel-bytes"), (SDIST_NAME, b"sdist-bytes")):
        (tmp_path / name).write_bytes(content)
    assert promote_mod.verify_dist(tmp_path, wheels) == []


def test_verify_dist_rejects_a_hash_mismatch(promote_mod, tmp_path: Path):
    (tmp_path / WHEEL_NAME).write_bytes(b"tampered")
    errors = promote_mod.verify_dist(tmp_path, {WHEEL_NAME: sha(WHEEL_NAME, b"wheel-bytes")})
    assert any("not the soaked bytes" in message for message in errors)


def test_verify_dist_rejects_missing_and_extra_files(promote_mod, tmp_path: Path):
    (tmp_path / "extra-1.0.0.whl").write_bytes(b"surprise")
    errors = promote_mod.verify_dist(tmp_path, {WHEEL_NAME: sha(WHEEL_NAME, b"wheel-bytes")})
    assert any("missing from" in message for message in errors)
    assert any("not in the record" in message for message in errors)


# --- RC run selection ------------------------------------------------------------


def rc_run(
    run_id: int,
    *,
    branch="v1.0.0-rc1",
    conclusion="success",
    event="push",
    path=".github/workflows/release.yml",
    name="release",
):
    return {
        "id": run_id,
        "head_branch": branch,
        "event": event,
        "conclusion": conclusion,
        "path": path,
        "name": name,
    }


def test_select_rc_run_takes_the_latest_successful_release_run(promote_mod):
    runs = [
        rc_run(1),
        rc_run(2, conclusion="failure"),
        rc_run(3, event="workflow_dispatch"),
        rc_run(4),
    ]
    run, errors = promote_mod.select_rc_run(runs, "v1.0.0-rc1")
    assert (errors, run["id"]) == ([], 4)


def test_select_rc_run_ignores_other_tags_and_names(promote_mod):
    runs = [
        rc_run(1, branch="v1.0.0-rc2"),
        rc_run(2, branch="main"),
        rc_run(3, path=".github/workflows/ci.yml", name="CI"),
    ]
    run, errors = promote_mod.select_rc_run(runs, "v1.0.0-rc1")
    assert run is None
    assert errors and "no release run" in errors[0]


def test_a_failed_latest_candidate_run_blocks_promotion(promote_mod):
    """The latest attempt defines the candidate's truth: neither routing around
    it to an older run nor to an older candidate is allowed."""
    runs = [rc_run(1), rc_run(7, conclusion="failure")]
    run, errors = promote_mod.select_rc_run(runs, "v1.0.0-rc1")
    assert run is None
    assert "not 'success'" in errors[0]


# --- artifact download ------------------------------------------------------------


def test_download_artifact_unpacks_the_zip_payload(promote_mod, tmp_path: Path):
    """The real unzip path: gh api streams the artifact zip, this unpacks it."""

    def fake_run(args, stdout=None, stderr=None, text=False, check=False):
        if stdout is not None:
            with zipfile.ZipFile(stdout, "w") as archive:
                archive.writestr(WHEEL_NAME, b"wheel-bytes")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    original = promote_mod.subprocess.run
    promote_mod.subprocess.run = fake_run
    try:
        promote_mod._download_artifact("org/repo", 7, tmp_path)
    finally:
        promote_mod.subprocess.run = original
    assert (tmp_path / WHEEL_NAME).read_bytes() == b"wheel-bytes"


def test_download_artifact_fails_loudly_on_gh_error(promote_mod, tmp_path: Path):
    def fake_run(args, stdout=None, stderr=None, text=False, check=False):
        return subprocess.CompletedProcess(args, 1, b"", b"403")

    original = promote_mod.subprocess.run
    promote_mod.subprocess.run = fake_run
    try:
        with pytest.raises(RuntimeError, match="403"):
            promote_mod._download_artifact("org/repo", 7, tmp_path)
    finally:
        promote_mod.subprocess.run = original


def pin_current_tree(monkeypatch: pytest.MonkeyPatch, promote_mod, tree: str) -> None:
    """Pin what the CLI sees as the checked-out tree (a real promotion run
    compares against the final tag's checkout)."""

    def fake_check_output(args, **kwargs):
        if "HEAD^{tree}" in args:
            return tree + "\n"
        return subprocess.check_output(args, **kwargs)

    monkeypatch.setattr(promote_mod.subprocess, "check_output", fake_check_output)


# --- CLI: adopt-wheels ------------------------------------------------------------


@pytest.fixture
def github_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")


def install_rc_run(
    monkeypatch: pytest.MonkeyPatch,
    promote_mod,
    tmp_path: Path,
    *,
    evidence: dict,
    dist_files: dict[str, bytes],
    soak_artifact: dict | None = None,
    run_id: int | None = None,
):
    """Serve a complete fake RC run through the script's GitHub seams."""
    run_id = evidence["run_id"] if run_id is None else run_id
    monkeypatch.setattr(promote_mod, "_fetch_run_id", lambda repo, rc_tag: run_id)

    def fake_artifact_id(repo: str, rid: int, name: str) -> int:
        assert rid == run_id
        assert name in ("release-evidence", "dist", "soak-evidence"), (
            f"unexpected artifact request {name!r}"
        )
        return {"release-evidence": 101, "dist": 102, "soak-evidence": 103}[name]

    monkeypatch.setattr(promote_mod, "_artifact_id", fake_artifact_id)

    def fake_download(repo: str, artifact_id: int, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        if artifact_id == 101:
            (dest / "release-evidence.json").write_text(json.dumps(evidence))
        elif artifact_id == 102:
            for name, content in dist_files.items():
                (dest / name).write_bytes(content)
        elif artifact_id == 103:
            if soak_artifact is None:
                raise SystemExit(f"::error::run {run_id} has no 'soak-evidence' artifact")
            (dest / "soak-evidence.json").write_text(json.dumps(soak_artifact))

    monkeypatch.setattr(promote_mod, "_download_artifact", fake_download)


def test_adopt_wheels_promotes_the_candidate_bytes(promote_mod, tmp_path, monkeypatch, github_env):
    evidence = make_evidence()
    pin_current_tree(monkeypatch, promote_mod, evidence["tree"])
    dist_files = {WHEEL_NAME: b"wheel-bytes", SDIST_NAME: b"sdist"}
    install_rc_run(monkeypatch, promote_mod, tmp_path, evidence=evidence, dist_files=dist_files)

    dist_dir = tmp_path / "dist"
    out = tmp_path / "github-output"
    code = promote_mod.main(
        [
            "adopt-wheels",
            "--tag",
            "v1.0.0",
            "--version",
            "1.0.0",
            "--rc-tag",
            "v1.0.0-rc1",
            "--dist-dir",
            str(dist_dir),
            "--evidence-out",
            str(tmp_path / "evidence.json"),
            "--github-output",
            str(out),
        ]
    )
    assert code == 0
    assert sorted(p.name for p in dist_dir.iterdir()) == sorted(dist_files)
    adopted = json.loads((tmp_path / "evidence.json").read_text())
    assert adopted["tag"] == "v1.0.0-rc1"
    assert "rc_run_id=42\n" in out.read_text()


def test_adopt_wheels_fails_closed_on_tampered_bytes(
    promote_mod, tmp_path, monkeypatch, github_env
):
    evidence = make_evidence()
    # Reach byte verification instead of rejecting the fixture's synthetic
    # tree before the tampered dist is downloaded.
    pin_current_tree(monkeypatch, promote_mod, evidence["tree"])
    install_rc_run(
        monkeypatch,
        promote_mod,
        tmp_path,
        evidence=evidence,
        dist_files={WHEEL_NAME: b"rebuilt-not-identical", SDIST_NAME: b"sdist"},
    )
    assert (
        promote_mod.main(
            [
                "adopt-wheels",
                "--tag",
                "v1.0.0",
                "--version",
                "1.0.0",
                "--rc-tag",
                "v1.0.0-rc1",
                "--dist-dir",
                str(tmp_path / "dist"),
                "--evidence-out",
                str(tmp_path / "evidence.json"),
            ]
        )
        == 1
    )
    assert (tmp_path / "dist" / WHEEL_NAME).read_bytes() == b"rebuilt-not-identical"
    assert not (tmp_path / "evidence.json").exists()


def test_adopt_wheels_fails_closed_when_the_record_describes_another_tree(
    promote_mod, tmp_path, monkeypatch, github_env
):
    """A record of a DIFFERENT tree (stale evidence, wrong candidate) must not
    pass even if the downloaded bytes hash-match the record."""
    evidence = make_evidence(tree="c" * 40)
    install_rc_run(
        monkeypatch,
        promote_mod,
        tmp_path,
        evidence=evidence,
        dist_files={WHEEL_NAME: b"wheel-bytes", SDIST_NAME: b"sdist"},
    )

    pin_current_tree(monkeypatch, promote_mod, "9" * 40)
    assert (
        promote_mod.main(
            [
                "adopt-wheels",
                "--tag",
                "v1.0.0",
                "--version",
                "1.0.0",
                "--rc-tag",
                "v1.0.0-rc1",
                "--dist-dir",
                str(tmp_path / "dist"),
                "--evidence-out",
                str(tmp_path / "evidence.json"),
            ]
        )
        == 1
    )


# --- CLI: adopt-digests ------------------------------------------------------------


def complete_evidence() -> dict:
    return make_evidence(
        images={"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    )


def write_evidence(tmp_path: Path, evidence: dict) -> Path:
    path = tmp_path / "release-evidence.json"
    path.write_text(json.dumps(evidence))
    return path


def test_adopt_digests_emits_the_soaked_digests(promote_mod, tmp_path, monkeypatch, github_env):
    evidence = complete_evidence()
    install_rc_run(
        monkeypatch,
        promote_mod,
        tmp_path,
        evidence=evidence,
        dist_files={},
        soak_artifact=make_soak(evidence),
    )
    path = write_evidence(tmp_path, evidence)
    out = tmp_path / "github-output"
    code = promote_mod.main(
        [
            "adopt-digests",
            "--evidence",
            str(path),
            "--version",
            "1.0.0",
            "--rc-tag",
            "v1.0.0-rc1",
            "--soak-out",
            str(tmp_path / "soak-evidence" / "soak-evidence.json"),
            "--github-output",
            str(out),
        ]
    )
    assert code == 0
    text = out.read_text()
    assert f"engine_digest={ENGINE_DIGEST}\n" in text
    assert f"conductor_digest={CONDUCTOR_DIGEST}\n" in text
    assert f"rc_run_id={evidence['run_id']}\n" in text
    assert (tmp_path / "soak-evidence" / "soak-evidence.json").exists()


def test_adopt_digests_fails_closed_without_soak_evidence(
    promote_mod, tmp_path, monkeypatch, github_env
):
    """No soak artifact on the RC run -> promotion stops, loudly."""
    evidence = complete_evidence()
    install_rc_run(
        monkeypatch, promote_mod, tmp_path, evidence=evidence, dist_files={}, soak_artifact=None
    )
    path = write_evidence(tmp_path, evidence)
    with pytest.raises(SystemExit, match="soak-evidence"):
        promote_mod.main(
            [
                "adopt-digests",
                "--evidence",
                str(path),
                "--version",
                "1.0.0",
                "--rc-tag",
                "v1.0.0-rc1",
                "--soak-out",
                str(tmp_path / "soak-evidence" / "soak-evidence.json"),
            ]
        )


def test_adopt_digests_fails_closed_on_unrouted_invariant_findings(
    promote_mod, tmp_path, monkeypatch, github_env
):
    evidence = complete_evidence()
    soak = make_soak(evidence)
    soak["findings"].append({"id": "F-2", "invalidates_invariant": True})
    install_rc_run(
        monkeypatch, promote_mod, tmp_path, evidence=evidence, dist_files={}, soak_artifact=soak
    )
    path = write_evidence(tmp_path, evidence)
    assert (
        promote_mod.main(
            [
                "adopt-digests",
                "--evidence",
                str(path),
                "--version",
                "1.0.0",
                "--rc-tag",
                "v1.0.0-rc1",
                "--soak-out",
                str(tmp_path / "soak-evidence" / "soak-evidence.json"),
            ]
        )
        == 1
    )


# --- CLI: record-evidence / finalize-evidence ------------------------------------


@pytest.fixture
def candidate_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repo so the recorded commit/tree are genuine objects."""

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "RC test")
    git("config", "user.email", "rc@example.invalid")
    (tmp_path / "artifact.txt").write_text("candidate\n")
    git("add", ".")
    git("commit", "-qm", "candidate")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_record_evidence_freezes_the_candidate_identity(
    promote_mod, candidate_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    dist = candidate_repo / "dist"
    dist.mkdir()
    (dist / WHEEL_NAME).write_bytes(b"wheel-bytes")
    out = candidate_repo / "release-evidence.json"
    assert (
        promote_mod.main(
            [
                "record-evidence",
                "--tag",
                "v1.0.0-rc1",
                "--version",
                "1.0.0",
                "--dist",
                str(dist),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    record = json.loads(out.read_text())
    expected_tree = subprocess.check_output(
        ["git", "-C", str(candidate_repo), "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    assert record["tree"] == expected_tree
    assert record["wheels"] == {WHEEL_NAME: sha(WHEEL_NAME, b"wheel-bytes")}
    assert (
        promote_mod.validate_evidence(
            record, version="1.0.0", rc_tag="v1.0.0-rc1", tree=expected_tree
        )
        == []
    )


def test_record_evidence_refuses_an_empty_dist(promote_mod, candidate_repo: Path, tmp_path):
    assert (
        promote_mod.main(
            [
                "record-evidence",
                "--tag",
                "v1.0.0-rc1",
                "--version",
                "1.0.0",
                "--dist",
                str(tmp_path / "empty"),
                "--output",
                str(tmp_path / "x.json"),
            ]
        )
        == 1
    )


def test_finalize_evidence_binds_digests_and_promotion_linkage(promote_mod, tmp_path):
    path = write_evidence(tmp_path, make_evidence())
    out = tmp_path / "final.json"
    assert (
        promote_mod.main(
            [
                "finalize-evidence",
                "--evidence",
                str(path),
                "--engine-digest",
                ENGINE_DIGEST,
                "--conductor-digest",
                CONDUCTOR_DIGEST,
                "--adopted-from-rc-tag",
                "v1.0.0-rc1",
                "--adopted-from-run-id",
                "4242",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    record = json.loads(out.read_text())
    assert record["images"] == {"maistro-engine": ENGINE_DIGEST, "hive-conductor": CONDUCTOR_DIGEST}
    assert record["promotion"] == {
        "adopted_from_rc_tag": "v1.0.0-rc1",
        "adopted_from_run_id": 4242,
        "wheels_rebuilt": False,
        "images_rebuilt": False,
    }


def test_finalize_evidence_requires_complete_linkage(promote_mod, tmp_path):
    path = write_evidence(tmp_path, make_evidence())
    assert (
        promote_mod.main(
            [
                "finalize-evidence",
                "--evidence",
                str(path),
                "--engine-digest",
                ENGINE_DIGEST,
                "--conductor-digest",
                CONDUCTOR_DIGEST,
                "--adopted-from-rc-tag",
                "v1.0.0-rc1",
                "--output",
                str(tmp_path / "no-run-id.json"),
            ]
        )
        == 1
    )


def test_finalize_evidence_rejects_malformed_digests(promote_mod, tmp_path):
    path = write_evidence(tmp_path, make_evidence())
    assert (
        promote_mod.main(
            [
                "finalize-evidence",
                "--evidence",
                str(path),
                "--engine-digest",
                "sha256:short",
                "--conductor-digest",
                CONDUCTOR_DIGEST,
                "--output",
                str(tmp_path / "bad.json"),
            ]
        )
        == 1
    )


# --- the shipping workflow must actually wire this path --------------------------


def test_pypi_waits_for_the_soak_gate_before_irreversible_publication():
    """A passing wheels job must not race a failing images/soak job to PyPI."""
    import yaml

    jobs = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())["jobs"]
    pypi = jobs["pypi"]
    assert "images" in pypi["needs"], (
        "PyPI can publish before images rejects missing/failed soak evidence"
    )
    # GitHub's default success() dependency gate must not be bypassed.
    assert "if" not in pypi
    assert not jobs["images"].get("continue-on-error", False)
    steps = jobs["images"]["steps"]
    gate = next(s for s in steps if "adopt-digests" in s.get("run", ""))
    assert gate["if"] == "needs.guard.outputs.prerelease == 'false'"
    assert not gate.get("continue-on-error", False)
    publish = next(s for s in pypi["steps"] if "gh-action-pypi-publish" in s.get("uses", ""))
    assert "if" not in publish
    assert pypi["environment"]["name"] == "release"


def test_candidate_release_does_not_require_future_soak_evidence():
    """The RC release must finish before its soak can produce promotion evidence."""
    import yaml

    jobs = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())["jobs"]
    download = next(
        s
        for s in jobs["github-release"]["steps"]
        if s.get("uses", "").startswith("actions/download-artifact")
        and s["with"]["name"] == "soak-evidence"
    )
    assert download.get("if") == "needs.guard.outputs.prerelease == 'false'", (
        "RC runs have no soak artifact yet; only finals must download it"
    )
    assert "if-no-files-found" not in download["with"], (
        "download-artifact has no skip-missing input; finals must fail if evidence is absent"
    )
    assert not download.get("continue-on-error", False)


def test_shipping_workflow_promotes_rc_artifacts_on_finals():
    import yaml

    workflow = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())
    jobs = workflow["jobs"]
    guard_step = next(s for s in jobs["guard"]["steps"] if s.get("id") == "guard")
    assert "--verify-rc-tree" in guard_step["run"]
    assert "steps.guard.outputs.rc_tag" in jobs["guard"]["outputs"]["rc_tag"]

    wheels = jobs["wheels"]["steps"]
    build = next(s for s in wheels if s.get("name", "").startswith("Build sdist + wheel"))
    adopt_wheels = next(
        s for s in wheels if "promote_release.py" in s.get("run", "") and "adopt-wheels" in s["run"]
    )
    assert build["if"] == "needs.guard.outputs.prerelease == 'true'", (
        "finals must not rebuild wheels"
    )
    assert adopt_wheels["if"] == "needs.guard.outputs.prerelease == 'false'"

    images = jobs["images"]
    assert images["permissions"].get("actions") == "read", "adopting needs the RC run's artifacts"
    image_steps = images["steps"]
    build_steps = [
        s for s in image_steps if s.get("uses", "").startswith("docker/build-push-action")
    ]
    assert build_steps, "RC runs must still build into quarantine"
    for step in build_steps:
        assert step["if"] == "needs.guard.outputs.prerelease == 'true'", (
            f"{step.get('name')}: finals must not build images"
        )
    adopt_digests = next(s for s in image_steps if "adopt-digests" in s.get("run", ""))
    assert adopt_digests["if"] == "needs.guard.outputs.prerelease == 'false'"
    assert adopt_digests["id"] == "rc_evidence"

    # Every digest consumer binds to the built digest on RC runs and falls
    # through to the adopted digest on finals.
    promote_chunk = next(s for s in image_steps if "imagetools create" in s.get("run", ""))
    assert "steps.engine.outputs.digest || steps.rc_evidence.outputs.engine_digest" in json.dumps(
        promote_chunk
    )
    evidence_uploads = [
        s
        for s in image_steps
        if s.get("uses", "").startswith("actions/upload-artifact")
        and "soak-evidence" in json.dumps(s)
    ]
    assert evidence_uploads, "the final run must publish the soak evidence it promoted on"
