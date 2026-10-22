"""The conformance cases' FAILURE branches (#974).

A conformance case that could not detect a violating subject would silently
pass one — the runner's detectors are its product. The happy paths are proven
end-to-end by `test_runner_and_report.py` through real subjects; this module
proves each detector's rejection verdicts directly. Two shapes:

- doctored environments (a context that lies about its capabilities, a grant
  wider than its declaration, a host that misbehaves in exactly one way) —
  states a correct host never produces, which is precisely why the cases must
  distrust their inputs and answer False;
- in-process CLI/`__main__`/reference-materializer paths that the subprocess
  and tmpdir runs exercise but coverage cannot see.

The `_case_*` / `_resolve_handler`-level imports are deliberate: these are
unit tests of the detectors, not of the runner plumbing around them.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from maistro_ext_harness import (
    CAPABILITIES,
    DiscoveredExtension,
    ExtensionContext,
    ExtensionHost,
    Grant,
    GrantPolicy,
    HandlerRaised,
    InvocationCancelled,
    LoadedExtension,
    build_context,
    reference_fixtures,
    resolve_grants,
    write_failing_probe_extension,
    write_reference_extension,
)
from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.cli import main as cli_main
from maistro_ext_harness.families import (
    _case_context_least_authority as case_least_authority,
)
from maistro_ext_harness.families import (
    _case_entrypoint_in_own_namespace as case_entrypoint_own_namespace,
)
from maistro_ext_harness.families import (
    _case_harness_cancellation as case_cancellation,
)
from maistro_ext_harness.families import (
    _case_harness_failure_containment as case_failure_contained,
)
from maistro_ext_harness.families import (
    _case_manifest_revalidates as case_manifest_revalidates,
)
from maistro_ext_harness.families import (
    _case_tool_handler_invocation as case_tool_invocation,
)
from maistro_ext_harness.families import (
    _case_tool_repeat_stable as case_tool_repeat_stable,
)
from maistro_ext_harness.families import (
    _case_undeclared_authority_invisible as case_authority_invisible,
)
from maistro_ext_harness.families import builtin_cases, shared_cases
from maistro_ext_harness.manifest import load_manifest_bytes

# ---------------------------------------------------------------------------
# Environment fabrication
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LyingContext(ExtensionContext):
    """A context object whose `has_capability` answers apart from its set.

    A correct host can never build one (`build_context` derives both from the
    same grant) — that is exactly the future host bug the least-authority
    cases must still catch, so the detector tests hand the case one.
    """

    lie: str = ""

    def has_capability(self, name: str) -> bool:
        return name == self.lie or super().has_capability(name)


class StubHost:
    """A host stub whose `invoke` does exactly what the test scripted."""

    def __init__(self, invoke: Any = None) -> None:
        self._invoke = invoke
        self.released: list[LoadedExtension] = []

    def invoke(self, loaded: LoadedExtension) -> object:
        if self._invoke is None:
            return "ok"
        return self._invoke(loaded)

    def release(self, loaded: LoadedExtension) -> None:
        self.released.append(loaded)


def _raw_manifest() -> dict[str, Any]:
    return {
        "id": "acme.widget",
        "publisher": "acme",
        "version": "1.0.0",
        "title": "ACME widget",
        "description": "suite fixture",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": [],
        "effects": ["read-only"],
        "data": {"scopes": []},
        "entrypoint": {"module": "acme_widget.plugin", "object": "PLUGIN"},
    }


def _manifest(**overrides: Any) -> Any:
    return load_manifest_bytes(json.dumps({**_raw_manifest(), **overrides}))


def _fixture_kwargs() -> dict[str, Any]:
    fx = reference_fixtures()
    return {
        "identity": fx.identity,
        "workspace": fx.workspace,
        "invocation": fx.invocation,
    }


def _loaded(
    manifest: Any,
    grant: Grant | None,
    context: ExtensionContext | None,
    plugin_object: object = None,
    calls: list[str] | None = None,
) -> LoadedExtension:
    module = types.ModuleType("fabricated_subject")
    module.PLUGIN = plugin_object  # type: ignore[attr-defined]
    module.CALLS = calls if calls is not None else []  # type: ignore[attr-defined]
    return LoadedExtension(
        manifest=manifest,
        grant=grant,
        module=module,
        plugin_object=plugin_object,
        context=context,
        fixtures=reference_fixtures(),
    )


def _env(
    loaded: LoadedExtension,
    grant: Any,
    manifest: Any,
    host: Any,
    discovered: Any = None,
) -> Any:
    """A CaseEnvironment-shaped namespace over doctored parts.

    The case functions read attributes only; a stub stands in where the test
    doctors behavior the real dataclass could not carry. `context` mirrors the
    real environment's property so the security cases read the loaded one.
    """
    return types.SimpleNamespace(
        subject="fabricated",
        host=host,
        discovered=discovered
        or DiscoveredExtension(root=Path("."), manifest_path=Path("extension.json")),
        manifest=manifest,
        grant=grant,
        loaded=loaded,
        context=getattr(loaded, "context", None),
        backends=BackendRegistry(),
    )


# ---------------------------------------------------------------------------
# Registry surface: builtin_cases (the suite's own test seam)
# ---------------------------------------------------------------------------


def test_builtin_cases_extends_the_shared_suite_and_keeps_ids_unique() -> None:
    shared = shared_cases()
    builtin = builtin_cases()
    assert len(builtin) > len(shared), "every family plug-in must contribute extra cases"
    ids = [case.case_id for case in builtin]
    assert len(ids) == len(set(ids)), "a duplicated case id would make reports ambiguous"


# ---------------------------------------------------------------------------
# Manifest revalidation detector
# ---------------------------------------------------------------------------


def test_manifest_revalidates_detector_rejects_a_manifest_that_changed_on_disk(
    make_extension: Any,
) -> None:
    """The subject swapping its manifest after validation must be caught."""
    root = make_extension(
        package="acme_swap",
        manifest={
            **_raw_manifest(),
            "entrypoint": {"module": "acme_swap.plugin", "object": "PLUGIN"},
        },
    )
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)

    changed = json.loads((root / "extension.json").read_text(encoding="utf-8"))
    changed["version"] = "9.9.9"
    (root / "extension.json").write_text(json.dumps(changed), encoding="utf-8")

    try:
        outcome = case_manifest_revalidates(_env(loaded, grant, manifest, host, discovered))
    finally:
        host.release(loaded)
    assert not outcome.passed
    assert "re-parsed to a different contract" in outcome.detail


def test_manifest_revalidates_detector_accepts_an_unchanged_manifest(
    conforming_extension: Path,
) -> None:
    host = ExtensionHost()
    discovered = host.discover(conforming_extension)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)
    try:
        assert case_manifest_revalidates(_env(loaded, grant, manifest, host, discovered)).passed
    finally:
        host.release(loaded)


# ---------------------------------------------------------------------------
# Entrypoint-namespace detector
# ---------------------------------------------------------------------------


def test_entrypoint_own_namespace_detector_rejects_a_foreign_module_root() -> None:
    """An entrypoint naming a package outside the extension's tree is a
    smuggling shape: the code it would load was never part of the subject."""
    manifest = _manifest(entrypoint={"module": "outside.plugin", "object": "PLUGIN"})
    grant = resolve_grants(manifest)
    env = _env(
        _loaded(manifest, grant, build_context(grant, **_fixture_kwargs())),
        grant,
        manifest,
        ExtensionHost(),
    )
    outcome = case_entrypoint_own_namespace(env)
    assert not outcome.passed
    assert "does not name a package inside" in outcome.detail


# ---------------------------------------------------------------------------
# Least-authority detector: the context is the suspect
# ---------------------------------------------------------------------------


def test_least_authority_detector_rejects_a_context_wider_than_the_grant() -> None:
    manifest = _manifest()
    grant = resolve_grants(manifest)
    context = ExtensionContext(
        capabilities=frozenset({"secrets.read"}),
        identity=None,
        workspace=None,
        invocation=None,
    )
    outcome = case_least_authority(_env(_loaded(manifest, grant, context), grant, manifest, None))
    assert not outcome.passed
    assert "but the grant is" in outcome.detail


def test_least_authority_detector_rejects_a_context_that_lies_about_a_capability() -> None:
    manifest = _manifest(capabilities=[CAPABILITIES[0]])
    grant = resolve_grants(manifest)
    context = LyingContext(
        capabilities=grant.capabilities,
        identity=None,
        workspace=None,
        invocation=None,
        lie="secrets.read",
    )
    outcome = case_least_authority(_env(_loaded(manifest, grant, context), grant, manifest, None))
    assert not outcome.passed
    assert "ungranted capability" in outcome.detail


def test_least_authority_detector_rejects_a_non_authority_name_answer() -> None:
    """A name outside the closed vocabulary must be invisible, not answered
    by accident: the detector probes it explicitly."""
    manifest = _manifest(capabilities=sorted(CAPABILITIES))
    grant = resolve_grants(manifest)
    context = LyingContext(
        capabilities=grant.capabilities,
        identity=None,
        workspace=None,
        invocation=None,
        lie="not-an-authority-name",
    )
    outcome = case_least_authority(_env(_loaded(manifest, grant, context), grant, manifest, None))
    assert not outcome.passed
    assert "non-authority name" in outcome.detail


# ---------------------------------------------------------------------------
# Undeclared-authority detector: grant/context disagreement
# ---------------------------------------------------------------------------


def _grant_widened(grant: Grant, capability: str) -> Grant:
    return Grant(
        capabilities=grant.capabilities | {capability},
        effects=grant.effects,
        data_scopes=grant.data_scopes,
        network_allow=grant.network_allow,
        network_ports=grant.network_ports,
        filesystem_paths=grant.filesystem_paths,
        filesystem_mode=grant.filesystem_mode,
        secrets=grant.secrets,
    )


def test_authority_invisible_detector_rejects_a_grant_wider_than_its_declaration() -> None:
    manifest = _manifest()
    grant = _grant_widened(resolve_grants(manifest), "secrets.read")
    context = build_context(grant, **_fixture_kwargs())
    outcome = case_authority_invisible(
        _env(_loaded(manifest, grant, context), grant, manifest, None)
    )
    assert not outcome.passed
    assert "grant exceeds declaration" in outcome.detail


def _grant_narrowed(grant: Grant, capability: str) -> Grant:
    return Grant(
        capabilities=grant.capabilities - {capability},
        effects=grant.effects,
        data_scopes=grant.data_scopes,
        network_allow=grant.network_allow,
        network_ports=grant.network_ports,
        filesystem_paths=grant.filesystem_paths,
        filesystem_mode=grant.filesystem_mode,
        secrets=grant.secrets,
    )


def test_authority_invisible_detector_rejects_views_present_without_their_capability() -> None:
    """A narrowed grant whose context still shows the narrowed-away view —
    the exact host bug the case exists to catch."""
    manifest = _manifest(
        capabilities=["workspace.read", "agent.read", "run.read"],
        data={"scopes": ["workspace"]},
    )
    full = resolve_grants(manifest)
    narrowed = _grant_narrowed(full, "agent.read")
    # The context was built for the FULL grant; the case receives the narrowed one.
    context = build_context(full, **_fixture_kwargs())
    outcome = case_authority_invisible(
        _env(_loaded(manifest, narrowed, context), narrowed, manifest, None)
    )
    assert not outcome.passed
    assert "identity view" in outcome.detail


def test_authority_invisible_detector_accepts_a_consistently_narrowed_grant() -> None:
    manifest = _manifest(
        capabilities=["workspace.read", "agent.read", "run.read"],
        data={"scopes": ["workspace"]},
    )
    narrowed = resolve_grants(manifest, GrantPolicy(capabilities={"workspace.read"}))
    context = build_context(narrowed, **_fixture_kwargs())
    outcome = case_authority_invisible(
        _env(_loaded(manifest, narrowed, context), narrowed, manifest, None)
    )
    assert outcome.passed
    assert "narrowed subset" in outcome.detail


# ---------------------------------------------------------------------------
# Failure containment + cancellation detectors: the host is the suspect
# ---------------------------------------------------------------------------


def test_failure_contained_detector_rejects_a_containment_that_lost_the_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def causeless(_self: object, _loaded: LoadedExtension) -> object:
        raise HandlerRaised("contained, but nothing caused it")

    monkeypatch.setattr(ExtensionHost, "invoke", causeless)
    outcome = case_failure_contained(
        _env(_loaded(_manifest(), None, None), None, None, ExtensionHost())
    )
    assert not outcome.passed
    assert "lost the original cause" in outcome.detail


def test_failure_contained_detector_rejects_a_host_that_reports_no_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ExtensionHost, "invoke", lambda _self, _loaded: "swallowed")
    outcome = case_failure_contained(
        _env(_loaded(_manifest(), None, None), None, None, ExtensionHost())
    )
    assert not outcome.passed
    assert "did not surface as HandlerRaised" in outcome.detail


def test_cancellation_detector_rejects_a_handler_that_ran_anyway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ran_despite_cancel(_self: object, loaded: LoadedExtension) -> object:
        loaded.module.CALLS.append("ghost-call")  # type: ignore[attr-defined]
        raise InvocationCancelled("refused")

    monkeypatch.setattr(ExtensionHost, "invoke", ran_despite_cancel)
    outcome = case_cancellation(_env(_loaded(_manifest(), None, None), None, None, ExtensionHost()))
    assert not outcome.passed
    assert "handler ran despite host-side cancellation" in outcome.detail


def test_cancellation_detector_rejects_a_host_that_invoked_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ExtensionHost, "invoke", lambda _self, _loaded: "silently ran")
    outcome = case_cancellation(_env(_loaded(_manifest(), None, None), None, None, ExtensionHost()))
    assert not outcome.passed
    assert "invoked a handler after cancellation" in outcome.detail


# ---------------------------------------------------------------------------
# Tool-family detectors: entrypoint protocol failures
# ---------------------------------------------------------------------------


def test_tool_invocation_detector_rejects_an_unresolvable_handler() -> None:
    manifest = _manifest()
    grant = resolve_grants(manifest)
    loaded = _loaded(
        manifest, grant, build_context(grant, **_fixture_kwargs()), {"handler": "absent"}
    )
    outcome = case_tool_invocation(_env(loaded, grant, manifest, ExtensionHost()))
    assert not outcome.passed
    assert "did not resolve" in outcome.detail


def test_tool_invocation_detector_rejects_an_entrypoint_that_is_neither_mapping_nor_callable() -> (
    None
):
    manifest = _manifest()
    grant = resolve_grants(manifest)
    loaded = _loaded(manifest, grant, build_context(grant, **_fixture_kwargs()), 42)
    outcome = case_tool_invocation(_env(loaded, grant, manifest, ExtensionHost()))
    assert not outcome.passed
    assert "neither a handler mapping nor callable" in outcome.detail


def test_tool_invocation_detector_rejects_a_handler_that_raises(
    make_extension: Any,
) -> None:
    """End-to-end through a real host: a raising tool handler is a FAILED
    conformance case, never a crash of the runner."""
    root = make_extension(
        package="acme_detonate",
        manifest={
            **_raw_manifest(),
            "entrypoint": {"module": "acme_detonate.plugin", "object": "PLUGIN"},
        },
        plugin_source=(
            "PLUGIN: dict[str, object] = {'kind': 'tool', 'handler': 'detonate'}\n"
            "def detonate() -> str:\n"
            "    raise RuntimeError('fabricated')\n"
            "HANDLERS = {'detonate': detonate}\n"
        ),
    )
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    grant = host.grants_for(manifest)
    loaded = host.load(discovered, manifest, grant)
    try:
        outcome = case_tool_invocation(_env(loaded, grant, manifest, host))
    finally:
        host.release(loaded)
    assert not outcome.passed
    assert "raised on invocation" in outcome.detail


def test_tool_repeat_detector_rejects_a_handler_that_raises_on_repeat() -> None:
    manifest = _manifest()
    grant = resolve_grants(manifest)

    def detonate(_loaded: LoadedExtension) -> object:
        raise HandlerRaised("second call exploded")

    loaded = _loaded(
        manifest, grant, build_context(grant, **_fixture_kwargs()), {"handler": "spin"}
    )
    outcome = case_tool_repeat_stable(_env(loaded, grant, manifest, StubHost(invoke=detonate)))
    assert not outcome.passed
    assert "repeat invocation raised" in outcome.detail


def test_tool_repeat_detector_rejects_a_refused_repeat() -> None:
    manifest = _manifest()
    grant = resolve_grants(manifest)

    def refuse(_loaded: LoadedExtension) -> object:
        raise InvocationCancelled("host refused the repeat")

    loaded = _loaded(
        manifest, grant, build_context(grant, **_fixture_kwargs()), {"handler": "spin"}
    )
    outcome = case_tool_repeat_stable(_env(loaded, grant, manifest, StubHost(invoke=refuse)))
    assert not outcome.passed
    assert "refused a repeat invocation" in outcome.detail


# ---------------------------------------------------------------------------
# Lifecycle handler resolution: the documented failure shapes
# ---------------------------------------------------------------------------


def test_lifecycle_rejects_a_mapping_entrypoint_without_a_string_handler() -> None:
    from maistro_ext_harness.lifecycle import HandlerMissing, _resolve_handler

    manifest = _manifest()
    grant = resolve_grants(manifest)
    loaded = _loaded(manifest, grant, build_context(grant, **_fixture_kwargs()), {"kind": "tool"})
    with pytest.raises(HandlerMissing, match=r"without.*string 'handler'"):
        _resolve_handler(loaded)


def test_lifecycle_rejects_a_handler_attribute_that_is_not_callable() -> None:
    from maistro_ext_harness.lifecycle import HandlerMissing, _resolve_handler

    manifest = _manifest()
    grant = resolve_grants(manifest)
    loaded = _loaded(
        manifest, grant, build_context(grant, **_fixture_kwargs()), {"handler": "not_a_fn"}
    )
    loaded.module.not_a_fn = 42  # type: ignore[attr-defined]
    with pytest.raises(HandlerMissing, match=r"not callable"):
        _resolve_handler(loaded)


def test_lifecycle_rejects_an_entrypoint_missing_from_the_tree(make_extension: Any) -> None:
    """A manifest whose entrypoint names a package the subject does not ship:
    validation (lexical) accepts it, loading (the first code that runs) must
    refuse it by name."""
    broken = {**_raw_manifest(), "entrypoint": {"module": "ghost.plugin", "object": "PLUGIN"}}
    root = make_extension(manifest=broken)
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    with pytest.raises(Exception, match=r"does not exist under"):
        host.load(discovered, manifest, host.grants_for(manifest))


def test_lifecycle_handles_a_builtin_without_an_inspectable_signature(
    make_extension: Any,
) -> None:
    """A handler `inspect.signature` cannot read (`iter` is a builtin with no
    text signature) falls back to the zero-argument call — the documented
    data-only protocol, not a crash. `iter(context)` then raises TypeError
    (the context is not iterable) and containment wraps it."""
    root = make_extension(
        package="acme_len",
        manifest={
            **_raw_manifest(),
            "entrypoint": {"module": "acme_len.plugin", "object": "PLUGIN"},
        },
        plugin_source="import builtins\nPLUGIN = iter\n",
    )
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    loaded = host.load(discovered, manifest, host.grants_for(manifest))
    try:
        with pytest.raises(HandlerRaised) as excinfo:
            host.invoke(loaded)
    finally:
        host.release(loaded)
    assert isinstance(excinfo.value.__cause__, TypeError)


# ---------------------------------------------------------------------------
# Reference materializer: the overwrite guard
# ---------------------------------------------------------------------------


def test_reference_materializer_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    write_reference_extension(tmp_path)
    with pytest.raises(FileExistsError, match=r"refusing to materialize"):
        write_reference_extension(tmp_path)


def test_reference_materializer_accepts_an_empty_existing_destination(tmp_path: Path) -> None:
    """The guard is against clobbering CONTENT, not against an existing
    (empty) directory a test or CI pre-created."""
    dest = tmp_path / "precreated"
    dest.mkdir()
    written = write_reference_extension(dest)
    assert (written / "extension.json").is_file()


def test_failing_probe_materializer_carries_a_raising_handler(tmp_path: Path) -> None:
    root = write_failing_probe_extension(tmp_path)
    assert "raise" in (root / "src" / "harness_probe_failure" / "plugin.py").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# `python -m maistro_ext_harness`: importable, side-effect-free
# ---------------------------------------------------------------------------


def test_dunder_main_is_importable_without_running_the_cli() -> None:
    """The `-m` shim must bind `main` and do nothing else on import — a
    module-level run would execute the suite at import time."""
    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        module = importlib.import_module("maistro_ext_harness.__main__")
    assert stdout.getvalue() == ""
    assert callable(module.main)


# ---------------------------------------------------------------------------
# The CLI's could-not-run and reporting paths, in process
# ---------------------------------------------------------------------------


def test_cli_in_process_writes_the_report_and_prints_its_path(
    conforming_extension: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"
    code = cli_main(["run", "--path", str(conforming_extension), "--report", str(report_path)])
    assert code == 0
    assert f"report: {report_path}" in capsys.readouterr().out
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert document["summary"]["failed"] == 0
    assert document["certification"]["platform_certified"] is False


def test_cli_in_process_prints_failed_cases_and_exits_1(
    make_extension: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    plugin = "PLUGIN: dict[str, object] = {'kind': 'tool', 'handler': 'absent'}\n"
    code = cli_main(["run", "--path", str(make_extension(plugin_source=plugin))])
    assert code == 1
    assert "FAIL" in capsys.readouterr().err


def test_cli_in_process_prints_could_not_run_errors_and_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["run", "--path", str(tmp_path / "absent")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_in_process_names_a_rejected_manifest_as_could_not_run(
    make_extension: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_extension(manifest={**_raw_manifest(), "family": "nope"})
    code = cli_main(["run", "--path", str(root)])
    assert code == 2
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Backends: a probe that raises is an unavailable service, not a crash
# ---------------------------------------------------------------------------


def test_backend_probe_that_raises_is_unavailable_fail_closed() -> None:
    from maistro_ext_harness import Backend, BackendRegistry

    registry = BackendRegistry()
    registry.register(
        Backend(name="real-service", probe=lambda: (_ for _ in ()).throw(RuntimeError("down")))
    )
    assert registry.probe("real-service") is False


# ---------------------------------------------------------------------------
# Remaining detector branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("narrowed", "view"),
    [
        ("workspace.read", "workspace view"),
        ("agent.read", "identity view"),
        ("run.read", "invocation view"),
    ],
)
def test_authority_invisible_detector_names_each_hidden_view(narrowed: str, view: str) -> None:
    manifest = _manifest(
        capabilities=["workspace.read", "agent.read", "run.read"],
        data={"scopes": ["workspace"]},
    )
    full = resolve_grants(manifest)
    narrowed_grant = _grant_narrowed(full, narrowed)
    context = build_context(full, **_fixture_kwargs())
    outcome = case_authority_invisible(
        _env(_loaded(manifest, narrowed_grant, context), narrowed_grant, manifest, None)
    )
    assert not outcome.passed
    assert view in outcome.detail


def test_tool_invocation_detector_accepts_a_callable_entrypoint_object() -> None:
    """The data-only protocol's second shape: the entrypoint object is itself
    the callable handler, no mapping needed."""

    def handler() -> str:
        return "ok"

    manifest = _manifest()
    grant = resolve_grants(manifest)
    loaded = _loaded(manifest, grant, build_context(grant, **_fixture_kwargs()), handler)
    outcome = case_tool_invocation(_env(loaded, grant, manifest, ExtensionHost()))
    assert outcome.passed
    assert "handler" in outcome.detail


def test_lifecycle_loads_a_flat_layout_extension(make_extension: Any, tmp_path: Any) -> None:
    """`src/` is a convention, not the contract: a package at the extension
    root (no src/) must load identically."""
    package = "acme_flat"
    root = tmp_path / "flat-ext"
    (root / package).mkdir(parents=True)
    (root / "extension.json").write_text(
        json.dumps(
            {
                **_raw_manifest(),
                "entrypoint": {"module": f"{package}.plugin", "object": "PLUGIN"},
            }
        ),
        encoding="utf-8",
    )
    (root / package / "__init__.py").write_text("\n", encoding="utf-8")
    (root / package / "plugin.py").write_text(
        "PLUGIN = {'kind': 'tool', 'handler': 'spin'}\n"
        "def spin() -> str:\n"
        "    return 'flat-ok'\n"
        "HANDLERS = {'spin': spin}\n",
        encoding="utf-8",
    )
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    loaded = host.load(discovered, manifest, host.grants_for(manifest))
    try:
        assert host.invoke(loaded) == "flat-ok"
    finally:
        host.release(loaded)


def test_lifecycle_propagates_a_contract_error_from_invoke_undwrapped(
    make_extension: Any,
) -> None:
    """A handler raising a ContractError is re-raised as itself — wrapping a
    typed contract failure as HandlerRaised would erase its type for CI."""
    from maistro_ext_harness import ContractError

    root = make_extension(
        package="acme_contract",
        manifest={
            **_raw_manifest(),
            "entrypoint": {"module": "acme_contract.plugin", "object": "PLUGIN"},
        },
        plugin_source=(
            "from maistro_ext_harness.contract import ContractError\n"
            "PLUGIN = {'kind': 'tool', 'handler': 'refuse'}\n"
            "def refuse() -> str:\n"
            "    raise ContractError('contract refusal')\n"
            "HANDLERS = {'refuse': refuse}\n"
        ),
    )
    host = ExtensionHost()
    discovered = host.discover(root)
    manifest = host.validate(discovered)
    loaded = host.load(discovered, manifest, host.grants_for(manifest))
    try:
        with pytest.raises(ContractError, match=r"contract refusal") as excinfo:
            host.invoke(loaded)
    finally:
        host.release(loaded)
    assert not isinstance(
        excinfo.value, __import__("maistro_ext_harness", fromlist=["HandlerRaised"]).HandlerRaised
    )


def test_runner_with_reference_materializes_the_builtin_reference(
    conforming_extension: Path,
) -> None:
    """`with_reference` without a pinned root materializes the built-in
    reference into a scratch dir for the run — the same case IDs run against
    both subjects, and the scratch dir does not outlive the run."""
    from maistro_ext_harness import RunRequest, run_conformance

    report = run_conformance(RunRequest(subject=conforming_extension, with_reference=True))
    assert {subject.role for subject in report.subjects} == {"external", "reference"}
    # CaseRecord.subject is the role string; the same case IDs must have run
    # against both subjects for the comparison to mean anything.
    by_role: dict[str, set[str]] = {}
    for record in report.cases:
        by_role.setdefault(record.subject, set()).add(record.case_id)
    assert set(by_role) == {"external", "reference"}
    assert by_role["external"] == by_role["reference"]
    assert report.passed_count == len(report.cases)


def test_runner_with_a_pinned_reference_root_skips_materialization(
    conforming_extension: Path,
) -> None:
    """A caller may pin its own reference copy — the repo's real
    `extensions/reference-greeter` is the anchor case."""
    from maistro_ext_harness import RunRequest, run_conformance

    repo_reference = Path(__file__).resolve().parents[3] / "extensions" / "reference-greeter"
    report = run_conformance(
        RunRequest(
            subject=conforming_extension,
            with_reference=True,
            reference_root=repo_reference,
        )
    )
    assert {subject.role for subject in report.subjects} == {"external", "reference"}
    assert report.passed_count == len(report.cases)
