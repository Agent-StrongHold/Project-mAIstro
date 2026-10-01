"""Dispatch an HTTP-initiated RSI cleanup run into an ephemeral container (#509).

Why this exists
---------------
#305 made ``POST /v1/rsi/runs`` fail closed because the in-process loop runs
candidate-authored code as the Conductor process: ``python -m pytest`` over a
candidate-edited tree imports that tree's conftest, test modules and declared
plugins, so an argument vector is not an isolation boundary.

The fix is not a wider attestation of the same in-process loop — it is a
different execution model. ``tools/run_rsi_isolated.sh`` already runs the WHOLE
loop (agent, git, tests, coverage, fitness) inside an ephemeral container; this
module gives the Conductor a way to do the same over HTTP, so the RSI page's
Start button works again without the API becoming a host-execution primitive.

What the Conductor process does here
------------------------------------
It builds one ``docker run`` invocation as an argument vector — no shell on the
host, and (via ``--test-argv``) no shell inside the container either — and then
only observes: it polls the report directory the container writes, relays the
container's exit code, and stops the container on cancellation. Every byte of
candidate-authored code executes inside the container.

Trust decisions this module makes explicit
------------------------------------------
* **Where the container runs.** Here, on whatever Docker endpoint this process
  can reach. Reaching a Docker socket is root-equivalent on its host, so
  ``backend_available()`` is the deployment's trust decision made visible: with
  no Docker CLI, no reachable daemon, or no runner image, the backend does not
  attest and ``require_isolation()`` refuses the run. Nothing here widens what
  counts as attested — the probe answers exactly "can this process launch the
  contained loop", not "is docker installed somewhere".
* **How reports come back.** The wrapper mounts ``REPORT_DIR`` outside the
  edited workspace so the agent cannot see or touch it. Same shape here: the
  report directory lives on the host under the server's own working root,
  derived from the run id (never named by the caller — the route refuses
  caller-supplied output directories), and is mounted read-write at
  ``/run/reports`` while the repository is mounted READ-ONLY at ``/target``.
  The loop clones its target and never writes to it (``local_loop``:
  "Local clone — never touches the source repo's branches or working tree"),
  so the read-only mount costs nothing and closes the last host-write path.
  ``/workspace`` is deliberately left to the image: that is where the baked
  toolchain and virtualenv live, and mounting a foreign repo over it would
  hide both.
* **How a run is cancelled.** ``stop_container`` is a bounded ``docker stop`` —
  a different operation from cancelling an asyncio task, with a different
  failure mode (the stop can time out; the monitor thread then reaps the
  container's exit code when it finally exits).
* **Whether the run outlives the Conductor process.** It can, and this module
  does not pretend otherwise: the container is labeled with its run id, is
  bounded by its own cycle count, and removes itself (``--rm``) when it exits.
  Runs recorded in the Conductor's memory are still lost on restart, so a
  container from a previous process life is visible only to Docker
  (``docker ps --filter label=maistro.rsi.run-id``). That is a documented
  gap, not a silent one — surfacing it in ``list_runs`` needs durable run
  records, which is its own change.

Isolation posture (ADR-093 reconciliation)
------------------------------------------
ADR-093's aspiration for *unattended untrusted code* is a microVM (Tier 2+).
This backend is Tier 3 — a hardened container (``--cap-drop=ALL``,
``no-new-privileges``, memory/cpu/pids ceilings, read-only source mount) —
which ADR-093 itself calls "a guardrail against accidents and
prompt-injection mistakes". It is deployed anyway, deliberately, because the
RSI stack carries containment layers a bare exec sandbox does not: Warden
quarantine, the fitness scorecard, the protected-test-inventory gate, the
promotion review, and the harvest boundary all stand between a candidate and
anything leaving the loop — and the issue (#509, under epic #552) names this
wrapper model as the supported isolated path. The docker invocation is
confined to this module so a microVM backend (the ``sbx/`` kit, or a
SPEC-190 selector backend) can replace the runtime without touching the
policy, the routes, or the service.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Image that bakes the maistro toolchain (maistro_rsi and its workspace deps)
#: plus the fitness toolchain. Built from ``Dockerfile.rsi-runner``.
DEFAULT_RUNNER_IMAGE = "maistro-rsi-runner:latest"

#: The loop's gateway endpoint inside the compose network. The wrapper joins
#: the gateway's compose network and uses the container name for the same
#: reason: the published port is host-loopback only, and the builders agent
#: rewrites a bare ``litellm`` host to 127.0.0.1.
DEFAULT_GATEWAY_URL = "http://maistro-litellm:4000"

#: Resource + capability guardrails, mirroring ``tools/run_rsi_isolated.sh``:
#: caps stripped, no privilege escalation, fork storms bounded. Generous vs
#: the measured sequential peak — a runaway ceiling, not a squeeze.
DEFAULT_MEMORY = "6g"
DEFAULT_CPUS = "4"
DEFAULT_PIDS = "1024"

#: Seconds ``docker stop`` waits for the loop to exit before SIGKILL. The loop
#: checks between cycles, so a graceful stop usually lands quickly; the timeout
#: exists so a wedged container still dies.
STOP_TIMEOUT_S = 20

#: Where the container expects its inputs. Container-side paths, fixed: the
#: host paths that feed them are derived server-side.
REPO_MOUNT_TARGET = "/target"
REPORT_MOUNT_TARGET = "/run/reports"
WORK_ROOT_IN_CONTAINER = "/tmp/rsi-work"

#: Label put on every dispatched container, so an operator (or a future
#: durable run store) can find the containers this backend started.
RUN_ID_LABEL = "maistro.rsi.run-id"

#: Source paths that make the workspace packages importable inside the runner
#: image. The image bakes the workspace source (`COPY packages`) but `uv sync
#: --frozen` installs only the root meta-package's dependencies — and
#: `maistro-rsi` is deliberately NOT one of them (it is an optional member,
#: present in `[tool.uv.sources]` only), so without this the loop's first
#: import dies with "No module named maistro_rsi". Same fact the wrapper ships:
#: `tools/run_rsi_isolated.sh` line 57 (`PACKAGE_PATHS`) passed via
#: `-e PYTHONPATH=` on every run. Paths are relative to the image's
#: WORKDIR /workspace. Keep in step with that line.
PYTHONPATH_IN_CONTAINER = (
    "packages/maistro-core/src:packages/maistro-evolve/src:"
    "packages/maistro-rsi/src:packages/maistro-bootstrap/src"
)

#: The git config file `launch()` writes into the report dir (which is mounted
#: at REPORT_MOUNT_TARGET) and advertises via GIT_CONFIG_GLOBAL. It marks the
#: read-only source mount and its gitdir as safe for the container's user —
#: see container_argv for why a config file and not the env mechanism.
GIT_CONFIG_FILENAME = "gitconfig"


class DispatchError(RuntimeError):
    """The container backend could not start or lost a run. Surfaces as `errored`."""


def _settings() -> Any:
    """The Conductor's settings, imported at call time.

    Deferred for the same reason ``rsi_execution_policy`` defers it: the flat
    backend layout resolves ``config`` via ``sys.path``, and a module-scope
    import would make this module unimportable from the tests of other
    packages that reach into it statically.
    """
    from config import get_settings

    return get_settings()


def _docker_env(name: str, default: str) -> str:
    raw = getattr(_settings(), name, "") or ""
    return raw.strip() or default


def runner_image() -> str:
    return _docker_env("rsi_runner_image", DEFAULT_RUNNER_IMAGE)


def gateway_url() -> str:
    return _docker_env("rsi_gateway_url", DEFAULT_GATEWAY_URL)


def work_root() -> Path:
    """Host root under which per-run report directories are derived."""
    configured = (getattr(_settings(), "rsi_work_root", "") or "").strip()
    root = Path(configured).expanduser() if configured else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_docker(
    args: list[str], *, timeout_s: float | None = 60
) -> subprocess.CompletedProcess[str]:
    """One docker CLI call, as an argument vector, with the caller's timeout."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def unavailability_reason() -> str | None:
    """Why the dispatch backend cannot attest, or `None` when it can.

    Three distinct failures, each named: a missing CLI, an unreachable daemon,
    and an absent image read differently to an operator — the first two mean
    "give this process Docker", the third means "build the runner image".
    Answering only "docker available: true/false" would send every one of
    those operators down the same blind alley.
    """
    if shutil.which("docker") is None:
        return "the docker CLI is not on this process's PATH"
    probe = _run_docker(["info", "--format", "ok"], timeout_s=15)
    if probe.returncode != 0:
        return "the docker daemon is not reachable from this process"
    image = _run_docker(["image", "inspect", runner_image()], timeout_s=15)
    if image.returncode != 0:
        return (
            f"runner image {runner_image()} is not present — build it with "
            f"`docker build -f Dockerfile.rsi-runner -t {runner_image()} .`"
        )
    return None


def backend_available() -> bool:
    """Whether this process can launch the contained loop right now.

    The attestation ``rsi_execution_policy.require_isolation()`` rests on. It
    deliberately answers the whole question — CLI, daemon, and the image that
    actually contains the loop — because an attestation that answers a
    narrower question than the one being asked reads as containment to every
    caller.
    """
    return unavailability_reason() is None


@dataclass(frozen=True)
class DispatchSpec:
    """Everything one contained run needs, already resolved by the policy.

    Built by the service from values the route resolved at the trust boundary:
    an authorized repository, a named test profile as an argument vector, and
    output directories derived from the run id. Nothing here comes from the
    request as a path or a command.
    """

    run_id: str
    repo: Path
    test_argv: tuple[str, ...]
    cycles: int
    report_dir: Path
    agent_turns: int = 6
    model: str | None = None
    objective: str = ""
    targets: list[str] = field(default_factory=list)
    use_fitness: bool = False
    coverage_source: str = "."
    coverage_pytest_args: str = ""
    scout: bool = False
    genome_models: list[str] = field(default_factory=list)
    roster_size: int = 4
    report_every: int = 1


def build_spec(
    *,
    run_id: str,
    repo: Path,
    test_argv: tuple[str, ...],
    cycles: int,
    agent_turns: int,
    model: str | None,
    objective: str,
    targets: list[str],
    use_fitness: bool,
    coverage_source: str,
    coverage_pytest_args: str,
    scout: bool,
    genome_models: list[str],
    roster_size: int,
) -> DispatchSpec:
    """A spec whose report directory is derived from the run id (#305 carries).

    The request never names an output directory — the route refuses those —
    and the derivation lives here so the directory the Conductor polls and the
    directory the container writes are the same fact, not two spellings that
    can drift.
    """
    report_dir = work_root() / f"rsi-{run_id}" / "reports"
    return DispatchSpec(
        run_id=run_id,
        repo=repo,
        test_argv=tuple(test_argv),
        cycles=cycles,
        report_dir=report_dir,
        agent_turns=agent_turns,
        model=model,
        objective=objective,
        targets=list(targets),
        use_fitness=use_fitness,
        coverage_source=coverage_source,
        coverage_pytest_args=coverage_pytest_args,
        scout=scout,
        genome_models=list(genome_models),
        roster_size=roster_size,
    )


def _container_user() -> list[str]:
    """`--user` matching this process, so the loop can write the report mount.

    The runtime strips every capability (`--cap-drop=ALL`), and with them root
    loses CAP_DAC_OVERRIDE — a container running as root canNOT write a report
    directory owned by the host user (observed as EACCES on the loop's
    checkpoint write). Running
    the loop as THIS process's uid:gid makes the mount writable through
    ordinary permissions and keeps the loop unprivileged inside the container —
    the image-level `USER` fix the wrapper documents, applied at run time
    where the uid is actually known. POSIX only: Windows has no uid model, and
    its bind mounts do not enforce these bits.
    """
    if not hasattr(os, "getuid"):
        return []
    gid = os.getgid() if hasattr(os, "getgid") else os.getuid()
    return ["--user", f"{os.getuid()}:{gid}"]


def container_argv(spec: DispatchSpec) -> list[str]:
    """The full ``docker run`` argument vector for one contained run.

    Every value crosses as an argv token or an environment variable — the same
    rule ``tools/run_rsi_isolated.sh`` learned twice (#309): nothing free-text
    is ever interpolated into shell source, because there is no shell here at
    all. The container-side command is the loop's own argv (``--test-argv``
    carries the policy-resolved vector), so the only process that ever parses
    a command line is the container runtime itself.
    """
    repo_mount = f"{spec.repo.resolve()}:{REPO_MOUNT_TARGET}:ro"
    report_mount = f"{spec.report_dir}:{REPORT_MOUNT_TARGET}"
    network = (getattr(_settings(), "rsi_container_network", "") or "").strip()
    if not network:
        network = _detect_gateway_network()
    image = runner_image()

    loop_cmd: list[str] = [
        "/workspace/.venv/bin/python",
        "-m",
        "maistro_rsi",
        "run",
        "--repo",
        REPO_MOUNT_TARGET,
        # Parsed but never executed inside the container (argparse requires
        # it): the display form of the policy-resolved vector, exactly what
        # the service used to hand LocalRsiConfig as test_command. `--test-argv`
        # below WINS in LocalRsiLoop._run_tests, and it is what runs — with no
        # shell on either side of the boundary.
        "--test-cmd",
        " ".join(spec.test_argv),
        "--test-argv",
        json.dumps(list(spec.test_argv)),
        "--cycles",
        str(spec.cycles),
        "--report-every",
        str(spec.report_every),
        "--report-dir",
        REPORT_MOUNT_TARGET,
        "--export-patches",
        f"{REPORT_MOUNT_TARGET}/export",
        "--work-root",
        WORK_ROOT_IN_CONTAINER,
        "--agent-turns",
        str(spec.agent_turns),
    ]
    if spec.use_fitness:
        loop_cmd += ["--fitness"]
    if spec.model:
        loop_cmd += ["--model", spec.model]
    if spec.objective:
        loop_cmd += ["--objective", spec.objective]
    if spec.targets:
        loop_cmd += ["--targets", ",".join(spec.targets)]
    if spec.coverage_pytest_args:
        loop_cmd += [
            "--coverage-source",
            spec.coverage_source,
            "--coverage-pytest-args",
            spec.coverage_pytest_args,
        ]
    if spec.scout:
        loop_cmd += ["--scout"]
    if spec.genome_models:
        loop_cmd += [
            "--genome-db",
            f"{REPORT_MOUNT_TARGET}/population.db",
            "--genome-models",
            ",".join(spec.genome_models),
            "--roster-size",
            str(spec.roster_size),
        ]

    argv: list[str] = [
        "run",
        "--detach",
        "--rm",
        "--name",
        f"rsi-run-{spec.run_id}",
        "--label",
        f"{RUN_ID_LABEL}={spec.run_id}",
        "--network",
        network,
        # The gateway is published to host-loopback only; this is the fallback
        # route to it when the container is NOT on the gateway's compose
        # network.
        "--add-host=host.docker.internal:host-gateway",
        "--memory",
        _docker_env("rsi_container_memory", DEFAULT_MEMORY),
        "--cpus",
        _docker_env("rsi_container_cpus", DEFAULT_CPUS),
        "--pids-limit",
        _docker_env("rsi_container_pids", DEFAULT_PIDS),
        "--security-opt=no-new-privileges",
        "--cap-drop=ALL",
        *_container_user(),
        "-v",
        repo_mount,
        "-v",
        report_mount,
        "-e",
        f"LITELLM_URL={gateway_url()}",
        "-e",
        f"LITELLM_BASE_URL={gateway_url()}",
        "-e",
        f"LITELLM_PROXY_URL={gateway_url()}",
        "-e",
        f"LITELLM_API_BASE={gateway_url()}/v1",
    ]
    for key in _gateway_credentials():
        argv += ["-e", key]
    argv += ["-e", f"PYTHONPATH={PYTHONPATH_IN_CONTAINER}"]
    # The mounted authorized checkout is owned by the HOST user; the container
    # runs as the image's own user, so git's dubious-ownership guard would
    # refuse the one repo this container exists to read (git ≥2.35.2). The
    # allowance reaches git as a global config file `launch()` writes into the
    # report dir before starting the container (GIT_CONFIG_GLOBAL), because the
    # clone-time ownership check ignores command-line-scoped config — env
    # GIT_CONFIG_* entries pass `git log` yet are ignored by `git clone`.
    # Entries name exactly the mount target and its gitdir, never a wildcard:
    # this container exists to read one path, and no other.
    argv += ["-e", f"GIT_CONFIG_GLOBAL={REPORT_MOUNT_TARGET}/{GIT_CONFIG_FILENAME}"]
    argv += [image, *loop_cmd]
    return argv


def _detect_gateway_network() -> str:
    """The compose network the gateway container is actually on.

    Compose names the default network ``<project>_default``, which varies by
    layout, so hardcoding one breaks the other — the same detection the
    wrapper does, keyed on the fixed ``maistro-litellm`` container name.
    """
    probe = _run_docker(
        [
            "inspect",
            "maistro-litellm",
            "--format",
            '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{"\\n"}}{{end}}',
        ],
        timeout_s=15,
    )
    for line in (probe.stdout or "").splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return "bridge"


def _gateway_credentials() -> list[str]:
    """`-e KEY=VALUE` entries for the gateway key, taken from this process.

    The container needs the key to reach the gateway; keeping the key out of
    the *agent's* subprocesses is the loop's own job (its ``_SAFE_ENV``
    curation), just as it is under the wrapper's mounted ``.env``. Only the
    credential variables cross — the rest of this process's environment stays
    on this side of the boundary.
    """
    entries: list[str] = []
    seen: set[str] = set()
    for name in ("LITELLM_MASTER_KEY", "LITELLM_PROXY_KEY", "LITELLM_API_KEY"):
        value = os.environ.get(name)
        if value and name not in seen:
            seen.add(name)
            entries.append(f"{name}={value}")
    return entries


def launch(spec: DispatchSpec) -> str:
    """Start the contained run; return the container id.

    Raises ``DispatchError`` with the CLI's own stderr on failure — the run
    record shows an operator-facing summary, so the raw docker error stays
    here, in the server log, one frame away from the argv that caused it.
    """
    spec.report_dir.mkdir(parents=True, exist_ok=True)
    _write_gitconfig(spec.report_dir)
    argv = container_argv(spec)
    try:
        probe = _run_docker(argv, timeout_s=120)
    except subprocess.TimeoutExpired as exc:
        raise DispatchError("docker did not answer the run request in time") from exc
    if probe.returncode != 0:
        raise DispatchError(
            f"docker refused the run request (exit {probe.returncode}): "
            f"{(probe.stderr or probe.stdout or '').strip()[:400]}"
        )
    container_id = (probe.stdout or "").strip().splitlines()[-1] if probe.stdout else ""
    if not container_id:
        raise DispatchError("docker started no container and reported no id")
    return container_id


def _write_gitconfig(report_dir: Path) -> None:
    """The global git config the container reads (GIT_CONFIG_GLOBAL).

    Written host-side into the server-derived report dir before the container
    starts. Static content — the two safe paths and nothing else — so an
    attacker who could influence this file could only widen the ownership
    guard for paths the container can already read read-only.
    """
    (report_dir / GIT_CONFIG_FILENAME).write_text(
        f"[safe]\n\tdirectory = {REPO_MOUNT_TARGET}\n\tdirectory = {REPO_MOUNT_TARGET}/.git\n",
        encoding="utf-8",
    )


def stop_container(container_id: str) -> bool:
    """Stop a dispatched container. Bounded, idempotent, best-effort.

    A stop that times out does not raise: the container is wedged, not
    unkillable, and ``wait()`` still reaps its exit code when it eventually
    dies. Returning ``False`` means "it was already gone", which for
    cancellation is success by another name.
    """
    try:
        probe = _run_docker(
            ["stop", "--time", str(STOP_TIMEOUT_S), container_id], timeout_s=STOP_TIMEOUT_S + 30
        )
    except subprocess.TimeoutExpired:
        return True
    return probe.returncode == 0


def wait(container_id: str) -> int:
    """Block until the container exits; return its exit code.

    The one blocking call the service drives from a thread. If docker itself
    goes away mid-run (daemon restart without live-restore), the wait fails —
    and a run the backend can no longer observe must be reported errored, not
    left ``running`` forever against a container that no longer exists.
    """
    try:
        # No timeout: an RSI run is long by design, and `docker wait` returns
        # the moment the container exits however long that takes.
        probe = _run_docker(["wait", container_id], timeout_s=None)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover — unreachable with no timeout
        raise DispatchError("docker stopped answering while waiting on the run") from exc
    if probe.returncode == 0 and (probe.stdout or "").strip().isdigit():
        return int(probe.stdout.strip())
    state = _inspect_exit_code(container_id)
    if state is not None:
        return state
    raise DispatchError(
        f"lost contact with the runner container ({(probe.stderr or '').strip()[:200]})"
    )


def _inspect_exit_code(container_id: str) -> int | None:
    probe = _run_docker(["inspect", "--format", "{{.State.ExitCode}}", container_id], timeout_s=15)
    out = (probe.stdout or "").strip()
    if probe.returncode == 0 and out.isdigit():
        return int(out)
    return None


def poll_reports(report_dir: Path) -> dict[str, int]:
    """Cycle/promotion counts from the newest checkpoint the container wrote.

    The container writes ``checkpoint-*.json`` into the mounted report dir —
    the only channel through which run progress crosses back to the host. A
    missing or half-written checkpoint is not an error: the poller reads
    again on its next tick, and an unreadable *newest* checkpoint falls back
    to the newest readable one rather than reporting zeros the UI would read
    as "no progress".
    """
    if not report_dir.is_dir():
        return {}
    best: dict[str, int] = {}
    best_cycles = -1
    for path in report_dir.glob("checkpoint-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        cycles = data.get("cycles_run")
        if not isinstance(cycles, int) or cycles < best_cycles:
            continue
        best_cycles = cycles
        promotions = data.get("promotions")
        best = {
            "cycles_run": cycles,
            "promotions": promotions if isinstance(promotions, int) else 0,
        }
    return best


def final_summary(report_dir: Path) -> str | None:
    """The operator-facing one-liner from the run's last checkpoint."""
    counts = poll_reports(report_dir)
    if not counts:
        return None
    return (
        f"{counts.get('promotions', 0)} promotion(s) across {counts.get('cycles_run', 0)} cycle(s)"
    )


def describe(spec: DispatchSpec) -> str:
    """Human-readable echo of what would run, for logs — never a command line."""
    return (
        f"run={spec.run_id} image={runner_image()} repo={spec.repo} "
        f"test_argv={shlex.join(spec.test_argv)} cycles={spec.cycles} "
        f"report_dir={spec.report_dir}"
    )
