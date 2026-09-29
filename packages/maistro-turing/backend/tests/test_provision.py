"""The opt-in dev bootstrap generates unique keys, never a shared value (#858)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..provision import KEY_ENV_NAME, generate_service_key, main, store_key_env_line


def test_generated_keys_are_unique_and_prefixed() -> None:
    keys = {generate_service_key() for _ in range(64)}
    assert len(keys) == 64
    assert all(k.startswith("sk-svc-turing-") for k in keys)


def test_generated_key_is_never_a_known_shared_value() -> None:
    key = generate_service_key()
    assert key != "sk-svc-turing-dev-" + "internal"
    assert generate_service_key() != key


def test_env_file_storage_is_opt_in_and_0600(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env.turing"
    assert main(["--env-file", str(env_file)]) == 0
    assert env_file.stat().st_mode & 0o777 == 0o600
    content = env_file.read_text(encoding="utf-8")
    assert content.startswith(f"{KEY_ENV_NAME}=sk-svc-turing-")
    # The same key printed on stdout is the one stored — no silent divergence.
    stored = content.strip().split("=", 1)[1]
    assert capsys.readouterr().out.strip() == stored


def test_existing_entry_requires_explicit_force(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.turing"
    env_file.write_text(f"{KEY_ENV_NAME}=old-key\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--env-file", str(env_file)])
    assert "old-key" in env_file.read_text(encoding="utf-8")
    assert main(["--env-file", str(env_file), "--force"]) == 0
    content = env_file.read_text(encoding="utf-8")
    assert "old-key" not in content
    assert content.startswith(f"{KEY_ENV_NAME}=sk-svc-turing-")
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_store_preserves_unrelated_env_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.turing"
    env_file.write_text("TURING_SELF_ID=astro\nOTHER=keep\n", encoding="utf-8")
    store_key_env_line(env_file, "sk-svc-turing-new", force=False)
    content = env_file.read_text(encoding="utf-8")
    assert "TURING_SELF_ID=astro" in content
    assert "OTHER=keep" in content
    assert f"{KEY_ENV_NAME}=sk-svc-turing-new" in content
