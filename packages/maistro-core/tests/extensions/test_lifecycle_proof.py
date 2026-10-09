"""The M9-J3 end-to-end extension lifecycle proof (issue #981).

These tests pin ``scripts/extension_lifecycle_proof.py`` — the reproducible
harness that drives discover → inspect → authorize → install → invoke →
observe → update → reauthorization-fence → restart durability against the
production seams. The load-bearing properties:

* the proof actually proves (every stage's checks pass, and the harness
  reports failure rather than quietly passing one on);
* the proof is deterministic (identical cores across runs — the lifecycle
  evidence is a function of the artifacts, not of the wall clock);
* no source-tree or editable-install bypass exists (loaded code originates
  under the scratch install root, never under ``packages/`` or
  ``extensions/``);
* the harness's own guards are real (artifact path escapes are refused; a
  plugin lying about its identity is recorded FAILED with nothing active);
* the lineage stays honest about what this base cannot prove yet (the #954
  post-install restart-durability boundary note is present, not hidden);
* the #954 post-install lifecycle — disable, pin, rollback, remove — is
  proven as explicit, audited decisions on the governed records.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from maistro.extensions import ExtensionLifecycleError
from maistro.extensions.types import ExtensionState

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "extension_lifecycle_proof.py"

EXPECTED_STAGES = (
    "build-catalog",
    "discover",
    "inspect",
    "authorize-install",
    "invoke-observe",
    "denials",
    "update-fence",
    "post-install-lifecycle",
    "catalog-integrity",
    "durable-restart",
    "canonical-truth-boundary",
)


def _load_proof_module():
    spec = importlib.util.spec_from_file_location("extension_lifecycle_proof", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extension_lifecycle_proof"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def proof_module():
    return _load_proof_module()


async def _run_proof(proof_module, scratch: Path) -> dict:
    proof = proof_module.LifecycleProof(scratch)
    return await proof.run()


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
class TestFullLifecycleProof:
    async def test_every_stage_proves(self, proof_module, tmp_path: Path) -> None:
        report = await _run_proof(proof_module, tmp_path / "scratch")
        assert report["summary"]["checks_failed"] == 0
        assert report["summary"]["stages_ok"] == report["summary"]["stages"]
        assert tuple(stage["name"] for stage in report["stages"]) == EXPECTED_STAGES

    async def test_lineage_is_honest_about_post_install_boundaries(
        self, proof_module, tmp_path: Path
    ) -> None:
        """The lineage must say what this base cannot prove, not hide it."""
        report = await _run_proof(proof_module, tmp_path / "scratch")
        restart_stage = next(s for s in report["stages"] if s["name"] == "durable-restart")
        assert restart_stage["note"] is not None
        assert "#954" in restart_stage["note"]
        assert "rollback" in restart_stage["note"]

    async def test_every_invocation_record_carries_canonical_provenance(
        self, proof_module, tmp_path: Path
    ) -> None:
        report = await _run_proof(proof_module, tmp_path / "scratch")
        assert len(report["invocations"]) >= 4
        for observation in report["invocations"]:
            assert observation["caller"]
            assert observation["scope"]["org_id"] == "org-acme"
            assert observation["scope"]["workspace_id"] == "ws-7"
            assert observation["install_id"]
            assert len(observation["extension"]["artifact_sha256"]) == 64
            assert observation["outcome"] in {
                "ok",
                "denied:undeclared-capability",
            }
        denied = [
            o for o in report["invocations"] if o["outcome"] == "denied:undeclared-capability"
        ]
        assert denied, "the undeclared-access denial must be an observed invocation"
        assert denied[0]["capability_requests"][-1]["outcome"] == "denied"


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
class TestProofDeterminism:
    async def test_core_digest_is_identical_across_runs(
        self, proof_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = await _run_proof(proof_module, tmp_path / "run1")
        # Force the second build into a different ZIP timestamp bucket.
        # ``ZipFile.writestr`` dates a str arcname from ``time.localtime()``
        # and DOS time has 2-second granularity, so a builder that inherits
        # the wall clock hashes identical sources differently depending on
        # when the run started — this monkeypatch is what makes the
        # assertions below a regression test rather than a timing
        # coincidence that only holds while two runs share one bucket.
        monkeypatch.setattr(
            time,
            "localtime",
            lambda *args: time.struct_time((2000, 1, 1, 12, 0, 4, 5, 1, 0)),
        )
        second = await _run_proof(proof_module, tmp_path / "run2")
        assert first["deterministic_core_sha256"] == second["deterministic_core_sha256"]
        first_lock = next(s for s in first["stages"] if s["name"] == "discover")
        second_lock = next(s for s in second["stages"] if s["name"] == "discover")
        assert first_lock["evidence"]["lock"] == second_lock["evidence"]["lock"]

    async def test_reported_base_commit_is_a_commit(self, proof_module, tmp_path: Path) -> None:
        report = await _run_proof(proof_module, tmp_path / "scratch")
        assert len(report["base_commit"]) == 40


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
class TestNoSourceTreeBypass:
    async def test_loaded_code_originates_only_from_the_install_root(
        self, proof_module, tmp_path: Path
    ) -> None:
        scratch = tmp_path / "scratch"
        proof = proof_module.LifecycleProof(scratch)
        await proof.run()
        assert proof.loaded
        for key, loaded in proof.loaded.items():
            assert loaded.install_dir.is_relative_to(proof.install_root), key
            module_origin = getattr(loaded.module, "__spec__", None)
            assert module_origin is not None
            assert module_origin.origin is not None
            origin = Path(module_origin.origin).resolve()
            assert origin.is_relative_to(proof.install_root), key
            assert not origin.is_relative_to(REPO / "packages")
            assert not origin.is_relative_to(REPO / "extensions")

    async def test_loader_refuses_artifact_path_escapes(self, proof_module, tmp_path) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../evil.py", "PLUGIN = {}")
        record = SimpleNamespace(
            extension_id="acme.evil", version="1.0.0", artifact_sha256="a" * 64
        )
        with pytest.raises(ValueError, match="unsafe artifact entry"):
            proof_module._extract_artifact(tmp_path, record, buffer.getvalue())
        assert not (tmp_path / "evil.py").exists()
        assert not (tmp_path.parent / "evil.py").exists()

    async def test_plugin_lying_about_identity_is_recorded_failed(
        self, proof_module, tmp_path: Path
    ) -> None:
        """A payload whose plugin self-declares a different version must fail
        activation truthfully: FAILED with nothing active."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from maistro.extensions import (
            ExtensionInstallService,
            ExtensionPackage,
            ExtensionScope,
            TrustPolicy,
        )
        from maistro.extensions.store import InMemoryExtensionStore
        from maistro.extensions.types import TrustClaim

        lying_source = (
            'PLUGIN = {"kind": "tool", "name": "acme.liar", "version": "9.9.9", '
            '"capabilities": [], "handler": "hi"}\n'
            "def hi(context):\n    return 'hi'\n"
            "HANDLERS = {'hi': hi}\n"
        )
        spec = proof_module.PackageSpec(
            extension_id="acme.liar",
            version="1.0.0",
            module_name="acme_liar.plugin",
            plugin_source=lying_source,
            permissions=(),
        )
        artifacts, manifests = proof_module.build_packages([spec])
        key = Ed25519PrivateKey.from_private_bytes(proof_module.PUBLISHER_KEY_SEED)
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=proof_module.ArtifactZipLoader(tmp_path / "root"),
            trust_policy=TrustPolicy(trusted_publishers=frozenset({"acme-labs"})),
            install_id_factory=lambda: "install-liar-1",
        )
        scope = ExtensionScope(org_id="org-acme", workspace_id="ws-7")
        record = await service.inspect(
            actor="operator:alice",
            scope=scope,
            package=ExtensionPackage(
                manifest_bytes=manifests[spec.key], payload=artifacts[spec.key]
            ),
            trust_evidence=TrustClaim(
                publisher_id="acme-labs",
                signature_present=True,
                signer_key_id=proof_module.key_fingerprint(key),
                package_sha256=proof_module.sha256_hex(artifacts[spec.key]),
            ),
        )
        await service.authorize(
            record.install_id, actor="operator:alice", scope=scope, approve=True, reason="test"
        )
        with pytest.raises(ExtensionLifecycleError):
            await service.install(
                record.install_id, actor="operator:alice", scope=scope, payload=artifacts[spec.key]
            )
        failed = await service.get(record.install_id, scope=scope)
        assert failed.state is ExtensionState.FAILED
        assert failed.failure_reason is not None
        assert "9.9.9" in failed.failure_reason or "identity" in failed.failure_reason
        assert await service.active(scope, "acme.liar") is None


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
class TestPostInstallHistoryTruth:
    async def test_denied_and_superseded_records_stay_queryable(
        self, proof_module, tmp_path: Path
    ) -> None:
        proof = proof_module.LifecycleProof(tmp_path / "scratch")
        await proof.run()
        denied = await proof.store.records_in_state(ExtensionState.DENIED)
        assert denied, "the denied broader upgrade must be in history"
        active = await proof.store.records_in_state(ExtensionState.ACTIVE)
        assert active, "the authorized versions stay active and queryable"
        for record in (*denied, *active):
            trail = await proof.store.transitions_for(record.install_id)
            assert trail, f"every record keeps its audit trail ({record.install_id})"
            assert trail[-1].to_state is record.state


@pytest.mark.contract("boundary")
@pytest.mark.scope("integration")
class TestCommandLineContract:
    def test_cli_writes_lineage_and_exits_zero(self, tmp_path: Path) -> None:
        out = tmp_path / "lineage"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(out), "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((out / "lineage.json").read_text(encoding="utf-8"))
        assert report["schema"] == "maistro-extension-lifecycle-proof:v1"
        assert report["summary"]["checks_failed"] == 0
        markdown = (out / "lineage.md").read_text(encoding="utf-8")
        assert "# Extension lifecycle proof — lineage" in markdown
        for stage in EXPECTED_STAGES:
            assert stage in markdown
        assert "checks passed." in markdown

    def test_cli_exits_nonzero_when_a_check_fails(
        self, proof_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailingProof(proof_module.LifecycleProof):
            async def run(self) -> dict:
                report = await super().run()
                report["stages"][0]["checks"].append(
                    {"id": "injected", "ok": False, "detail": "injected failure"}
                )
                report["summary"]["checks_failed"] += 1
                return report

        monkeypatch.setattr(proof_module, "LifecycleProof", FailingProof)
        out = tmp_path / "lineage"
        assert proof_module.main(["--out", str(out), "--quiet"]) == 1
        report = json.loads((out / "lineage.json").read_text(encoding="utf-8"))
        assert report["summary"]["checks_failed"] == 1
        markdown = (out / "lineage.md").read_text(encoding="utf-8")
        assert "FAIL: `injected`" in markdown
