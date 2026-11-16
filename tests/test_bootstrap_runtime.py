"""The user-owned Python/uv bootstrap contract (#1821).

``install.sh`` used to satisfy a missing uv with
``python -m pip install --user uv``, and ``get.sh`` invoked a bare
``python3`` for legacy ``.env`` migration before install.sh could resolve
anything. That stopped on machines without Python, without pip, or with a
PEP 668 externally managed interpreter, and left PATH recovery to the user.

The contract now lives in one place, ``scripts/bootstrap-runtime.sh``, sourced
by both entrypoints: uv first (official standalone installer — no Python, no
pip, no elevation, user-owned destination, immediately on this process's
PATH), then a helper interpreter against a 3.11 floor, with the wizard
package's separate 3.12+ ``requires-python`` validated by
``ensure_package_python`` so a helper interpreter can never be reported as
satisfying package execution.

These tests drive the real library with controlled prerequisite fixtures: stub
``python3``/``uv``/``curl`` executables whose behavior each test pins. The one
thing they cannot exercise offline is the real astral.sh installer, so the
fixture installer models — and asserts — the properties the official one
documents (user-owned destination, marked idempotent rc block,
INSTALLER_NO_MODIFY_PATH passthrough). The clean-machine end-to-end path is
proved through the stub chain: no Python, no uv, download, provision, use.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "bootstrap-runtime.sh"
GET_SH = ROOT / "get.sh"
INSTALL_SH = ROOT / "install.sh"

#: Core executables the library (and its fixture installer) may use. PATH is
#: restricted to a directory holding exactly these plus a test's stubs, so
#: "no Python" and "no uv" states are real rather than assumed. bash itself
#: is included because a harness may spawn a child whose PATH is the shim
#: alone (subprocess resolves the interpreter through the child's env).
CORE_TOOLS = (
    "bash",
    "mktemp",
    "rm",
    "rmdir",
    "sh",
    "chmod",
    "grep",
    "mkdir",
    "cp",
    "head",
    "sed",
    "sleep",
)

RC_MARKER = "maistro-test-uv-path-block"


def _symlink_core(shim: Path) -> None:
    for name in CORE_TOOLS:
        resolved = shutil.which(name)
        assert resolved, f"{name} must exist to build the fixture PATH"
        (shim / name).symlink_to(resolved)


def _write_stub_python(path: Path, *, version: str, pip_log: Path | None = None) -> None:
    """A `python3` stand-in baked with one version.

    Handles exactly the invocation shapes the library uses: the stdin floor
    probe (`<stub> - <floor>`), the version print (`-c ...`), and `-m pip` —
    which never happens under the contract, so a call fails loudly (and the
    static no-pip test pins that the contract never even tries). When
    ``pip_log`` is given, every pip attempt is recorded there so a test can
    assert the contract never reached for pip at all.
    """
    major, minor = [*version.split("."), "0", "0"][:2]
    pip_line = f'printf "%s\\n" "pip $*" >> "{pip_log}"\n' if pip_log else ""
    path.write_text(
        "#!/bin/bash\n"
        f'stub_version="{version}"\n'
        f'stub_major="{major}"\n'
        f'stub_minor="{minor}"\n'
        'if [[ "${1:-}" == "-m" ]]; then\n'
        f"    {pip_line}"
        '    echo "pip $*" >&2\n'
        "    exit 1\n"
        "fi\n"
        'if [[ "${1:-}" == "-" ]]; then\n'
        '    floor="${2:?}"\n'
        '    fmaj="${floor%%.*}"; fmin="${floor#*.}"; fmin="${fmin%%.*}"\n'
        "    if (( stub_major > fmaj )) || (( stub_major == fmaj && stub_minor >= fmin )); then\n"
        "        exit 0\n"
        "    fi\n"
        "    exit 1\n"
        "fi\n"
        'if [[ "${1:-}" == "-c" ]]; then\n'
        '    printf "%s\\n" "$stub_version"\n'
        "    exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_stub_uv(
    path: Path,
    *,
    version: str = "9.9.9",
    state_dir: Path | None = None,
    install_version: str | None = None,
    install_path: str | None = None,
    install_rc: int | None = None,
    log: Path | None = None,
) -> None:
    """A `uv` stand-in.

    - ``--version`` prints the baked version.
    - ``python find REQ`` consults ``<state_dir>/installed``
      (VERSION<space>PATH) and answers only when the recorded version
      satisfies REQ (">=X.Y" or exact "X.Y").
    - ``python install REQ`` records the baked install version/path unless a
      state file already exists (installs do not clobber), or exits the baked
      rc when one is set — modelling a failed download.

    The stub never satisfies a floor by trusting REQ: `find` compares the
    recorded version, and the library separately executes whatever path find
    returned — which is how the belt-and-braces test below catches a
    resolution that lies about its version.
    """
    assert state_dir is not None and log is not None
    if install_rc is not None:
        install_line = f'exit "{install_rc}"\n'
    else:
        install_version = install_version or "3.12.0"
        install_path = install_path or "/nonexistent"
        install_line = (
            'if [[ ! -e "$state" ]]; then\n'
            f'    mkdir -p "{state_dir}"\n'
            f'    printf "%s %s\\n" "{install_version}" "{install_path}" > "$state"\n'
            "fi\n"
            'printf "Installed Python %s\\n" "$req"\n'
            "exit 0\n"
        )
    path.write_text(
        "#!/bin/bash\n"
        f'stub_version="{version}"\n'
        f'state_dir="{state_dir}"\n'
        f'uv_log="{log}"\n'
        'if [[ "${1:-}" == "--version" ]]; then\n'
        '    printf "uv %s\\n" "$stub_version"\n'
        "    exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "python" ]]; then\n'
        '    req="${3:?}"\n'
        '    state="$state_dir/installed"\n'
        '    if [[ "$2" == "install" ]]; then\n'
        '        echo "python install $req" >> "$uv_log"\n'
        f"        {install_line}"
        "    fi\n"
        '    [[ "$2" == "find" ]] || exit 1\n'
        '    echo "python find $req" >> "$uv_log"\n'
        '    [[ -e "$state" ]] || exit 1\n'
        '    read -r rec_version rec_path < "$state"\n'
        '    mode="exact"; req2="$req"\n'
        '    if [[ "$req" == ">="* ]]; then mode="gte"; req2="${req#>=}"; fi\n'
        '    rmaj="${req2%%.*}"; rmin="${req2#*.}"; rmin="${rmin%%.*}"\n'
        '    vmaj="${rec_version%%.*}"; vmin="${rec_version#*.}"; vmin="${vmin%%.*}"\n'
        '    if [[ "$mode" == "gte" ]]; then\n'
        "        (( vmaj > rmaj || (vmaj == rmaj && vmin >= rmin) )) || exit 1\n"
        "    else\n"
        '        [[ "$rec_version" == "$req2".* || "$rec_version" == "$req2" ]] || exit 1\n'
        "    fi\n"
        '    printf "%s\\n" "$rec_path"\n'
        "    exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_stub_curl(path: Path, *, payload: Path, fail_rc: int | None, log: Path) -> None:
    """A `curl` stand-in: fails with the baked rc when set, otherwise copies
    the fixture installer payload to the ``-o`` target. Every invocation is
    logged so a test can pin which URL the contract chose to download."""
    fail_line = f'exit "{fail_rc}"\n' if fail_rc is not None else ""
    path.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f"fail_line() {{ {fail_line} :; }}\n"
        'target=""\n'
        "while [[ $# -gt 0 ]]; do\n"
        '    if [[ "${1:-}" == "-o" ]]; then target="${2:?}"; shift 2; else shift; fi\n'
        "done\n"
        '[[ -n "$target" ]] || exit 1\n'
        "fail_line\n"
        f'cp "{payload}" "$target"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_installer_payload(path: Path, *, pre_delay: int = 0) -> None:
    """Models the documented contract of the official uv standalone installer:
    the binary lands in $UV_INSTALL_DIR (default ~/.local/bin, user-owned) and,
    unless INSTALLER_NO_MODIFY_PATH=1, an idempotent clearly-marked PATH block
    is appended to shell start-up files. POSIX sh; never elevates.

    ``pre_delay`` keeps the installer running (sleep) before it lays anything
    down, so a test can deliver a signal mid-run — the interrupted run must
    never adopt the success the installer would eventually have reported. The
    sleep detaches its own stdout/stderr: when the interrupted run's trap kills
    the installer wrapper, the still-running sleep is orphaned, and an orphan
    holding this process's pipes would keep ``communicate()`` waiting for EOF
    until the sleep ended — a harness artifact that measures the sleep, not the
    contract, and the reason this suite once ate the whole 30s pytest-timeout
    budget in CI while the bootstrap itself had exited within ~2s."""
    path.write_text(
        "#!/bin/sh\n"
        # >/dev/null 2>&1: see the docstring — an orphaned sleep must not hold
        # the harness's pipe write-ends open.
        + (f"sleep {pre_delay} >/dev/null 2>&1\n" if pre_delay > 0 else "")
        + 'install_dir="${UV_INSTALL_DIR:-$HOME/.local/bin}"\n'
        'mkdir -p "$install_dir" || exit 1\n'
        'cp "${STUB_UV_BIN:?}" "$install_dir/uv" || exit 1\n'
        'chmod +x "$install_dir/uv" || exit 1\n'
        'if [ "${INSTALLER_NO_MODIFY_PATH:-0}" != "1" ]; then\n'
        '    rc_file="$HOME/.bashrc"\n'
        f'    if ! grep -q "{RC_MARKER}" "$rc_file" 2>/dev/null; then\n'
        "        {\n"
        '            echo ""\n'
        f'            echo "# >>> {RC_MARKER} >>>"\n'
        '            echo "export PATH=\\"$install_dir:$PATH\\""\n'
        f'            echo "# <<< {RC_MARKER} <<<"\n'
        '        } >> "$rc_file"\n'
        "    fi\n"
        "fi\n"
        'echo "installed uv to $install_dir"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


class Harness:
    """One bash process with a fully controlled PATH, HOME and TMPDIR.

    Stubs are baked (version, state, rc) at creation time, so a test's
    fixtures cannot leak into each other through the environment.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir(parents=True)
        self.shim = tmp_path / "shim"
        self.shim.mkdir(parents=True)
        self.scratch = tmp_path / "scratch"
        self.scratch.mkdir(parents=True)
        self.state_dir = tmp_path / "uv-state"
        self.uv_log = tmp_path / "uv-calls.log"
        self.curl_log = tmp_path / "curl-calls.log"
        _symlink_core(self.shim)

    def stub_uv_on_path(self, **kwargs: object) -> Path:
        kwargs.setdefault("state_dir", self.state_dir)
        kwargs.setdefault("log", self.uv_log)
        stub = self.shim / "uv"
        _write_stub_uv(stub, **kwargs)  # type: ignore[arg-type]
        return stub

    def stub_curl(self, payload: Path, fail_rc: int | None = None) -> Path:
        stub = self.shim / "curl"
        _write_stub_curl(stub, payload=payload, fail_rc=fail_rc, log=self.curl_log)
        return stub

    def uv_asset(self, **kwargs: object) -> Path:
        """The 'downloaded' uv binary the fixture installer lays down."""
        asset = self.tmp_path / "uv-asset"
        kwargs.setdefault("state_dir", self.state_dir)
        kwargs.setdefault("log", self.uv_log)
        _write_stub_uv(asset, **kwargs)  # type: ignore[arg-type]
        return asset

    def asset_env(self, asset: Path) -> str:
        """Prelude pointing the fixture installer at the 'downloaded' binary."""
        return f"export STUB_UV_BIN={shlex.quote(str(asset))}\n"

    def script(self, body: str) -> str:
        return f"""
set -uo pipefail
export HOME={shlex.quote(str(self.home))}
export TMPDIR={shlex.quote(str(self.scratch))}
export PATH={shlex.quote(str(self.shim))}
ok() {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
PYTHON_CMD=()
UV_CMD=()
UV_PACKAGE_PYTHON=""
source {shlex.quote(str(LIB))}
{body}"""

    def run(self, body: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", self.script(body)],
            cwd=self.tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


@pytest.fixture
def installer_payload(tmp_path: Path) -> Path:
    payload = tmp_path / "uv-installer.sh"
    _write_installer_payload(payload)
    return payload


#: The 'provisioned' interpreter the stub uv records: the real interpreter on
#: this machine, so the python_meets_floor probe and (in the migration tests)
#: the real scripts/secret_env.py both genuinely run.
@pytest.fixture
def real_python() -> str:
    resolved = shutil.which("python3")
    assert resolved, "python3 must exist on the test machine"
    return resolved


class TestEnsureUv:
    def test_uv_already_on_path_is_reused_without_downloading(self, harness: Harness) -> None:
        harness.stub_uv_on_path(version="0.9.12")
        result = harness.run(
            'ensure_uv || exit 1\nprintf "resolved:%s\\n" "${UV_CMD[*]}"\n"${UV_CMD[@]}" --version\n'
        )
        assert result.returncode == 0, result.stderr
        assert "OK: uv found: uv 0.9.12" in result.stdout
        assert "resolved:uv" in result.stdout
        # No download machinery ran: curl is not even on the fixture PATH.
        assert "curl is required" not in result.stderr

    def test_uv_outside_path_is_adopted_not_duplicated(self, harness: Harness) -> None:
        bin_dir = harness.home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        _write_stub_uv(
            bin_dir / "uv", version="0.9.12", state_dir=harness.state_dir, log=harness.uv_log
        )
        result = harness.run('ensure_uv || exit 1\nprintf "at:%s\\n" "$(command -v uv)"\n')
        assert result.returncode == 0, result.stderr
        assert f"OK: uv found at {bin_dir}/uv" in result.stdout
        assert f"at:{bin_dir}/uv" in result.stdout

    def test_missing_uv_installs_standalone_and_is_usable_immediately(
        self, harness: Harness, installer_payload: Path, real_python: str
    ) -> None:
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(installer_payload)
        asset_env = harness.asset_env(harness.tmp_path / "uv-asset")
        result = harness.run(
            asset_env
            + 'ensure_uv || exit 1\n"${UV_CMD[@]}" --version || exit 1\nprintf "bin:%s\\n" "$(command -v uv)"\n'
        )
        assert result.returncode == 0, result.stderr
        assert "OK: uv installed: uv 9.9.9" in result.stdout
        assert f"bin:{harness.home / '.local' / 'bin' / 'uv'}" in result.stdout
        # The downloaded installer and its scratch state are cleaned up.
        assert not list(harness.scratch.glob("maistro-uv.*")), list(harness.scratch.iterdir())
        # The initiating account owns what landed.
        assert (harness.home / ".local" / "bin" / "uv").stat().st_uid == os.getuid()

    def test_download_failure_is_actionable_and_leaves_nothing(
        self, harness: Harness, installer_payload: Path, real_python: str
    ) -> None:
        harness.uv_asset(install_version="3.12.7", install_path="/x")
        harness.stub_curl(installer_payload, fail_rc=7)
        result = harness.run("ensure_uv\n")
        assert result.returncode == 1
        assert "https://astral.sh/uv/install.sh" in result.stderr
        assert "nothing was installed or modified" in result.stderr
        assert not list(harness.scratch.glob("maistro-uv.*"))
        assert not (harness.home / ".local" / "bin" / "uv").exists()
        # A retry against a recovered network succeeds and the resolved uv is
        # the freshly installed one — a failed attempt poisons nothing.
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(installer_payload)
        retry = harness.run(
            harness.asset_env(harness.tmp_path / "uv-asset")
            + 'ensure_uv || exit 1\n"${UV_CMD[@]}" --version\n'
        )
        assert retry.returncode == 0, retry.stderr
        assert "OK: uv installed: uv 9.9.9" in retry.stdout

    def test_unwritable_destination_fails_actionably(
        self, harness: Harness, installer_payload: Path
    ) -> None:
        harness.uv_asset(install_version="3.12.7", install_path="/x")
        harness.stub_curl(installer_payload)
        harness.home.chmod(0o555)
        try:
            result = harness.run("ensure_uv\n")
        finally:
            harness.home.chmod(0o755)
        assert result.returncode == 1
        assert "The uv installer failed" in result.stderr
        assert "Nothing else was modified" in result.stderr
        assert not (harness.home / ".local").exists()

    def test_installer_rc_block_is_default_idempotent_and_skippable(
        self, harness: Harness, installer_payload: Path, tmp_path: Path, real_python: str
    ) -> None:
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(installer_payload)
        asset_env = harness.asset_env(harness.tmp_path / "uv-asset")
        first = harness.run(asset_env + "ensure_uv || exit 1")
        second = harness.run(asset_env + "ensure_uv || exit 1")
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        bashrc = (harness.home / ".bashrc").read_text(encoding="utf-8")
        assert bashrc.count(f"# >>> {RC_MARKER} >>>") == 1, bashrc
        # A NEW shell after successful bootstrap finds uv through the marked
        # block alone — the documented new-shell recovery path.
        new_shell = subprocess.run(
            [
                "bash",
                "-c",
                'source "$HOME/.bashrc" && command -v uv && "$(command -v uv)" --version',
            ],
            env={"HOME": str(harness.home), "PATH": str(harness.shim)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert new_shell.returncode == 0, new_shell.stderr
        assert f"{harness.home / '.local' / 'bin' / 'uv'}" in new_shell.stdout
        assert "uv 9.9.9" in new_shell.stdout

        fresh = Harness(tmp_path / "no-rc")
        fresh.uv_asset(install_version="3.12.7", install_path=real_python)
        fresh.stub_curl(installer_payload)
        result = fresh.run(
            fresh.asset_env(fresh.tmp_path / "uv-asset")
            + "MAISTRO_UV_NO_MODIFY_PATH=1 ensure_uv || exit 1"
        )
        assert result.returncode == 0, result.stderr
        assert not (fresh.home / ".bashrc").exists()
        assert "no shell start-up file was touched" in result.stderr

    def test_interrupted_installer_stops_the_run_and_never_reports_ready(
        self, harness: Harness, tmp_path: Path, real_python: str
    ) -> None:
        """A TERM while the child installer runs must stop the bootstrap with a
        non-zero status and an actionable error — never adopt the installer's
        eventual success. Bash defers a trap until a FOREGROUND child exits,
        so an installer run in the foreground would swallow the signal and
        print `OK: uv installed` + `READY` (exit 0) after the very
        interruption acceptance criterion 6 forbids reporting as ready."""
        delayed = tmp_path / "uv-installer-delayed.sh"
        _write_installer_payload(delayed, pre_delay=30)
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(delayed)
        asset_env = harness.asset_env(harness.tmp_path / "uv-asset")
        started = time.monotonic()
        proc = subprocess.Popen(
            ["bash", "-c", harness.script(asset_env + "ensure_uv || exit 1\necho READY\n")],
            cwd=harness.tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(2.0)  # the installer is in its sleep; the run is mid-flight
        proc.send_signal(signal.SIGTERM)
        # The installer's sleep detached its fds (see _write_installer_payload),
        # so EOF here means the bootstrap exited — a deferred trap would surface
        # as TimeoutExpired, and a trap that fired only after the installer's own
        # 30s delay would breach the promptness bound below. Either way the test
        # fails; passing requires the immediate stop the contract promises.
        stdout, stderr = proc.communicate(timeout=30)
        elapsed = time.monotonic() - started
        # The signal is not swallowed: conventional non-zero exit, no success
        # announcement of any kind.
        assert proc.returncode != 0, (proc.returncode, stdout, stderr)
        assert "OK: uv installed" not in stdout
        assert "READY" not in stdout
        assert "Interrupted while the uv installer was running" in stderr
        # Prompt, not eventual: the run stopped while the installer was still
        # mid-flight, not once the installer would have finished anyway. The
        # root suite runs this file under pytest-timeout's 30s per-test cap;
        # ~2s is the mechanism, 15s the structural bound.
        assert elapsed < 15, (elapsed, proc.returncode, stdout, stderr)
        # The installer was killed mid-flight: it laid nothing down, and the
        # scratch it ran from is gone — no half-state left behind.
        assert not (harness.home / ".local" / "bin" / "uv").exists()
        assert not list(harness.scratch.glob("maistro-uv.*")), list(harness.scratch.iterdir())

    def test_version_pin_and_explicit_url_choose_the_installer(
        self, harness: Harness, installer_payload: Path, tmp_path: Path, real_python: str
    ) -> None:
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(installer_payload)
        asset_env = harness.asset_env(harness.tmp_path / "uv-asset")
        pinned = harness.run(asset_env + "MAISTRO_UV_VERSION=0.9.5 ensure_uv || exit 1")
        assert pinned.returncode == 0, pinned.stderr
        assert "https://astral.sh/uv/0.9.5/install.sh" in harness.curl_log.read_text(
            encoding="utf-8"
        )

        mirror = tmp_path / "mirror.sh"
        shutil.copyfile(installer_payload, mirror)
        home2 = Harness(tmp_path / "mirror-home")
        home2.uv_asset(install_version="3.12.7", install_path=real_python)
        home2.stub_curl(installer_payload)
        result = home2.run(
            home2.asset_env(home2.tmp_path / "uv-asset")
            + f"MAISTRO_UV_VERSION=0.9.5 MAISTRO_UV_INSTALLER_URL='file://{mirror}' ensure_uv || exit 1"
        )
        assert result.returncode == 0, result.stderr
        last_call = home2.curl_log.read_text(encoding="utf-8").splitlines()[-1]
        assert f"file://{mirror}" in last_call


class TestEnsurePython:
    def test_helper_floor_3_11_is_accepted_without_uv(self, harness: Harness) -> None:
        _write_stub_python(harness.shim / "python3", version="3.11.8")
        result = harness.run('ensure_python || exit 1\nprintf "helper:%s\\n" "${PYTHON_CMD[*]}"\n')
        assert result.returncode == 0, result.stderr
        assert "OK: Python found: 3.11.8" in result.stdout
        assert "helper:python3" in result.stdout
        # The stub uv is not on the fixture PATH: consulting it would fail.
        assert "uv" not in result.stdout

    def test_too_old_python_is_rejected_and_uv_provisions_the_package_floor(
        self, harness: Harness, real_python: str
    ) -> None:
        _write_stub_python(harness.shim / "python3", version="3.10.4")
        harness.stub_uv_on_path(install_version="3.12.7", install_path=real_python)
        result = harness.run('ensure_python || exit 1\nprintf "helper:%s\\n" "$PYTHON_CMD"\n')
        assert result.returncode == 0, result.stderr
        assert "OK: uv found: uv 9.9.9" in result.stdout
        assert "OK: Package interpreter (Python >= 3.12, resolved by uv):" in result.stdout
        assert "OK: Helper interpreter:" in result.stdout
        assert f"helper:{real_python}" in result.stdout
        assert "python install >=3.12" in harness.uv_log.read_text(encoding="utf-8")

    def test_clean_host_without_python_or_uv_reaches_a_working_runtime(
        self, harness: Harness, installer_payload: Path, real_python: str
    ) -> None:
        """The #1821 headline path: no Python, no pip, no uv — one contract
        later, uv AND a package-grade interpreter are resolved and immediately
        usable in the same process."""
        harness.uv_asset(install_version="3.12.7", install_path=real_python)
        harness.stub_curl(installer_payload)
        asset_env = harness.asset_env(harness.tmp_path / "uv-asset")
        result = harness.run(
            asset_env
            + 'ensure_python || exit 1\n"${UV_CMD[@]}" --version || exit 1\n'
            + '"${PYTHON_CMD[@]}" -c "import sys; assert sys.version_info >= (3, 12); print(\'helper-grade\')" || exit 1\n'
        )
        assert result.returncode == 0, result.stderr
        assert "OK: uv installed:" in result.stdout
        assert "OK: Package interpreter (Python >= 3.12, resolved by uv):" in result.stdout
        assert "OK: Helper interpreter:" in result.stdout

    def test_uv_provision_failure_is_actionable(self, harness: Harness) -> None:
        harness.stub_uv_on_path(install_rc=1)
        result = harness.run("ensure_python\n")
        assert result.returncode == 1
        assert "uv could not provision Python >= 3.12" in result.stderr
        assert "Install Python 3.12+ yourself" in result.stderr
        assert "nothing was modified" in result.stderr

    def test_externally_managed_python_without_pip_is_used_and_never_asked_to_pip(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        """A supported interpreter on a PEP 668 host (no usable pip) is a fine
        helper: the contract never invokes pip, so EXTERNALLY-MANAGED cannot
        block or break anything. The stub records every pip attempt so the
        'never even tried' claim is observed, not assumed."""
        pip_log = tmp_path / "pip-attempts.log"
        _write_stub_python(harness.shim / "python3", version="3.12.1", pip_log=pip_log)
        # The PEP 668 marker itself, for scenario fidelity — only pip reads it.
        (tmp_path / "EXTERNALLY-MANAGED").write_text(
            "[externally-managed]\nError=\n", encoding="utf-8"
        )
        result = harness.run('ensure_python || exit 1\nprintf "helper:%s\\n" "${PYTHON_CMD[*]}"\n')
        assert result.returncode == 0, result.stderr
        assert "helper:python3" in result.stdout
        assert "OK: Python found: 3.12.1" in result.stdout
        assert not pip_log.exists(), "the contract invoked pip on a PEP 668 host"
        assert "pip" not in result.stderr

    def test_a_floor_violating_resolution_is_never_announced_as_satisfying(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        harness.stub_uv_on_path()
        lying = tmp_path / "lying-python"
        _write_stub_python(lying, version="3.11.0")
        harness.state_dir.mkdir(parents=True, exist_ok=True)
        # find's recorded version says 3.12.0; the binary it points to reports
        # 3.11.0 when probed. The library must execute and verify the resolved
        # interpreter instead of trusting the resolution.
        (harness.state_dir / "installed").write_text(f"3.12.0 {lying}\n", encoding="utf-8")
        result = harness.run("ensure_package_python\n")
        assert result.returncode == 1
        assert "does not satisfy the package's Python >= 3.12 requirement" in result.stderr
        assert "OK: Package interpreter" not in result.stdout


class TestHelperVersusPackageFloors:
    def test_package_interpreter_is_validated_separately_from_the_helper(
        self, harness: Harness, tmp_path: Path
    ) -> None:
        _write_stub_python(harness.shim / "python3", version="3.11.8")
        harness.stub_uv_on_path()
        pkg_python = tmp_path / "pkg-python"
        _write_stub_python(pkg_python, version="3.12.4")
        harness.state_dir.mkdir(parents=True)
        (harness.state_dir / "installed").write_text(f"3.12.4 {pkg_python}\n", encoding="utf-8")
        result = harness.run(
            "ensure_python || exit 1\nensure_package_python || exit 1\n"
            'printf "helper=%s pkg=%s\\n" "${PYTHON_CMD[*]}" "$UV_PACKAGE_PYTHON"\n'
        )
        assert result.returncode == 0, result.stderr
        assert "OK: Python found: 3.11.8" in result.stdout
        assert "OK: Package interpreter (Python >= 3.12, resolved by uv):" in result.stdout
        assert "helper=python3" in result.stdout
        assert f"pkg={pkg_python}" in result.stdout

    def test_recorded_floors_match_the_bootstrap_package(self) -> None:
        """The separate floors are the contract; the package floor must be the
        wizard package's own requires-python, not a copy that can drift."""
        pyproject = (ROOT / "packages" / "maistro-bootstrap" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        requires = next(
            line.split("=", 1)[1].strip().strip('"')
            for line in pyproject.splitlines()
            if line.startswith("requires-python")
        )
        assert requires == ">=3.12"
        lib = LIB.read_text(encoding="utf-8")
        assert 'MAISTRO_HELPER_PYTHON_FLOOR="3.11"' in lib
        assert 'MAISTRO_PACKAGE_PYTHON_FLOOR="3.12"' in lib


class TestNoPipAnywhere:
    def test_entrypoints_and_library_never_reach_for_pip_or_elevation(self) -> None:
        bodies = {
            name: path.read_text(encoding="utf-8")
            for name, path in (
                ("install.sh", INSTALL_SH),
                ("get.sh", GET_SH),
                ("bootstrap-runtime.sh", LIB),
            )
        }
        for name, body in bodies.items():
            assert "pip install" not in body, name
            assert "--break-system-packages" not in body, name
            assert "sudo pip" not in body, name
            assert " -m uv" not in body, f"{name}: uv runs as a standalone binary, not a module"

    def test_the_only_pre_init_python_invocation_is_the_contract(self) -> None:
        """get.sh's legacy migration is the one Python consumer that runs
        before install.sh initialization; it must go through the contract."""
        get_body = GET_SH.read_text(encoding="utf-8")
        assert '"${PYTHON_CMD[@]}" "$INSTALL_DIR/scripts/secret_env.py"' in get_body
        bare = [
            line
            for line in get_body.splitlines()
            if line.strip().startswith("python3 ") or line.strip().startswith("python ")
        ]
        assert bare == [], bare


class TestLegacyEnvMigration:
    @pytest.fixture
    def migration_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        install_dir = tmp_path / "install"
        (install_dir / "scripts").mkdir(parents=True)
        shutil.copyfile(
            ROOT / "scripts" / "secret_env.py", install_dir / "scripts" / "secret_env.py"
        )
        shutil.copyfile(LIB, install_dir / "scripts" / "bootstrap-runtime.sh")
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        return install_dir, legacy

    def _run_migration(
        self, harness: Harness, install_dir: Path, legacy: Path
    ) -> subprocess.CompletedProcess[str]:
        extract = "/^migrate_legacy_install()/,/^}/p"
        body = f"""
ok() {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
PYTHON_CMD=()
UV_CMD=()
UV_PACKAGE_PYTHON=""
source {shlex.quote(str(LIB))}
INSTALL_DIR={shlex.quote(str(install_dir))}
DEFAULT_INSTALL_DIR={shlex.quote(str(install_dir))}
LEGACY_DIR={shlex.quote(str(legacy))}
source <(sed -n {extract!r} {shlex.quote(str(GET_SH))})
migrate_legacy_install
printf "rc=%s\\n" "$?"
"""
        env = dict(os.environ)
        env["HOME"] = str(harness.home)
        env["TMPDIR"] = str(harness.scratch)
        env["PATH"] = str(harness.shim)
        return subprocess.run(
            ["bash", "-c", body],
            cwd=harness.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_migration_without_system_python_goes_through_uv(
        self, harness: Harness, migration_dirs: tuple[Path, Path], real_python: str
    ) -> None:
        install_dir, legacy = migration_dirs
        legacy_env = legacy / ".env"
        legacy_env.write_text(
            'MAISTRO_ACCESS_TOKEN=legacytok\nAPI_KEYS=["conductor:legacytok"]\n', encoding="utf-8"
        )
        legacy_env.chmod(0o600)
        harness.stub_uv_on_path(install_version="3.12.7", install_path=real_python)
        result = self._run_migration(harness, install_dir, legacy)
        assert result.returncode == 0, result.stderr
        assert "rc=0" in result.stdout
        migrated = install_dir / ".env"
        assert migrated.exists()
        assert migrated.stat().st_mode & 0o777 == 0o600
        assert "MAISTRO_ACCESS_TOKEN=legacytok" in migrated.read_text(encoding="utf-8")
        # The interpreter came through the contract's uv path, not a bare python3.
        assert "OK: uv found: uv 9.9.9" in result.stdout
        assert "OK: Helper interpreter:" in result.stdout

    def test_migration_failure_before_any_mutation_leaves_both_files_untouched(
        self, harness: Harness, migration_dirs: tuple[Path, Path], installer_payload: Path
    ) -> None:
        install_dir, legacy = migration_dirs
        legacy_env = legacy / ".env"
        legacy_env.write_text("MAISTRO_ACCESS_TOKEN=legacytok\n", encoding="utf-8")
        before = legacy_env.read_bytes()
        # No python, no uv, and the download fails: the resolver must give up
        # before the migration touches a single byte.
        harness.stub_curl(installer_payload, fail_rc=7)
        result = self._run_migration(harness, install_dir, legacy)
        assert result.returncode == 1
        assert "nothing was installed or modified" in result.stderr
        assert legacy_env.read_bytes() == before
        assert not (install_dir / ".env").exists()
        # The only entry under the install dir is the fixture's own scripts/
        # copy; the migration itself created nothing.
        assert sorted(p.name for p in install_dir.iterdir()) == ["scripts"]

    def test_migration_with_a_compatible_helper_python_never_touches_uv(
        self, harness: Harness, migration_dirs: tuple[Path, Path], real_python: str
    ) -> None:
        install_dir, legacy = migration_dirs
        (legacy / ".env").write_text('API_KEYS=["ops:legacytok"]\n', encoding="utf-8")
        (harness.shim / "python3").symlink_to(real_python)
        result = self._run_migration(harness, install_dir, legacy)
        assert result.returncode == 0, result.stderr
        assert "rc=0" in result.stdout
        assert "OK: Python found:" in result.stdout
        assert "uv" not in result.stdout
