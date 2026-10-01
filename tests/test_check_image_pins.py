"""Tests for the image digest-pin gate (#349).

The gap this closes is drift, not absence: every Dockerfile already named a
base, but the bases floated on mutable tags and the uv installer came from a
`:latest` image, so a registry tag move changed what every build installs
without a repository diff. These tests pin the gate's two closed loops — the
tree must be fully digest-pinned with every pin registered
(`quality/image-pins.json`), and the registry must name nothing the tree does
not build — plus the release-side helper that proves a provenance attestation
names every base digest.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-image-pins.py"

DIGEST = "sha256:" + "aa" * 32
OTHER_DIGEST = "sha256:" + "bb" * 32


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_image_pins", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tree(
    tmp_path: Path,
    dockerfiles: dict[str, str],
    pins: list[dict[str, object]],
    exemptions: list[dict[str, object]] | None = None,
    inventory: dict[str, str] | None = None,
) -> Path:
    """A repo-shaped tree: Dockerfiles, the pin registry, the inventory."""
    (tmp_path / "quality").mkdir(exist_ok=True)
    (tmp_path / "quality" / "image-pins.json").write_text(
        json.dumps({"pins": pins, "exemptions": exemptions or []}), encoding="utf-8"
    )
    dispositions = inventory or dict.fromkeys(dockerfiles, "PUBLISHED")
    (tmp_path / "quality" / "image-inventory.json").write_text(
        json.dumps(
            {
                "images": [
                    {"id": name, "dockerfile": name, "disposition": disposition}
                    for name, disposition in dispositions.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    for name, text in dockerfiles.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _pin(**overrides: object) -> dict[str, object]:
    row = {
        "image": "python",
        "tag": "3.13.1-slim",
        "digest": DIGEST,
        "recorded": "2026-09-30",
        "recorded_in": "#349",
        "used_by": ["Dockerfile"],
    }
    row.update(overrides)
    return row


def hex_of(digest: str) -> str:
    """The bare hex of a `sha256:<hex>` digest, for building fixture refs."""
    return digest.split(":", 1)[1]


def _run(gate, tmp_path: Path, monkeypatch) -> int:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "PINS", tmp_path / "quality" / "image-pins.json")
    monkeypatch.setattr(gate, "INVENTORY", tmp_path / "quality" / "image-inventory.json")
    return gate.main()


PINNED = (
    "FROM python:3.13.1-slim@sha256:{d} AS builder\n"
    "RUN true\n"
    "FROM python:3.13.1-slim@sha256:{d}\n"
    "COPY --from=docker:29-cli@sha256:{d2} /usr/local/bin/docker /usr/local/bin/docker\n"
)


def test_fully_pinned_tree_passes(gate, tmp_path, monkeypatch):
    tree = _tree(
        tmp_path,
        {"Dockerfile": PINNED.format(d=hex_of(DIGEST), d2=hex_of(OTHER_DIGEST))},
        [
            _pin(),
            _pin(image="docker", tag="29-cli", digest=OTHER_DIGEST),
        ],
    )
    assert _run(gate, tree, monkeypatch) == 0


def test_explicit_latest_is_rejected(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path, {"Dockerfile": "FROM python:latest\n"}, [])
    assert _run(gate, tree, monkeypatch) == 1
    assert "resolves to `:latest`" in capsys.readouterr().err


def test_bare_image_name_is_implicit_latest(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path, {"Dockerfile": "FROM python\n"}, [])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no digest and no tag" in capsys.readouterr().err


def test_unpinned_release_base_fails(gate, tmp_path, monkeypatch, capsys):
    """The exact shape this issue exists to kill: a mutable base tag."""
    tree = _tree(tmp_path, {"Dockerfile": "FROM python:3.13.1-slim\n"}, [])
    assert _run(gate, tree, monkeypatch) == 1
    assert "must pin python by" in capsys.readouterr().err


def test_unpinned_internal_base_needs_an_owned_exemption(gate, tmp_path, monkeypatch, capsys):
    df = "Dockerfile.tests"
    tree = _tree(tmp_path, {df: "FROM python:3.13.1-slim\n"}, [], inventory={df: "INTERNAL"})
    assert _run(gate, tree, monkeypatch) == 1
    assert "owned, issue-numbered exemption" in capsys.readouterr().err

    exempted = _tree(
        tmp_path,
        {df: "FROM python:3.13.1-slim\n"},
        [],
        exemptions=[
            {
                "file": df,
                "ref": "python:3.13.1-slim",
                "owner": "@someone",
                "issue": "#349",
                "reason": "version-scoped test image",
            }
        ],
        inventory={df: "INTERNAL"},
    )
    assert _run(gate, exempted, monkeypatch) == 0


def test_exemption_without_owner_issue_reason_is_rejected(gate, tmp_path, monkeypatch, capsys):
    """A `file`+`ref`-only row must not silently waive the pin rule."""
    df = "Dockerfile.tests"
    cases = [
        {"file": df, "ref": "python:3.13.1-slim"},
        {"file": df, "ref": "python:3.13.1-slim", "owner": "@someone", "issue": "#349"},
    ]
    for exemption in cases:
        tree = _tree(
            tmp_path,
            {df: "FROM python:3.13.1-slim\n"},
            [],
            exemptions=[exemption],
            inventory={df: "INTERNAL"},
        )
        assert _run(gate, tree, monkeypatch) == 1
        err = capsys.readouterr().err
        assert "missing required field(s)" in err
        assert "unowned exemption is just permission" in err


def test_exemption_cannot_waive_a_release_scoped_dockerfile(gate, tmp_path, monkeypatch, capsys):
    """Exemptions are INTERNAL-only; a published image must pin, period."""
    tree = _tree(
        tmp_path,
        {"Dockerfile": "FROM python:3.13.1-slim\n"},
        [],
        exemptions=[
            {
                "file": "Dockerfile",
                "ref": "python:3.13.1-slim",
                "owner": "@someone",
                "issue": "#349",
                "reason": "trying to dodge the release contract",
            }
        ],
    )
    assert _run(gate, tree, monkeypatch) == 1
    err = capsys.readouterr().err
    assert "INTERNAL images only" in err
    assert "must pin python by" in err


def test_unregistered_digest_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(
        tmp_path,
        {"Dockerfile": PINNED.format(d=hex_of(DIGEST), d2=hex_of(DIGEST))},
        [_pin()],  # no docker:29-cli row
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "not registered in quality/image-pins.json" in capsys.readouterr().err


def test_annotation_drift_fails(gate, tmp_path, monkeypatch, capsys):
    """A digest bump that quietly rewrites the human-readable tag."""
    tree = _tree(
        tmp_path,
        {"Dockerfile": PINNED.format(d=hex_of(DIGEST), d2=hex_of(DIGEST))},
        [_pin(), _pin(image="docker", tag="30-cli", digest=DIGEST)],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "annotation drift" in capsys.readouterr().err


def test_used_by_drift_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(
        tmp_path,
        {"Dockerfile": PINNED.format(d=hex_of(DIGEST), d2=hex_of(DIGEST))},
        [_pin(used_by=["somewhere/else/Dockerfile"])],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "used_by drift" in capsys.readouterr().err


def test_unused_pin_row_fails(gate, tmp_path, monkeypatch, capsys):
    """The registry cannot rot into pins nothing builds anymore."""
    tree = _tree(
        tmp_path,
        {"Dockerfile": "FROM python:3.13.1-slim@sha256:" + hex_of(DIGEST) + "\n"},
        [_pin(), _pin(image="golang", tag="1.25.13-alpine", digest=OTHER_DIGEST)],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "not referenced by any Dockerfile" in capsys.readouterr().err


def test_a_latest_row_in_the_registry_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(
        tmp_path,
        {"Dockerfile": "FROM python:3.13.1-slim@sha256:" + hex_of(DIGEST) + "\n"},
        [_pin(tag="latest")],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "records a `latest` tag" in capsys.readouterr().err


def test_malformed_digest_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(
        tmp_path,
        {"Dockerfile": "FROM python:3.13.1-slim@sha256:not-a-digest\n"},
        [],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "malformed digest" in capsys.readouterr().err


def test_digest_pinned_latest_annotation_fails(gate, tmp_path, monkeypatch, capsys):
    """Immutable, yes — but `latest` is not a reviewable version annotation."""
    tree = _tree(
        tmp_path,
        {"Dockerfile": "FROM python:latest@sha256:" + hex_of(DIGEST) + "\n"},
        [],
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "missing or `latest`" in capsys.readouterr().err


def test_stage_references_are_not_external_images(gate, tmp_path, monkeypatch):
    df = (
        "FROM python:3.13.1-slim@sha256:" + hex_of(DIGEST) + " AS builder\n"
        "RUN true\n"
        "COPY --from=builder /out /out\n"
        "COPY --from=0 /out2 /out2\n"
        "FROM scratch\n"
        "COPY --from=builder /x /x\n"
    )
    tree = _tree(tmp_path, {"Dockerfile": df}, [_pin()])
    assert _run(gate, tree, monkeypatch) == 0


def test_from_alias_identical_to_base_is_still_pinned(gate, tmp_path, monkeypatch):
    """`FROM ubuntu AS ubuntu` must not classify its external base as a stage:
    the alias (and index) register only after the ref is judged against
    previously declared stages, or the gate passes with zero pins."""
    tree = _tree(tmp_path, {"Dockerfile": "FROM ubuntu AS ubuntu\nRUN true\n"}, [])
    assert _run(gate, tree, monkeypatch) == 1


def test_first_stage_index_zero_is_not_a_stage_reference(gate, tmp_path, monkeypatch):
    """`FROM 0` is the first stage: no earlier stage exists, so the digit
    must be treated as an external (unpinnable) ref, not skipped."""
    tree = _tree(tmp_path, {"Dockerfile": "FROM 0\nRUN true\n"}, [])
    assert _run(gate, tree, monkeypatch) == 1


def test_conditional_copier_template_is_discovered(gate, tmp_path, monkeypatch, capsys):
    """Copier conditional filenames (`{% if %}Dockerfile{% endif %}.jinja`) must
    be discovered by their name containing `Dockerfile`, not by the
    `Dockerfile*` prefix, or a shipped scaffold stays outside the gate."""
    name = "templates/single-tenant-multi-user/{% if host_target in ['docker', 'podman'] %}Dockerfile{% endif %}.jinja"
    tree = _tree(tmp_path, {name: "FROM python:3.13.1-slim\n"}, [_pin()])
    monkeypatch.setattr(gate, "ROOT", tree)
    assert _run(gate, tree, monkeypatch) == 1
    assert name in capsys.readouterr().err


def test_base_digests_lists_pinned_refs(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(
        tmp_path,
        {"Dockerfile": PINNED.format(d=hex_of(DIGEST), d2=hex_of(OTHER_DIGEST))},
        [],
    )
    monkeypatch.setattr(gate, "ROOT", tree)
    refs = gate.base_digests(["Dockerfile"])
    assert refs == [
        f"docker:29-cli@{OTHER_DIGEST}",
        f"python:3.13.1-slim@{DIGEST}",
    ]
    capsys.readouterr()


def test_base_digests_refuses_unpinned(gate, tmp_path, monkeypatch):
    tree = _tree(tmp_path, {"Dockerfile": "FROM python:3.13.1-slim\n"}, [])
    monkeypatch.setattr(gate, "ROOT", tree)
    with pytest.raises(SystemExit, match="not digest-pinned"):
        gate.base_digests(["Dockerfile"])


def _attestation_records(digest_hexes: list[str]) -> str:
    """NDJSON shaped exactly like `cosign download attestation` output."""
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "resolvedDependencies": [
                    {"uri": f"pkg:docker/python@sha256:{h}", "digest": {"sha256": h}}
                    for h in digest_hexes
                ]
            }
        },
    }
    # `cosign download attestation` NDJSON: record.payload decodes straight
    # to the in-toto statement (no synthetic outer envelope).
    record = {"payload": base64.b64encode(json.dumps(statement).encode()).decode()}
    return json.dumps(record) + "\n"


def test_attestation_check(gate, tmp_path, monkeypatch):
    """The release-side proof: every pinned base digest named by provenance."""
    df = "Dockerfile"
    tree = _tree(
        tmp_path,
        {df: PINNED.format(d=hex_of(DIGEST), d2=hex_of(OTHER_DIGEST))},
        [],
    )
    monkeypatch.setattr(gate, "ROOT", tree)

    good = tree / "att.json"
    good.write_text(
        _attestation_records([hex_of(DIGEST), hex_of(OTHER_DIGEST)]),
        encoding="utf-8",
    )
    assert gate.verify_attestation(str(good), df) == 0

    # One base missing from provenance = the release ships a base the
    # attestation cannot speak for.
    bad = tree / "bad.json"
    bad.write_text(_attestation_records([hex_of(DIGEST)]), encoding="utf-8")
    assert gate.verify_attestation(str(bad), df) == 1

    # Not cosign output at all must fail loudly, never pass vacuously.
    junk = tree / "junk.json"
    junk.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="not a cosign attestation"):
        gate.verify_attestation(str(junk), df)


def _nonslsa_record(digest_hex: str) -> str:
    """A non-provenance attestation whose free-text fields name the digest."""
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://spdx.dev/Document",
        "predicate": {
            "notes": f"built from sha256:{digest_hex}",
            "packages": [{"name": "python", "versionInfo": f"sha256:{digest_hex}"}],
        },
    }
    record = {"payload": base64.b64encode(json.dumps(statement).encode()).decode()}
    return json.dumps(record) + "\n"


def _unrelated_field_record(digest_hex: str) -> str:
    """SLSA provenance naming the digest everywhere but resolvedDependencies."""
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {"externalParameters": {"base": f"sha256:{digest_hex}"}},
            "resolvedDependencies": [
                {
                    "uri": "pkg:docker/alpine@sha256:" + hex_of(OTHER_DIGEST),
                    "digest": {"sha256": hex_of(OTHER_DIGEST)},
                }
            ],
        },
    }
    record = {"payload": base64.b64encode(json.dumps(statement).encode()).decode()}
    return json.dumps(record) + "\n"


def test_attestation_ignores_digest_outside_slsa_resolved_dependencies(gate, tmp_path, monkeypatch):
    """Only structured resolvedDependencies digests prove base coverage."""
    df = "Dockerfile"
    tree = _tree(tmp_path, {df: PINNED.format(d=hex_of(DIGEST), d2=hex_of(DIGEST))}, [])
    monkeypatch.setattr(gate, "ROOT", tree)

    # A non-SLSA record mentioning the digest must not satisfy the check.
    nonslsa = tree / "nonslsa.json"
    nonslsa.write_text(_nonslsa_record(hex_of(DIGEST)), encoding="utf-8")
    assert gate.verify_attestation(str(nonslsa), df) == 1

    # Nor may a SLSA statement that names it outside resolvedDependencies.
    unrelated = tree / "unrelated.json"
    unrelated.write_text(_unrelated_field_record(hex_of(DIGEST)), encoding="utf-8")
    assert gate.verify_attestation(str(unrelated), df) == 1
