"""Interactive Questionary flows for maistro-install."""

from __future__ import annotations

from typing import Any

import questionary
import typer
from rich.console import Console
from rich.panel import Panel

from maistro_bootstrap.platform_detect import (
    deployment_hint,
    deployment_tier_gate_message,
    detect_container_runtime,
    environment_report,
    uname_summary,
)
from maistro_bootstrap.resolver import COMPOSE_ADDONS, FEATURES, PRODUCTS
from maistro_bootstrap.schema import InstallAnswersV1, parse_answers_dict

console = Console()

SIGNUP = {
    "OpenAI": "https://platform.openai.com/signup",
    "Anthropic": "https://console.anthropic.com/",
    "Google AI Studio": "https://aistudio.google.com/",
}


def _abort() -> None:
    raise typer.Exit(1)


def _stack_bringup() -> str:
    stack = questionary.confirm(
        "Request compose build from monorepo root (`docker compose build --pull never` on apply)?",
        default=False,
    ).ask()
    if stack is None:
        _abort()
    return "root_full" if stack else "none"


def _feature_set() -> list[str]:
    choices = [{"name": f.label, "value": f.id} for f in FEATURES.values()]
    picked = questionary.checkbox(
        "Select feature slices (commands are printed unless you use --apply for stack only):",
        choices=choices,
    ).ask()
    if picked is None:
        _abort()
    return [str(x) for x in picked]


def _compose_addon_set() -> list[str]:
    choices = [{"name": a.label, "value": a.id} for a in COMPOSE_ADDONS.values()]
    picked = questionary.checkbox(
        "Optional compose add-ons (validate / Podman merge):",
        choices=choices,
    ).ask()
    if picked is None:
        _abort()
    return [str(x) for x in picked]


def _product_key() -> str | None:
    product = questionary.select(
        "Scaffold a product with Copier? (optional)",
        choices=["(none)", *PRODUCTS.keys()],
    ).ask()
    if product is None:
        _abort()
    return None if product == "(none)" else str(product)


def _provider_panel() -> tuple[bool, bool]:
    console.print("\n[bold]Provider accounts[/bold] (sign up; never put API keys in YAML answers)")
    for name, url in SIGNUP.items():
        console.print(f"  • [link={url}]{name}[/link]")
    oa = questionary.confirm("Will you use an OpenAI API account?", default=False).ask()
    an = questionary.confirm("Will you use an Anthropic API account?", default=False).ask()
    if oa is None or an is None:
        _abort()
    return bool(oa), bool(an)


def _select_str(message: str, choices: list[str]) -> str:
    val = questionary.select(message, choices=choices).ask()
    if val is None:
        _abort()
    return str(val)


def preflight_lines(runtime: str, runtime_hint: str, env: dict[str, Any]) -> list[str]:
    """The preflight banner, as values.

    A function rather than four `console.print` calls inline, so what the
    installer tells an operator about isolation is assertable without driving
    the interactive wizard. That claim is the whole of #81, and it was the one
    part of that change no test could reach.
    """
    sandbox = env["sandbox"]
    # The sandbox line sits next to the hypervisor inventory on purpose: the two
    # used to be conflated, and "kvm" on the Virtualization line reads as "this
    # host can isolate untrusted code" when the engine ships no VM backend at
    # all. Yellow when nothing can isolate, because that is a refusal waiting to
    # happen rather than a note.
    style = "dim" if sandbox["sandbox_binary_present"] else "yellow"
    return [
        f"[dim]Container runtime:[/dim] {runtime} — {runtime_hint}",
        f"[dim]Admin:[/dim] {env['admin_hint']}",
        f"[dim]Virtualization:[/dim] {', '.join(env['virtualization'])}",
        f"[{style}]Sandbox:[/{style}] {sandbox['summary']}\n",
    ]


def print_preflight(runtime: str, runtime_hint: str, env: dict[str, Any]) -> None:
    for line in preflight_lines(runtime, runtime_hint, env):
        console.print(line)


def collect_answers_interactive() -> InstallAnswersV1:
    console.print(
        Panel.fit(
            f"[bold]Environment[/bold]\n{uname_summary()}\n{deployment_hint()}",
            title="maistro-install",
        )
    )
    det, hint = detect_container_runtime()
    print_preflight(det, hint, environment_report())

    stack_bringup = _stack_bringup()
    features = _feature_set()
    compose_addons = _compose_addon_set()
    prod = _product_key()
    oa, an = _provider_panel()

    llm_gateway = _select_str("LLM gateway preference:", ["litellm", "direct", "other"])
    obs = _select_str(
        "Observability backend (compose / manifest intent):",
        ["none", "langfuse_v2", "langfuse_v3", "arize"],
    )
    dep = _select_str(
        "Deployment tier:",
        [
            "local_docker",
            "local_podman",
            "vm",
            "lxc",
            "proxmox",
            "bare_metal",
        ],
    )
    gate = deployment_tier_gate_message(dep)
    if gate:
        console.print(Panel.fit(f"[yellow]{gate}[/yellow]", title="Deployment note"))

    crt_default = "auto"
    if det == "docker":
        crt_default = "docker"
    elif det == "podman":
        crt_default = "podman"
    crt = questionary.select(
        "Container runtime for stack bring-up:",
        choices=["auto", "docker", "podman"],
        default=crt_default,
    ).ask()
    if crt is None:
        _abort()

    users_i = _select_str(
        "User / tenancy intent:",
        ["skip", "bootstrap_admin", "sso_later"],
    )
    delivery_mode = _select_str(
        "Install delivery (same runtime behavior; source build takes longer):",
        ["image_pull", "source_build"],
    )
    sandbox = _select_str(
        "Sandbox profile (safe is default; unsupported options require building from source):",
        ["safe", "developer"],
    )
    crypto_profile = _select_str(
        "Crypto / identity profile:",
        ["distributed_identity_root", "no_crypto", "full_all_crypto"],
    )
    admin_user = questionary.text("Admin user name:", default="maistro-admin").ask()
    daily_user = questionary.text("Daily driver user 1:", default="maistro-user").ask()
    if admin_user is None or daily_user is None:
        _abort()

    raw: dict[str, Any] = {
        "schema_version": "1",
        "install_mode": "preview",
        "features": features,
        "compose_addons": compose_addons,
        "product": prod,
        "dry_run": True,
        "llm_gateway": llm_gateway,
        "observability_backend": obs,
        "deployment_tier": dep,
        "container_runtime": str(crt),
        "users_intent": users_i,
        "stack_bringup": stack_bringup,
        "provider_accounts": {"openai": oa, "anthropic": an},
        "install_surface": "curl",
        "delivery_mode": delivery_mode,
        "sandbox_profile": sandbox,
        "crypto_profile": crypto_profile,
        "admin_user": admin_user,
        "daily_driver_user": daily_user,
        "reactor_enabled": True,
    }
    return parse_answers_dict(raw)


def _password_with_confirm(label: str, attempts: int = 3) -> str:
    for _ in range(attempts):
        pw = questionary.password(f"{label} password:").ask()
        if pw is None:
            _abort()
        if not pw:
            console.print("[yellow]Password must not be empty.[/yellow]")
            continue
        confirm = questionary.password(f"Confirm {label.lower()} password:").ask()
        if confirm is None:
            _abort()
        if pw == confirm:
            return str(pw)
        console.print("[yellow]Passwords do not match — try again.[/yellow]")
    console.print("[red]Too many mismatched attempts.[/red]")
    _abort()
    raise AssertionError("unreachable")


def collect_bootstrap_credentials(answers: InstallAnswersV1) -> dict[str, Any]:
    """Prompt for first-run account passwords (never stored in answers YAML).

    Returns the /v1/setup/complete payload; the caller stages it 0600 via
    credentials.write_bootstrap_credentials for one-shot consumption.
    """
    from maistro_bootstrap.credentials import build_bootstrap_credentials

    console.print(
        Panel.fit(
            f"[bold]First-run accounts[/bold]\n"
            f"Admin (break-glass, no chat): {answers.admin_user}\n"
            f"Daily driver 1:               {answers.daily_driver_user}\n"
            "Passwords are staged once, sent to the server at bring-up, then shredded.",
            title="bootstrap credentials",
        )
    )
    admin_pw = _password_with_confirm("Admin")
    user_pw = _password_with_confirm("Daily driver")
    return build_bootstrap_credentials(answers, admin_password=admin_pw, user_password=user_pw)
