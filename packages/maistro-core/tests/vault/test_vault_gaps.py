"""Gap-filling coverage for vault.py not exercised by test_vault.py:
_extract_public_key's missing-key branch, _parse_secrets' comment/blank-skip
and both '=' split branches, _ensure_loaded's FileNotFoundError/
CalledProcessError decrypt-failure branches, and _write's
CalledProcessError re-encrypt-failure branch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from maistro.vault import (
    Vault,
    VaultUnavailableError,
    _extract_public_key,
    _parse_secrets,
)


@pytest.fixture()
def tmp_vault_dir(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "conductor"
    vault_dir.mkdir()
    return vault_dir


def _has_age() -> bool:
    try:
        subprocess.run(["age", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


age_required = pytest.mark.skipif(not _has_age(), reason="age not installed")


class TestExtractPublicKey:
    def test_missing_public_key_line_raises(self, tmp_vault_dir: Path) -> None:
        identity = tmp_vault_dir / "no_pubkey.key"
        identity.write_text("AGE-SECRET-KEY-NOTAREALKEY\n")
        with pytest.raises(VaultUnavailableError, match="no public key found"):
            _extract_public_key(identity)


class TestParseSecrets:
    def test_blank_and_comment_lines_are_skipped(self) -> None:
        result = _parse_secrets("\n# a comment\nfoo = bar\n")
        assert result == {"foo": "bar"}

    def test_equals_with_spaces_splits_on_space_equals_space(self) -> None:
        assert _parse_secrets("foo = bar") == {"foo": "bar"}

    def test_equals_without_spaces_splits_on_bare_equals(self) -> None:
        assert _parse_secrets("foo=bar") == {"foo": "bar"}

    def test_bare_value_is_indexed_to_itself(self) -> None:
        assert _parse_secrets("standalone-secret") == {"standalone-secret": "standalone-secret"}


class TestEnsureLoadedFailures:
    def test_age_binary_not_found_raises_vault_unavailable(
        self, tmp_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault_path = tmp_vault_dir / "vault.age"
        vault_path.write_bytes(b"ciphertext")
        identity_path = tmp_vault_dir / "admin.key"
        identity_path.write_text("# public key: age1xxx\nAGE-SECRET-KEY-X\n")

        def fake_run(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("age not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        vault = Vault(vault_path=vault_path, identity_path=identity_path)
        with pytest.raises(VaultUnavailableError, match="age command not found"):
            vault.use("foo", lambda v: v)

    def test_decryption_failure_raises_vault_unavailable(
        self, tmp_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault_path = tmp_vault_dir / "vault.age"
        vault_path.write_bytes(b"ciphertext")
        identity_path = tmp_vault_dir / "admin.key"
        identity_path.write_text("# public key: age1xxx\nAGE-SECRET-KEY-X\n")

        def fake_run(*args: object, **kwargs: object) -> None:
            raise subprocess.CalledProcessError(1, ["age"], stderr=b"bad ciphertext")

        monkeypatch.setattr(subprocess, "run", fake_run)

        vault = Vault(vault_path=vault_path, identity_path=identity_path)
        with pytest.raises(VaultUnavailableError, match="decryption failed"):
            vault.use("foo", lambda v: v)


@age_required
class TestWriteFailure:
    def test_reencrypt_failure_raises_runtime_error(
        self, tmp_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
        secret_key = result.stdout.strip()
        public_key = secret_key.split("# public key: ")[1].split("\n")[0]

        identity_path = tmp_vault_dir / "admin.key"
        identity_path.write_text(secret_key)

        vault_path = tmp_vault_dir / "vault.age"
        encrypted = subprocess.run(
            ["age", "-r", public_key, "-o", str(vault_path)],
            input=b"foo = bar\n",
            capture_output=True,
            check=True,
        )
        assert encrypted.returncode == 0

        vault = Vault(vault_path=vault_path, identity_path=identity_path)
        vault.use("foo", lambda v: v)  # forces _ensure_loaded so _secrets is populated

        real_run = subprocess.run

        def flaky_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            if args[0] == "age" and "-r" in args:
                raise subprocess.CalledProcessError(1, args, stderr=b"encrypt boom")
            return real_run(args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(subprocess, "run", flaky_run)

        with pytest.raises(RuntimeError, match="Failed to re-encrypt vault"):
            vault.add("baz", "qux")


class TestInitVault:
    """First-run provisioning (SPEC-072726-3439 Phase 3): init_vault creates
    the identity key + empty encrypted vault, idempotently."""

    def test_creates_key_and_vault_then_round_trips(self, tmp_path: Path) -> None:
        if shutil.which("age") is None or shutil.which("age-keygen") is None:
            pytest.skip("age not installed")
        from maistro.vault import Vault, init_vault

        vault_path = tmp_path / "data" / "secrets.age"
        identity_path = tmp_path / "data" / "admin.key"
        assert init_vault(vault_path, identity_path) is True
        assert vault_path.exists() and identity_path.exists()

        # Second call is a no-op.
        assert init_vault(vault_path, identity_path) is False

        # The fresh vault is empty but usable: add + use round-trips.
        v = Vault(vault_path=vault_path, identity_path=identity_path)
        v.add("FIRST_SECRET", "hunter2")
        assert (
            Vault(vault_path=vault_path, identity_path=identity_path).use(
                "FIRST_SECRET", lambda s: s
            )
            == "hunter2"
        )

    def test_missing_age_toolchain_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from maistro import vault as vault_mod

        monkeypatch.setattr("shutil.which", lambda _cmd: None)
        with pytest.raises(vault_mod.VaultUnavailableError, match="age"):
            vault_mod.init_vault(tmp_path / "s.age", tmp_path / "a.key")
