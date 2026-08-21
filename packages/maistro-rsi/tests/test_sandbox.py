"""Tests tied to SPEC.md §1 (MicroVM sandbox) acceptance criteria sandbox-1..7."""

from __future__ import annotations

import sys

import pytest

from maistro_rsi.protocols import MicroVmSandbox
from maistro_rsi.sandbox.microvm import DockerMicroVmSandbox

# LocalSandbox.exec() is POSIX-only by construction: it shells out to `bash` and
# kills the process group via os.killpg/signal.SIGKILL — neither attribute even
# exists on Windows, and `bash` there resolves to a WSL shim, not a real shell.
# LocalSandbox is the passthrough for when RSI ALREADY runs inside an sbx Linux
# microVM (see its module docstring), so Windows is out of scope rather than
# broken. Only exec() is guarded; the protocol, file-I/O and path-escape tests
# below are platform-independent and still run everywhere.
posix_exec_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="LocalSandbox.exec is POSIX-only (bash + os.killpg/SIGKILL); it runs inside an sbx Linux microVM",
)


class FakeContainer:
    def __init__(self) -> None:
        self.destroy_calls = 0
        self.files: dict[str, str] = {}

    async def exec(self, command, timeout=60):
        return 0, f"ran: {command}"

    async def read_file(self, path):
        return self.files[path]

    async def write_file(self, path, content):
        self.files[path] = content

    async def destroy(self):
        self.destroy_calls += 1


class TestDockerMicroVmSandbox:
    def test_satisfies_microvm_protocol(self):
        """sandbox-1: DockerMicroVmSandbox structurally satisfies MicroVmSandbox."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        assert isinstance(sandbox, MicroVmSandbox)

    @pytest.mark.asyncio
    async def test_exec_delegates_to_container_and_returns_exit_code_and_output(self):
        """sandbox-2: exec runs the command and returns (exit_code, output)."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        code, output = await sandbox.exec("echo hi")
        assert code == 0
        assert "echo hi" in output

    @pytest.mark.asyncio
    async def test_write_then_read_round_trips_through_workspace(self):
        """sandbox-3: write_file followed by read_file round-trips content."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        await sandbox.write_file("notes.txt", "hello")
        assert await sandbox.read_file("notes.txt") == "hello"

    @pytest.mark.asyncio
    async def test_snapshot_ids_are_unique_even_for_the_same_label(self):
        """sandbox-4: snapshot returns a unique id per call, no collisions."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        snap_a = await sandbox.snapshot("checkpoint")
        snap_b = await sandbox.snapshot("checkpoint")
        assert snap_a != snap_b

    @pytest.mark.asyncio
    async def test_restore_of_captured_snapshot_raises_not_implemented(self):
        """sandbox-5: restoring a real snapshot id raises NotImplementedError, not a silent no-op."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        snapshot_id = await sandbox.snapshot("checkpoint")
        with pytest.raises(NotImplementedError):
            await sandbox.restore(snapshot_id)

    @pytest.mark.asyncio
    async def test_restore_of_unknown_snapshot_raises_key_error(self):
        """sandbox-5: restoring an id that was never captured raises KeyError."""
        sandbox = DockerMicroVmSandbox(FakeContainer())
        with pytest.raises(KeyError):
            await sandbox.restore("never-captured")

    @pytest.mark.asyncio
    async def test_destroy_tears_down_the_underlying_container_exactly_once(self):
        """sandbox-6: destroy() tears down the container exactly once."""
        container = FakeContainer()
        sandbox = DockerMicroVmSandbox(container)
        await sandbox.destroy()
        assert container.destroy_calls == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_destroys_on_normal_exit(self):
        """sandbox-7: async-with destroys the sandbox on normal exit."""
        container = FakeContainer()
        async with DockerMicroVmSandbox(container):
            assert container.destroy_calls == 0
        assert container.destroy_calls == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_destroys_on_exception(self):
        """sandbox-7: async-with destroys the sandbox even when the body raises — no leaked containers."""
        container = FakeContainer()
        with pytest.raises(RuntimeError):
            async with DockerMicroVmSandbox(container):
                raise RuntimeError("boom")
        assert container.destroy_calls == 1


class TestLocalSandbox:
    """Tests tied to SPEC.md §1 acceptance criteria sandbox-8..12."""

    def test_satisfies_microvm_protocol(self, tmp_path):
        """sandbox-8: LocalSandbox structurally satisfies MicroVmSandbox."""
        from maistro_rsi.sandbox.local import LocalSandbox

        assert isinstance(LocalSandbox(str(tmp_path)), MicroVmSandbox)

    @posix_exec_only
    @pytest.mark.asyncio
    async def test_exec_returns_exit_code_and_output(self, tmp_path):
        """sandbox-9: exec runs against the workspace and returns (exit_code, output)."""
        from maistro_rsi.sandbox.local import LocalSandbox

        sandbox = LocalSandbox(str(tmp_path))
        code, output = await sandbox.exec("echo hello")
        assert code == 0 and "hello" in output

    @posix_exec_only
    @pytest.mark.asyncio
    async def test_exec_reports_nonzero_exit_verbatim(self, tmp_path):
        """sandbox-9: a non-zero exit is reported, not swallowed."""
        from maistro_rsi.sandbox.local import LocalSandbox

        code, _ = await LocalSandbox(str(tmp_path)).exec("exit 3")
        assert code == 3

    @posix_exec_only
    @pytest.mark.asyncio
    async def test_exec_times_out_and_reports_124(self, tmp_path):
        """sandbox-9: a command exceeding the timeout is killed and reported as exit 124."""
        from maistro_rsi.sandbox.local import LocalSandbox

        code, output = await LocalSandbox(str(tmp_path)).exec("sleep 30", timeout=1)
        assert code == 124 and "timeout" in output

    @pytest.mark.asyncio
    async def test_write_read_round_trip_relative_path_stays_in_workspace(self, tmp_path):
        """sandbox-10: write/read round-trip; relative paths resolve under the workspace."""
        from maistro_rsi.sandbox.local import LocalSandbox

        sandbox = LocalSandbox(str(tmp_path))
        await sandbox.write_file("sub/notes.txt", "hi")
        assert await sandbox.read_file("sub/notes.txt") == "hi"
        assert (tmp_path / "sub" / "notes.txt").read_text() == "hi"

    @pytest.mark.asyncio
    async def test_snapshot_unique_and_restore_posture(self, tmp_path):
        """sandbox-11: unique snapshot ids; restore raises KeyError / NotImplementedError."""
        from maistro_rsi.sandbox.local import LocalSandbox

        sandbox = LocalSandbox(str(tmp_path))
        a = await sandbox.snapshot("cp")
        b = await sandbox.snapshot("cp")
        assert a != b
        with pytest.raises(KeyError):
            await sandbox.restore("never")
        with pytest.raises(NotImplementedError):
            await sandbox.restore(a)

    @pytest.mark.asyncio
    async def test_destroy_is_noop_and_context_manager_exits_clean(self, tmp_path):
        """sandbox-12: destroy never raises; async-with exits cleanly."""
        from maistro_rsi.sandbox.local import LocalSandbox

        async with LocalSandbox(str(tmp_path)) as sandbox:
            await sandbox.write_file("f", "x")
        await sandbox.destroy()  # idempotent, no raise

    @pytest.mark.asyncio
    async def test_rejects_paths_escaping_the_workspace(self, tmp_path):
        """sandbox-14: `..` traversal and outside-absolute paths raise ValueError;
        absolute paths inside the workspace still resolve."""
        from maistro_rsi.sandbox.local import LocalSandbox

        workspace = tmp_path / "ws"
        sandbox = LocalSandbox(str(workspace))

        with pytest.raises(ValueError, match="escapes"):
            await sandbox.write_file("../evil.gitconfig", "x")
        with pytest.raises(ValueError, match="escapes"):
            await sandbox.read_file("sub/../../evil")
        with pytest.raises(ValueError, match="escapes"):
            await sandbox.write_file(str(tmp_path / "outside.txt"), "x")

        inside = workspace / "ok.txt"
        await sandbox.write_file(str(inside), "fine")  # absolute but inside
        assert await sandbox.read_file("ok.txt") == "fine"

    @posix_exec_only
    @pytest.mark.asyncio
    async def test_bash_shell_semantics(self, tmp_path):
        """sandbox-15: commands run under bash, matching the Docker backend's
        shell contract ([[ ]] is a bashism that plain sh rejects)."""
        from maistro_rsi.sandbox.local import LocalSandbox

        code, output = await LocalSandbox(str(tmp_path)).exec('[[ -n "x" ]] && echo bash-ok')
        assert code == 0 and "bash-ok" in output

    @posix_exec_only
    @pytest.mark.asyncio
    async def test_timeout_kills_the_whole_process_group(self, tmp_path):
        """sandbox-15: a timed-out command's children die with it — a spawned
        `sleep` must not outlive exec()."""
        import os

        from maistro_rsi.sandbox.local import LocalSandbox

        sandbox = LocalSandbox(str(tmp_path))
        code, _ = await sandbox.exec("sleep 30 & echo $! > child.pid; wait", timeout=1)
        assert code == 124

        child_pid = int((tmp_path / "child.pid").read_text().strip())
        # SIGKILL was sent to the process group; give the kernel a beat to reap.
        import asyncio as _asyncio

        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            await _asyncio.sleep(0.1)
        else:
            pytest.fail(f"child {child_pid} survived the group kill")


@pytest.fixture
def isolated_env(monkeypatch):
    """Make the isolation check deterministic and host-independent.

    Backend *selection* is a separate concern from isolation *verification*, and
    the two must not be tangled in one assertion: the CI host may or may not
    expose `/.dockerenv`, a populated `/proc/1/cgroup` or readable DMI, so a
    selection test that relies on the real host passes or fails by accident.
    Tests that care about the verification behaviour drive it explicitly below.
    """
    import maistro_rsi.sandbox.microvm as microvm_mod

    monkeypatch.setattr(microvm_mod, "isolation_evidence", lambda: ["test:stubbed"])


class TestCreateRsiSandbox:
    """Tests tied to SPEC.md §1 acceptance criterion sandbox-13."""

    @pytest.mark.asyncio
    async def test_local_backend_selected_by_arg(self, tmp_path, isolated_env):
        """sandbox-13: backend='local' returns a LocalSandbox."""
        from maistro_rsi.sandbox.local import LocalSandbox
        from maistro_rsi.sandbox.microvm import create_rsi_sandbox

        sandbox = await create_rsi_sandbox(str(tmp_path), backend="local")
        assert isinstance(sandbox, LocalSandbox)

    @pytest.mark.asyncio
    async def test_local_backend_selected_by_env(self, tmp_path, monkeypatch, isolated_env):
        """sandbox-13: $MAISTRO_RSI_SANDBOX=local returns a LocalSandbox."""
        from maistro_rsi.sandbox.local import LocalSandbox
        from maistro_rsi.sandbox.microvm import SANDBOX_BACKEND_ENV, create_rsi_sandbox

        monkeypatch.setenv(SANDBOX_BACKEND_ENV, "local")
        assert isinstance(await create_rsi_sandbox(str(tmp_path)), LocalSandbox)

    @pytest.mark.asyncio
    async def test_arg_overrides_env_and_default_is_docker(
        self, tmp_path, monkeypatch, isolated_env
    ):
        """sandbox-13: explicit backend arg overrides env; default routes to the Docker backend."""
        import maistro_rsi.sandbox.microvm as microvm_mod
        from maistro_rsi.sandbox.local import LocalSandbox

        # env says docker, arg says local → arg wins
        monkeypatch.setenv(microvm_mod.SANDBOX_BACKEND_ENV, "docker")
        assert isinstance(
            await microvm_mod.create_rsi_sandbox(str(tmp_path), backend="local"), LocalSandbox
        )

        # default (no arg, no env) routes to create_microvm_sandbox — stub it so
        # the test needs no real Docker daemon.
        monkeypatch.delenv(microvm_mod.SANDBOX_BACKEND_ENV, raising=False)
        sentinel = object()

        async def fake_create(workspace, settings=None, env=None):
            return sentinel

        monkeypatch.setattr(microvm_mod, "create_microvm_sandbox", fake_create)
        assert await microvm_mod.create_rsi_sandbox(str(tmp_path)) is sentinel


class TestLocalBackendRequiresVerifiedIsolation:
    """`local` must prove containment, not merely be asked for.

    LocalSandbox executes the coding agent directly against the mounted
    filesystem — `sbx/maistro-rsi/spec.yaml` pairs it with `--auto`, so the
    agent's tool use is auto-approved and the microVM *is* the containment.
    Selecting it therefore asserts something about the environment, and that
    assertion used to be one environment variable any parent process could set.

    The motivating input is a developer or a stray export setting
    MAISTRO_RSI_SANDBOX=local on a real workstation: previously an
    auto-approved agent loop on the real filesystem, now a refusal.
    """

    @pytest.mark.asyncio
    async def test_refuses_local_without_isolation_evidence(self, tmp_path, monkeypatch):
        import maistro_rsi.sandbox.microvm as microvm_mod

        monkeypatch.setattr(microvm_mod, "isolation_evidence", lambda: [])
        monkeypatch.delenv(microvm_mod.SANDBOX_ATTEST_ENV, raising=False)

        with pytest.raises(RuntimeError) as exc:
            await microvm_mod.create_rsi_sandbox(str(tmp_path), backend="local")

        message = str(exc.value)
        # The refusal has to be actionable, or an operator will reach for the
        # nearest workaround instead of the intended one.
        assert microvm_mod.SANDBOX_ATTEST_ENV in message
        assert "/.dockerenv" in message

    @pytest.mark.asyncio
    async def test_allows_local_when_evidence_is_present(self, tmp_path, monkeypatch):
        import maistro_rsi.sandbox.microvm as microvm_mod
        from maistro_rsi.sandbox.local import LocalSandbox

        monkeypatch.setattr(microvm_mod, "isolation_evidence", lambda: ["/.dockerenv"])
        monkeypatch.delenv(microvm_mod.SANDBOX_ATTEST_ENV, raising=False)

        sandbox = await microvm_mod.create_rsi_sandbox(str(tmp_path), backend="local")
        assert isinstance(sandbox, LocalSandbox)

    @pytest.mark.asyncio
    async def test_attestation_permits_local_on_unrecognised_substrate(self, tmp_path, monkeypatch):
        """The sbx kit's path: isolation real, markers absent.

        Verified against a live example — the container this suite was developed
        in is genuinely isolated and exposes no `/.dockerenv`, no runtime token
        in `/proc/1/cgroup`, and unreadable DMI. Detection alone would refuse it.
        """
        import maistro_rsi.sandbox.microvm as microvm_mod
        from maistro_rsi.sandbox.local import LocalSandbox

        monkeypatch.setattr(microvm_mod, "isolation_evidence", lambda: [])
        monkeypatch.setenv(microvm_mod.SANDBOX_ATTEST_ENV, "i-am-inside-a-disposable-vm")

        sandbox = await microvm_mod.create_rsi_sandbox(str(tmp_path), backend="local")
        assert isinstance(sandbox, LocalSandbox)

    @pytest.mark.asyncio
    async def test_wrong_attestation_value_is_not_accepted(self, tmp_path, monkeypatch):
        """A truthy-looking value must not pass; the token is exact."""
        import maistro_rsi.sandbox.microvm as microvm_mod

        monkeypatch.setattr(microvm_mod, "isolation_evidence", lambda: [])
        monkeypatch.setenv(microvm_mod.SANDBOX_ATTEST_ENV, "1")

        with pytest.raises(RuntimeError):
            await microvm_mod.create_rsi_sandbox(str(tmp_path), backend="local")

    def test_sbx_kit_attests_the_isolation_it_creates(self):
        """The kit that sets MAISTRO_RSI_SANDBOX=local must also attest.

        Without this the shipped kit would hit the refusal above on any host
        whose isolation markers are not detectable — the gate would fire on the
        one environment it is meant to permit.
        """
        from pathlib import Path

        import yaml

        spec_path = Path(__file__).resolve().parents[3] / "sbx" / "maistro-rsi" / "spec.yaml"
        spec = yaml.safe_load(spec_path.read_text())
        variables = spec["environment"]["variables"]

        assert variables["MAISTRO_RSI_SANDBOX"] == "local"
        assert variables["MAISTRO_RSI_SANDBOX_ATTEST_ISOLATED"] == "i-am-inside-a-disposable-vm"


class TestIsolationEvidenceSemantics:
    """Only container evidence counts — generic VM-ness must not.

    Codex P1 on #263: a persistent KVM/VirtualBox development VM reports a
    virtual platform in DMI, so DMI-based evidence let MAISTRO_RSI_SANDBOX=
    local hand an auto-approved agent a real, non-disposable filesystem —
    recreating the exact workstation case this gate exists to refuse.
    """

    def _blind(self, monkeypatch, tmp_path):
        """Point every probe at empty fixtures so the host can't interfere."""
        import maistro_rsi.sandbox.microvm as microvm_mod

        monkeypatch.setattr(microvm_mod, "_CONTAINER_MARKER_FILES", ())
        monkeypatch.setattr(microvm_mod, "_CGROUP_PATH", str(tmp_path / "no-cgroup"))
        return microvm_mod

    def test_no_markers_means_no_evidence(self, monkeypatch, tmp_path):
        mod = self._blind(monkeypatch, tmp_path)
        assert mod.isolation_evidence() == []

    def test_container_marker_file_is_evidence(self, monkeypatch, tmp_path):
        mod = self._blind(monkeypatch, tmp_path)
        marker = tmp_path / ".dockerenv"
        marker.write_text("")
        monkeypatch.setattr(mod, "_CONTAINER_MARKER_FILES", (str(marker),))
        assert mod.isolation_evidence() == [str(marker)]

    def test_cgroup_runtime_token_is_evidence(self, monkeypatch, tmp_path):
        mod = self._blind(monkeypatch, tmp_path)
        cgroup = tmp_path / "cgroup"
        cgroup.write_text("0::/system.slice/docker-abc123.scope\n")
        monkeypatch.setattr(mod, "_CGROUP_PATH", str(cgroup))
        evidence = mod.isolation_evidence()
        assert evidence and "docker" in evidence[0]

    def test_dmi_is_never_consulted(self):
        """The source must not read DMI: VM-ness ≠ disposability. Pinned at
        the source level because no fixture can prove a negative about a
        removed probe."""
        import inspect

        import maistro_rsi.sandbox.microvm as microvm_mod

        source = inspect.getsource(microvm_mod.isolation_evidence)
        assert "/sys/class/dmi" not in source
