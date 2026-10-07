"""Tests for the shipped-image inventory gate (#346, #611).

The gap this closes is not "some image had a CVE" -- it is that nothing
enumerated the images, so coverage was whatever `security.yml` happened to
name and nobody could tell. These pin the two directions that make the set
closed (a Dockerfile with no entry fails, an entry with no Dockerfile fails)
and the checks that make the inventory more than a document: a shipped entry
must name jobs that actually exist, and a PUBLISHED entry claiming
`published_digest_verified: true` must show the wiring that makes the claim
true -- build once, scan the built digest, apply the release tags to it after
the scans, and sign it (#611).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-image-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_image_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKFLOW = """\
name: demo
on: [push]
jobs:
  containers:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
  other-job:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


def _tree(tmp_path: Path, images: list[dict[str, object]], dockerfiles: list[str]) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "security.yml").write_text(WORKFLOW, encoding="utf-8")
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality" / "image-inventory.json").write_text(
        json.dumps({"images": images}), encoding="utf-8"
    )
    for name in dockerfiles:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("FROM scratch\n", encoding="utf-8")
    return tmp_path


def _run(gate, tmp_path: Path, monkeypatch) -> int:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "INVENTORY", tmp_path / "quality" / "image-inventory.json")
    monkeypatch.setattr(gate, "WORKFLOWS", tmp_path / ".github" / "workflows")
    return gate.main()


SHIPPED = {
    "id": "demo",
    "dockerfile": "Dockerfile",
    "disposition": "PUBLISHED",
    "rationale": "the one image",
    "built_by": [".github/workflows/security.yml:containers"],
    "scanned_by": [".github/workflows/security.yml:containers"],
    "published_by": ".github/workflows/security.yml:containers",
    "published_digest_verified": False,
}


def test_a_matching_inventory_passes(gate, tmp_path, monkeypatch):
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 0


def test_a_dockerfile_with_no_entry_fails(gate, tmp_path, monkeypatch, capsys):
    """The failure #346 is actually about. `Dockerfile.research` existed and
    was unscanned; nothing said so because nothing enumerated the images."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile", "Dockerfile.research"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "Dockerfile.research: on disk, not in the inventory" in capsys.readouterr().out


def test_an_entry_with_no_dockerfile_fails(gate, tmp_path, monkeypatch, capsys):
    """Otherwise the inventory rots into a list of things that used to exist,
    and its counts start describing a repository nobody has."""
    tree = _tree(tmp_path, [SHIPPED], [])
    assert _run(gate, tree, monkeypatch) == 1
    assert "Dockerfile: in the inventory, not on disk" in capsys.readouterr().out


def test_a_shipped_entry_naming_a_job_that_does_not_exist_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """The check that makes this more than a document.

    "Add the image to the list" is cheap, and would let a coverage claim drift
    from coverage exactly the way the unscanned images did. Naming a job that
    has to exist is what costs something.
    """
    entry = {**SHIPPED, "scanned_by": [".github/workflows/security.yml:no-such-job"]}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "declares no job 'no-such-job'" in capsys.readouterr().out


def test_a_shipped_entry_with_no_scan_job_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "scanned_by": []}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `scanned_by` job" in capsys.readouterr().out


def test_a_published_entry_with_no_publisher_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "published_by": None}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `published_by` job" in capsys.readouterr().out


def test_an_internal_entry_needs_no_jobs_but_needs_a_reason(gate, tmp_path, monkeypatch, capsys):
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "INTERNAL",
        "rationale": "",
        "built_by": [],
        "scanned_by": [],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no rationale" in capsys.readouterr().out


def test_an_internal_entry_that_claims_a_scan_job_fails(gate, tmp_path, monkeypatch, capsys):
    """A scanned image is DISTRIBUTED or PUBLISHED. Letting INTERNAL claim a
    scan would give the cheapest disposition the strongest-looking evidence."""
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "INTERNAL",
        "rationale": "test harness only",
        "built_by": [],
        "scanned_by": [".github/workflows/security.yml:containers"],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "entries name no scanned_by" in capsys.readouterr().out


def test_a_retired_entry_must_name_a_successor_and_an_owner(gate, tmp_path, monkeypatch, capsys):
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "RETIRED",
        "rationale": "superseded",
        "built_by": [],
        "scanned_by": [],
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "RETIRED needs `replaced_by`" in out
    assert "RETIRED needs `removal_owner`" in out


def test_a_shipped_entry_may_lack_jobs_behind_an_owned_exception(gate, tmp_path, monkeypatch):
    """#346's AC-4. The sbx template is the real case: CI cannot build it from a
    checkout, and calling it INTERNAL to dodge the requirement is what hid it."""
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "DISTRIBUTED",
        "rationale": "operator builds and may push it",
        "built_by": [],
        "scanned_by": [],
        "coverage_exception": {
            "owner": "@someone",
            "issue": "#346",
            "reason": "needs a preseed step CI does not run yet",
        },
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 0


def test_an_exception_without_an_owner_is_an_exemption(gate, tmp_path, monkeypatch, capsys):
    """The cheapest thing to write must not be the thing that satisfies it."""
    entry = {
        "id": "demo",
        "dockerfile": "Dockerfile",
        "disposition": "DISTRIBUTED",
        "rationale": "operator builds it",
        "built_by": [],
        "scanned_by": [],
        "coverage_exception": {"owner": "", "issue": "", "reason": "later"},
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "needs `owner`" in out
    assert "needs `issue`" in out


def test_a_published_entry_must_state_whether_the_released_digest_was_scanned(
    gate, tmp_path, monkeypatch, capsys
):
    """The one thing job names cannot show.

    security.yml scans a locally-built candidate tag; release.yml rebuilds and
    publishes its own digest. Accepting the publisher job as proof would let
    "the dependency set scanned is the dependency set shipped" read as verified
    when nothing checks it.
    """
    entry = {key: value for key, value in SHIPPED.items() if key != "published_digest_verified"}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "must state `published_digest_verified`" in capsys.readouterr().out


# ── #611: the `published_digest_verified: true` claim is machine-checked ────
#
# A release that rebuilds what it scanned publishes an artifact the scan never
# admitted. The gate now reads the publishing job's wiring, so these pin the
# shape it demands and every way of faking it.

RELEASE_WIRING = """\
name: release
on:
  push:
    tags: ["v*"]
jobs:
  images:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Build candidate
        id: engine
        uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}
      - name: Scan candidate
        uses: aquasecurity/trivy-action@ed142fd
        with:
          image-ref: ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}
          exit-code: "1"
      - name: Promote the scanned digest
        run: docker buildx imagetools create -t ghcr.io/example/maistro-engine:v1 ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}
      - name: Sign the pushed digest
        run: cosign sign ghcr.io/example/maistro-engine@${{ steps.engine.outputs.digest }}
"""


def _release_tree(tmp_path: Path, workflow: str, verified: object) -> Path:
    entry = {
        **SHIPPED,
        "built_by": [".github/workflows/release.yml:images"],
        "scanned_by": [".github/workflows/release.yml:images"],
        "published_by": ".github/workflows/release.yml:images",
        "published_digest_verified": verified,
    }
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    (tree / ".github" / "workflows" / "release.yml").write_text(workflow, encoding="utf-8")
    return tree


def test_true_with_the_full_wiring_passes(gate, tmp_path, monkeypatch):
    """Build once into a quarantine, scan the built digest, promote it, sign
    it: the claim is true and the gate can see it."""
    tree = _release_tree(tmp_path, RELEASE_WIRING, True)
    assert _run(gate, tree, monkeypatch) == 0


def test_true_without_a_scan_of_the_built_digest_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace("steps.engine.outputs.digest", "steps.engine.outputs.version"),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "never scans `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_with_a_reporting_step_that_merely_names_the_scanner_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """Naming trivy is not scanning.

    A step that echoes the digest under a `Report Trivy target` name checks
    the vocabulary box while gating nothing; it must not stand in for the
    scan that admits the digest.
    """
    scan_block = (
        "      - name: Scan candidate\n"
        "        uses: aquasecurity/trivy-action@ed142fd\n"
        "        with:\n"
        "          image-ref: ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}\n"
        '          exit-code: "1"\n'
    )
    report_block = (
        "      - name: Report Trivy target\n"
        '        run: echo "Trivy target: ${{ steps.engine.outputs.digest }}"\n'
    )
    tree = _release_tree(tmp_path, RELEASE_WIRING.replace(scan_block, report_block), True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "never scans `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_with_a_trivy_scan_configured_not_to_fail_fails(gate, tmp_path, monkeypatch, capsys):
    """`exit-code: "0"` reports findings; it does not gate them."""
    tree = _release_tree(tmp_path, RELEASE_WIRING.replace('exit-code: "1"', 'exit-code: "0"'), True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "never scans `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_with_a_scan_allowed_to_fail_fails(gate, tmp_path, monkeypatch, capsys):
    """`continue-on-error: true` turns the gate into a note."""
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "      - name: Scan candidate\n",
            "      - name: Scan candidate\n        continue-on-error: true\n",
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "never scans `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_with_a_cli_scan_without_the_failing_flag_fails(gate, tmp_path, monkeypatch, capsys):
    """A grype invocation without `--fail-on` scans and admits anything."""
    scan_block = (
        "      - name: Scan candidate\n"
        "        uses: aquasecurity/trivy-action@ed142fd\n"
        "        with:\n"
        "          image-ref: ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}\n"
        '          exit-code: "1"\n'
    )
    grype_block = (
        "      - name: Grype scan (report only)\n"
        "        run: grype ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}"
        " --output table\n"
    )
    tree = _release_tree(tmp_path, RELEASE_WIRING.replace(scan_block, grype_block), True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "never scans `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_without_tag_application_fails(gate, tmp_path, monkeypatch, capsys):
    """Publishing tags that were never pointed at the scanned digest is the
    original gap: an image id in a job name proved nothing."""
    workflow = "\n".join(
        line for line in RELEASE_WIRING.splitlines() if "imagetools create" not in line
    )
    tree = _release_tree(tmp_path, workflow, True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "never applies the release tags" in capsys.readouterr().out


def test_true_without_a_signature_of_the_scanned_digest_fails(gate, tmp_path, monkeypatch, capsys):
    workflow = "\n".join(line for line in RELEASE_WIRING.splitlines() if "cosign sign" not in line)
    tree = _release_tree(tmp_path, workflow, True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `cosign sign` of `steps.engine.outputs.digest`" in capsys.readouterr().out


def test_true_with_tags_applied_before_the_scan_fails(gate, tmp_path, monkeypatch, capsys):
    """Ordering is the property: a finding at the gating severity must stop
    the publish, not arrive after the tags already moved."""
    promote_block = (
        "      - name: Promote the scanned digest\n"
        "        run: docker buildx imagetools create -t ghcr.io/example/maistro-engine:v1 "
        "ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}\n"
    )
    scan_block = (
        "      - name: Scan candidate\n"
        "        uses: aquasecurity/trivy-action@ed142fd\n"
        "        with:\n"
        "          image-ref: ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}\n"
        '          exit-code: "1"\n'
    )
    workflow = RELEASE_WIRING.replace(promote_block, "").replace(
        scan_block, promote_block + scan_block
    )
    tree = _release_tree(tmp_path, workflow, True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "applies release tags before its scans" in capsys.readouterr().out


def test_true_with_the_build_pushing_latest_at_build_time_fails(
    gate, tmp_path, monkeypatch, capsys
):
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "maistro-engine-rc:rc-${{ github.run_id }}", "maistro-engine:latest"
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "pushes `:latest` at build time" in capsys.readouterr().out


def test_true_with_the_build_consuming_computed_release_tags_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """The pre-#611 shape: the build itself tagged the release. Whatever else
    the job does, the digest was published before any scan could reject it."""
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "tags: ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}",
            "tags: ${{ steps.tags.outputs.engine }}",
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "consumes computed release tags" in capsys.readouterr().out


def test_true_with_the_build_pushing_a_release_tag_directly_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """Any non-quarantine build destination publishes before the scan.

    `:latest` is only one shape. A build that pushes the immutable version tag
    itself — `tags: ghcr.io/example/maistro-engine:${{ github.ref_name }}` —
    makes the release public before any scan could reject it, and a later
    `imagetools create` cannot un-publish it. The check confines every build
    destination to a `-rc` quarantine repository instead of enumerating the
    tag shapes it happens to forbid today.
    """
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}",
            "ghcr.io/example/maistro-engine:${{ github.ref_name }}",
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert (
        "pushes 'ghcr.io/example/maistro-engine:${{ github.ref_name }}' outside a "
        "`-rc` quarantine repository" in capsys.readouterr().out
    )


def test_true_with_a_mixed_block_scalar_tags_fails(gate, tmp_path, monkeypatch, capsys):
    """The quarantine rule reads block-scalar `tags:` lists destination by
    destination — one production repo smuggled in beside a quarantine repo is
    still a publish at build time."""
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "tags: ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}",
            "tags: |\n"
            "            ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}\n"
            "            ghcr.io/example/maistro-engine:v1\n",
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "outside a `-rc` quarantine repository" in capsys.readouterr().out


def test_true_with_an_all_quarantine_block_scalar_tags_passes(gate, tmp_path, monkeypatch):
    """The block-scalar spelling of the real wiring must not read as a
    violation: every destination ends in `-rc`, so nothing is published
    before the scans."""
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace(
            "tags: ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}",
            "tags: |\n"
            "            ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}\n"
            "            ghcr.io/example/maistro-engine-rc:candidate\n",
        ),
        True,
    )
    assert _run(gate, tree, monkeypatch) == 0


SIBLING_WORKFLOW = """
name: release
on:
  push:
    tags: ["v*"]
jobs:
  images:
    runs-on: ubuntu-latest
    steps:
      - name: Build candidate
        id: engine
        uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: ghcr.io/example/maistro-engine-rc:rc-${{ github.run_id }}
  after:
    runs-on: ubuntu-latest
    steps:
      - name: Scan candidate
        uses: aquasecurity/trivy-action@ed142fd
        with:
          image-ref: ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}
          exit-code: "1"
      - name: Promote the scanned digest
        run: docker buildx imagetools create -t ghcr.io/example/maistro-engine:v1 ghcr.io/example/maistro-engine-rc@${{ steps.engine.outputs.digest }}
      - name: Sign the pushed digest
        run: cosign sign ghcr.io/example/maistro-engine@${{ steps.engine.outputs.digest }}
"""


def test_the_scan_of_a_later_job_does_not_satisfy_this_jobs_claim(
    gate, tmp_path, monkeypatch, capsys
):
    """Steps belong to their own job, not to the job that happens to precede
    them.

    A job block that ran to end-of-file would read the next job's steps as
    this job's, so a publishing job that never scanned, promoted or signed
    could pass by borrowing a later job's wiring — two independent jobs
    jointly satisfying what the publishing job must do alone.
    """
    tree = _release_tree(tmp_path, SIBLING_WORKFLOW, True)
    assert _run(gate, tree, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "never scans `steps.engine.outputs.digest`" in out
    assert "never applies the release tags" in out
    assert "no `cosign sign` of `steps.engine.outputs.digest`" in out


def test_a_job_followed_by_a_sibling_still_reads_its_own_steps(gate, tmp_path, monkeypatch):
    """The sibling bound must not cut the other way either: the full wiring in
    the FIRST of two jobs must still be visible when a second job follows it."""
    tree = _release_tree(tmp_path, RELEASE_WIRING + "  later:\n    runs-on: ubuntu-latest\n", True)
    assert _run(gate, tree, monkeypatch) == 0


def test_true_with_no_build_step_fails(gate, tmp_path, monkeypatch, capsys):
    workflow = "\n".join(
        line for line in RELEASE_WIRING.splitlines() if "build-push-action" not in line
    )
    tree = _release_tree(tmp_path, workflow, True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "pushes no docker/build-push-action step" in capsys.readouterr().out


def test_true_with_an_unidentified_build_step_fails(gate, tmp_path, monkeypatch, capsys):
    """A push with no `id:` exports no digest anyone can bind to, so no scan
    could ever be tied to it."""
    tree = _release_tree(tmp_path, RELEASE_WIRING.replace("        id: engine\n", ""), True)
    assert _run(gate, tree, monkeypatch) == 1
    assert "declares no `id:`" in capsys.readouterr().out


def test_true_in_a_job_with_no_steps_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _release_tree(
        tmp_path,
        "name: release\non: [push]\njobs:\n  images:\n    runs-on: ubuntu-latest\n",
        True,
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "declares no steps for job 'images'" in capsys.readouterr().out


def test_false_records_the_gap_without_demanding_the_wiring(gate, tmp_path, monkeypatch):
    """`false` is the honest state of a release path that has not been wired
    yet -- recording it must stay possible, or nobody flips it honestly."""
    tree = _release_tree(
        tmp_path,
        RELEASE_WIRING.replace("docker/build-push-action@v7", "build/other@v1"),
        False,
    )
    assert _run(gate, tree, monkeypatch) == 0


def test_a_non_boolean_flag_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _release_tree(tmp_path, RELEASE_WIRING, "yes")
    assert _run(gate, tree, monkeypatch) == 1
    assert "must be JSON true or false" in capsys.readouterr().out


def test_the_real_release_wiring_carries_both_claims(gate, capsys):
    """Not a unit test of the gate — both published entries now claim
    `published_digest_verified: true`, so the gate's wiring read of the real
    release.yml must hold. This is the test that fails if someone rewires the
    release back to publish-before-scan without re-recording the claim."""
    assert gate.main() == 0
    assert "PUBLISHED   : 2" in capsys.readouterr().out


def test_an_unknown_disposition_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "disposition": "PROBABLY_FINE"}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "is not one of" in capsys.readouterr().out


def test_dockerignore_files_are_not_images(gate, tmp_path, monkeypatch):
    """`Dockerfile.rsi-runner.dockerignore` sits beside its Dockerfile and
    matches `Dockerfile*`. It configures a build; it is not one."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile", "Dockerfile.rsi-runner.dockerignore"])
    assert _run(gate, tree, monkeypatch) == 0


def test_the_real_inventory_matches_the_real_repository(gate):
    """Not a unit test of the gate — the gate run against this repository.

    Everything above uses a synthetic tree, which proves the logic and proves
    nothing about the tree that ships.
    """
    assert gate.main() == 0


# ── the gate's own edges ──────────────────────────────────────────


def test_a_directory_named_dockerfile_is_not_an_image(gate, tmp_path, monkeypatch):
    """`rglob` matches directories too, and a `Dockerfile.d/` would otherwise
    read as an image nobody could build."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    (tree / "Dockerfile.d").mkdir()
    assert _run(gate, tree, monkeypatch) == 0


def test_vendored_trees_are_not_scanned(gate, tmp_path, monkeypatch):
    """A Dockerfile inside node_modules or a virtualenv belongs to a dependency.
    Demanding a disposition for it would make the gate unusable the first time
    someone installs a package that ships one."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    (tree / "node_modules" / "pkg").mkdir(parents=True)
    (tree / "node_modules" / "pkg" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert _run(gate, tree, monkeypatch) == 0


def test_a_malformed_job_reference_says_what_shape_it_wanted(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "built_by": ["security.yml"]}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "is not `<workflow path>:<job id>`" in capsys.readouterr().out


def test_a_reference_to_a_workflow_that_does_not_exist_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "built_by": [".github/workflows/gone.yml:containers"]}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "gone.yml does not exist" in capsys.readouterr().out


def test_a_shipped_entry_with_no_build_job_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {**SHIPPED, "built_by": []}
    tree = _tree(tmp_path, [entry], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `built_by` job and no `coverage_exception`" in capsys.readouterr().out


def test_an_entry_with_no_dockerfile_key_fails(gate, tmp_path, monkeypatch, capsys):
    entry = {"id": "nameless", "disposition": "INTERNAL", "rationale": "x"}
    tree = _tree(tmp_path, [entry, SHIPPED], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "no `dockerfile`" in capsys.readouterr().out


def test_the_same_dockerfile_listed_twice_fails(gate, tmp_path, monkeypatch, capsys):
    """Two entries for one image means two dispositions, and the second would
    silently lose — including if it were the stricter one."""
    softer = {
        "id": "demo-again",
        "dockerfile": "Dockerfile",
        "disposition": "INTERNAL",
        "rationale": "second opinion",
    }
    tree = _tree(tmp_path, [SHIPPED, softer], ["Dockerfile"])
    assert _run(gate, tree, monkeypatch) == 1
    assert "listed twice" in capsys.readouterr().out


def test_a_missing_inventory_file_fails(gate, tmp_path, monkeypatch, capsys):
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    (tree / "quality" / "image-inventory.json").unlink()
    assert _run(gate, tree, monkeypatch) == 1
    assert "is missing" in capsys.readouterr().out


def test_a_workflow_with_no_jobs_block_declares_no_jobs(gate, tmp_path, monkeypatch, capsys):
    """The parser walks out of `jobs:` at the first unindented key. A file that
    never enters it must yield nothing rather than matching on indentation
    somewhere else in the document."""
    tree = _tree(tmp_path, [SHIPPED], ["Dockerfile"])
    (tree / ".github" / "workflows" / "security.yml").write_text(
        "name: demo\non: [push]\nenv:\n  containers: not-a-job\n", encoding="utf-8"
    )
    assert _run(gate, tree, monkeypatch) == 1
    assert "declares no job 'containers'" in capsys.readouterr().out
