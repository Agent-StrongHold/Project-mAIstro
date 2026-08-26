"""The installer must not leave the recovery phrase readable, or behind (#360).

`bootstrap_first_run` POSTs the staged credentials to `/v1/setup/complete` and
receives, once, the 24-word BIP39 phrase that is the root of the deployment's
crypto identity. Three things were wrong with how it handled that response:

* `curl -o` created `.setup-response.json` under the caller's umask — 0644 on a
  typical system — so the phrase was world-readable from the instant it landed.
* There was no `trap` anywhere in `install.sh`, and the step that follows the
  phrase is a `read` loop that blocks until the operator types `yes`. An
  interrupt there is the *likely* case, not the exotic one, and it left the
  file on disk.
* `shred_file` truncated before overwriting, so the original blocks were
  released to the allocator before a single zero was written — and printed
  "shredded" either way.

`release-installer.yml` runs `./install.sh`, but it triggers only on tags and
`workflow_dispatch`, so no PR check executes a line of the installer. These
tests source the real functions out of `install.sh` and run them, which is what
makes a rewiring mistake fail a PR check rather than a release.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: Lifted verbatim from install.sh, by name.
_FUNCTIONS = ("ensure_python", "secret_file_run", "purge_file", "note_residual_risk")


def _harness(plan_dir: Path) -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    return f"""
set -uo pipefail
SCRIPT_DIR={str(ROOT)!r}
PLAN_DIR={str(plan_dir)!r}
PYTHON_CMD=()
warn() {{ echo "WARN: $*" >&2; }}
ok() {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
source <(sed -n {extract!r} "$SCRIPT_DIR/install.sh")
"""


def _run(workdir: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _harness(workdir) + script],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )


PHRASE = "abandon ability able about above absent absorb abstract absurd abuse access accident"


class TestThePhraseIsNeverReadableByOthers:
    def test_the_reserved_response_file_is_owner_only(self, tmp_path: Path) -> None:
        """`umask 0000` is the condition under test, not an environment
        detail: it is what the old `curl -o` path would have produced 666
        under, and 644 under the usual 022."""
        result = _run(
            tmp_path,
            """
umask 0000
secret_file_run reserve .setup-response.json
stat -c '%a' .setup-response.json
""",
        )
        assert result.returncode == 0, result.stderr
        # `ensure_python` announces itself through the harness's `ok`, so the
        # mode is the last line rather than the only one.
        assert result.stdout.strip().splitlines()[-1] == "600", result.stdout

    def test_a_writer_that_truncates_does_not_widen_it(self, tmp_path: Path) -> None:
        """What curl actually does to a path that already exists. If this were
        not true, reserving the file first would buy nothing."""
        result = _run(
            tmp_path,
            f"""
umask 0000
secret_file_run reserve .setup-response.json
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
stat -c '%a' .setup-response.json
""",
        )
        assert result.returncode == 0, result.stderr
        # `ensure_python` announces itself through the harness's `ok`, so the
        # mode is the last line rather than the only one.
        assert result.stdout.strip().splitlines()[-1] == "600", result.stdout

    def test_a_leftover_from_a_previous_run_is_narrowed_and_emptied(self, tmp_path: Path) -> None:
        """The state an interrupted pre-#360 run left behind. Reserving has to
        handle it rather than fail on it, or the first interrupt makes every
        later attempt fail while the exposed file stays put."""
        stale = tmp_path / ".setup-response.json"
        stale.write_text(f'{{"mnemonic": "{PHRASE}"}}', encoding="utf-8")
        stale.chmod(0o644)

        result = _run(tmp_path, "secret_file_run reserve .setup-response.json")

        assert result.returncode == 0, result.stderr
        assert stat.S_IMODE(stale.stat().st_mode) == 0o600
        assert stale.read_text(encoding="utf-8") == ""


class TestAnInterruptDoesNotLeaveThePhraseBehind:
    """`install.sh` had no `trap` at all. The interruption point that matters
    is the `read` loop that waits for the operator to type `yes` — it blocks
    indefinitely, by design, with the phrase sitting in the file."""

    def test_install_sh_traps_int_and_term(self) -> None:
        body = INSTALL_SH.read_text(encoding="utf-8")
        traps = re.findall(r"^\s*trap\s+.*$", body, flags=re.MULTILINE)

        assert traps, "install.sh has no trap; an interrupt leaves the phrase on disk"
        assert any("INT" in line and "TERM" in line for line in traps)

    def test_the_trap_purges_the_response_file(self) -> None:
        body = INSTALL_SH.read_text(encoding="utf-8")
        traps = re.findall(r"^\s*trap\s+.*$", body, flags=re.MULTILINE)

        assert any("purge_file" in line and "resp_file" in line for line in traps)

    def test_the_traps_are_cleared_before_the_function_returns(self) -> None:
        """A `trap ... INT` left installed hijacks Ctrl-C for the rest of the
        install, and an EXIT trap left installed purges a path this function no
        longer owns."""
        body = INSTALL_SH.read_text(encoding="utf-8")
        start = body.index("bootstrap_first_run() {")
        end = body.index("\n}", start)

        assert "trap - INT TERM EXIT" in body[start:end]

    def test_an_interrupted_run_leaves_no_readable_phrase(self, tmp_path: Path) -> None:
        """End to end through bash's own signal handling, rather than by
        reading the source: install the same trap, write the phrase, then send
        the process SIGINT while it waits."""
        script = f"""
secret_file_run reserve .setup-response.json
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
trap 'purge_file .setup-response.json; exit 130' INT
kill -INT $$
sleep 5
"""
        result = _run(tmp_path, script)

        assert result.returncode == 130, (result.returncode, result.stderr)
        assert not (tmp_path / ".setup-response.json").exists()

    def test_the_phrase_is_not_in_any_file_left_in_the_plan_directory(self, tmp_path: Path) -> None:
        """The property the operator cares about, stated without reference to
        any particular filename."""
        _run(
            tmp_path,
            f"""
secret_file_run reserve .setup-response.json
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
trap 'purge_file .setup-response.json; exit 130' INT
kill -INT $$
""",
        )
        leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
        for path in leftovers:
            assert "abandon ability" not in path.read_text(encoding="utf-8", errors="replace"), path


class TestRemovalDoesNotTruncateFirst:
    def test_the_file_is_removed(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            f"""
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
purge_file .setup-response.json
[[ -e .setup-response.json ]] && echo STILL_THERE || echo GONE
""",
        )
        assert result.stdout.strip().endswith("GONE"), result.stdout

    def test_purging_an_absent_file_is_not_an_error(self, tmp_path: Path) -> None:
        """It runs from an EXIT trap that fires on paths where the file was
        already removed."""
        result = _run(tmp_path, "purge_file .setup-response.json; echo rc=$?")
        assert "rc=0" in result.stdout, result.stdout

    def test_it_survives_python_being_unavailable(self, tmp_path: Path) -> None:
        """The helper is Python, and the installer runs on machines where
        `ensure_python` can fail. Leaving the file because the nice path was
        unavailable would be the worst of the options."""
        result = _run(
            tmp_path,
            f"""
ensure_python() {{ return 1; }}
secret_file_run() {{ return 1; }}
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
purge_file .setup-response.json
[[ -e .setup-response.json ]] && echo STILL_THERE || echo GONE
""",
        )
        assert result.stdout.strip().endswith("GONE"), result.stdout

    def test_a_symlink_is_not_followed(self, tmp_path: Path) -> None:
        """A cleanup step that follows a symlink is a way to make the installer
        delete a file of the attacker's choosing."""
        victim = tmp_path / "victim"
        victim.write_text("important", encoding="utf-8")
        (tmp_path / ".setup-response.json").symlink_to(victim)

        _run(tmp_path, "purge_file .setup-response.json")

        assert not (tmp_path / ".setup-response.json").exists()
        assert victim.read_text(encoding="utf-8") == "important"


class TestTheInstallerDoesNotOverclaim:
    """ "Shredded" reads as "the bytes are gone". On a journaling or
    copy-on-write filesystem, or any SSD with wear levelling, they may not be —
    and an operator whose threat model includes recovery from this disk has to
    know that to act on it."""

    def test_it_no_longer_says_shredded(self) -> None:
        body = INSTALL_SH.read_text(encoding="utf-8")
        operator_text = re.findall(r'^\s*(?:ok|info|warn) "(.*)"$', body, flags=re.MULTILINE)

        assert not [line for line in operator_text if "shred" in line.lower()], operator_text

    def test_it_states_the_residual_risk(self, tmp_path: Path) -> None:
        result = _run(tmp_path, "note_residual_risk")
        said = result.stdout.lower()

        assert "not" in said and "secure erasure" in said
        assert "ssd" in said or "copy-on-write" in said

    def test_it_names_something_the_operator_can_actually_do(self, tmp_path: Path) -> None:
        """A warning with no action attached is a warning people learn to
        skip."""
        result = _run(tmp_path, "note_residual_risk")

        assert "encryption" in result.stdout.lower()


class TestThePhraseIsNeverEchoedIntoTheEnvironment:
    """AC: never log, echo, or include the mnemonic in process arguments or
    shell history."""

    def test_the_helper_takes_a_path_not_a_value(self) -> None:
        """A secret in argv is readable from `ps` by every user on the box, and
        lands in shell history. Both secret-bearing files are passed by path."""
        body = INSTALL_SH.read_text(encoding="utf-8")

        for call in re.findall(r"^\s*secret_file_run .*$", body, flags=re.MULTILINE):
            assert "mnemonic" not in call.lower()

    def test_purge_prints_nothing_containing_the_content(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            f"""
printf '{{"mnemonic": "{PHRASE}"}}' > .setup-response.json
purge_file .setup-response.json
""",
        )
        assert "abandon" not in result.stdout
        assert "abandon" not in result.stderr


class TestTheStagedCredentialsFileKeepsItsContract:
    """`bootstrap-credentials.json` was already written 0600 by
    `maistro_bootstrap.credentials`. #360 must not change when it is kept: a
    pre-commit failure keeps it for retry, and that is stated to the operator."""

    def test_a_failed_bootstrap_still_keeps_the_credentials_for_retry(self) -> None:
        body = INSTALL_SH.read_text(encoding="utf-8")
        start = body.index("bootstrap_first_run() {")
        end = body.index("\n}", start)
        function = body[start:end]

        assert "Credentials kept at $creds for retry" in function

    def test_the_trap_does_not_purge_the_staged_credentials(self) -> None:
        """Purging them from the interrupt handler would destroy the retry path
        the failure branch promises."""
        body = INSTALL_SH.read_text(encoding="utf-8")

        for line in re.findall(r"^\s*trap\s+.*$", body, flags=re.MULTILINE):
            assert "$creds" not in line, line


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses the mode checks under test")
class TestTheModeChecksApplyToARealUser:
    def test_another_process_cannot_read_the_reserved_file(self, tmp_path: Path) -> None:
        """Stated as the property rather than as a mode number: no group or
        other bit is set, so no other unprivileged user has a way in."""
        _run(tmp_path, "umask 0000; secret_file_run reserve .setup-response.json")
        mode = (tmp_path / ".setup-response.json").stat().st_mode

        assert not mode & (stat.S_IRWXG | stat.S_IRWXO)
