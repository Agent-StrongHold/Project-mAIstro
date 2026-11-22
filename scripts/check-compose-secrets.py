#!/usr/bin/env python3
"""A tracked Compose file must not carry a credential anyone can read (#367).

`docker-compose.pm-poc.yml` shipped this, alongside `REQUIRE_AUTH=true`:

    - API_KEYS=alice:changeme-alice,bob:changeme-bob
    - MAISTRO_ROUTER_API_KEY=${API_KEYS:-alice:changeme-alice}

So the overlay read as a ready-to-run authenticated deployment whose keys are
published in this repository, and the `:-` on the second line meant a caller who
set nothing still got the known value rather than an error.

Every other tracked profile already had the right shape -- `${DB_PASSWORD:?Set
DB_PASSWORD in .env}`, `${API_KEYS:?Run ./install.sh to generate API_KEYS}` --
which is what makes this checkable rather than a matter of taste. The rule is
the convention the repository already follows:

**A secret-shaped environment variable in a tracked Compose file is either
required (`${VAR:?message}`) or optional-and-empty (`${VAR:-}`). Never a
literal, and never a non-empty fallback.**

And, since #402 (the `MAISTRO_ACCESS_TOKEN` removal):

**A secret-shaped variable a tracked Compose file hands to a service or
interpolates from the environment must have a consumer.** Either production
code under `packages/` reads it (matched case-insensitively, because a
pydantic setting named `maistro_router_api_key` is the reader for the env var
`MAISTRO_ROUTER_API_KEY`), the tracked LiteLLM config names it, or it is in
`_THIRD_PARTY_CONSUMERS` below -- the reviewed list of names whose reader is
another image (postgres, redis, langfuse, the LiteLLM gateway's
provider-convention keys). A variable that fails all three is a dead
credential-shaped knob: rotating it protects nothing and setting it enforces
nothing, which is exactly the false confidence this gate exists to prevent.
`MAISTRO_ACCESS_TOKEN` shipped for months in exactly that state -- passed to
the engine while the engine's auth read `API_KEYS` -- and no scanner could
catch it, because the variable itself was well-formed.

## Why `:-` with a value is the worse half

A bare literal at least looks like what it is. `${API_KEYS:-alice:changeme}`
reads as parameterised -- a reviewer skims it as "comes from the environment" --
and silently supplies the known credential to anyone who does not set it. The
failure is invisible precisely to the person most likely to be affected.

## Not a secret scanner

gitleaks and detect-secrets look for things shaped like real credentials, and
`changeme-alice` is shaped like a placeholder, which is why it was never
flagged. This asks a different question -- "can this file hand someone a working
credential?" -- and a deliberately fake-looking value answers yes just as well
as a realistic one.
"""

from __future__ import annotations

import argparse
import re
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Compose files anywhere in the tree. Recursive on purpose: a hand-written
#: list of directory shapes missed `packages/maistro-canvas/frontend/
#: docker-compose.yml`, which carries a committed `POSTGRES_PASSWORD`
#: fallback, while the gate reported a clean scan of six files. A gate that
#: answers "ok" about a set it chose too narrowly is worse than no gate,
#: because the "ok" is what people read.
COMPOSE_GLOBS = (
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
    "**/*.compose.yml",
    "**/*.compose.yaml",
    "**/compose.yml",
    "**/compose.yaml",
)

EXCLUDED_PARTS = ("node_modules", ".venv", "third_party", ".git")

#: Segments that make a name a credential. Matched against the `_`-delimited
#: parts of the name, not as a substring: `TOKEN` as a substring also matches
#: `MAX_TOKENS` and `TOKENIZERS_PARALLELISM`, which are ordinary model settings.
#: A gate that fails CI on `MAX_TOKENS=4096` with "replace this with a secret
#: substitution" teaches people to work around it.
SECRET_SEGMENTS = frozenset(
    {
        "PASSWORD",
        "PASSWORDS",
        "PASSPHRASE",
        "SECRET",
        "SECRETS",
        "TOKEN",
        "KEY",
        "KEYS",
        "CREDENTIAL",
        "CREDENTIALS",
    }
)

#: Names whose *value* can carry a credential even though the name does not:
#: `DATABASE_URL=postgresql://user:pw@host` hands out a password, and no marker
#: appears anywhere in `DATABASE_URL`.
URL_SUFFIXES = ("_URL", "_URI", "_DSN")

#: YAML's null spellings. `API_KEY: null` removes a variable rather than
#: supplying one, which is the opposite of committing a credential.
YAML_NULLS = frozenset({"null", "Null", "NULL", "~"})

#: `NAME=value`, in either the list form (`- NAME=value`) or the mapping form.
#: The list form's optional quote is part of the pattern: Compose accepts
#: `- "API_KEYS=hunter2"` as a YAML scalar, and a pattern that required the
#: name immediately after the dash skipped that spelling silently -- a way
#: to commit a credential past this gate.
#: (`NAME: value`). Leading `#` is handled by the caller: a commented line is
#: documentation, and `.env.example`-style guidance is not a deployment.
_LIST_FORM = re.compile(r"^\s*-\s*[\"']?([A-Z][A-Z0-9_]*)=(.*)$")
_MAP_FORM = re.compile(r"^\s*([A-Z][A-Z0-9_]*):\s+(\S.*)$")

#: `${VAR:?msg}` — required, refuses to start when unset. Always allowed.
_REQUIRED = re.compile(r"^\$\{[A-Z0-9_]+:\?[^}]*\}$")
#: `${VAR:-}` or `${VAR-}` — optional and empty. Allowed.
_EMPTY_DEFAULT = re.compile(r"^\$\{[A-Z0-9_]+:?-\s*\}$")
#: `${VAR}` — plain substitution, no default. Allowed: unset becomes empty.
_PLAIN = re.compile(r"^\$\{?[A-Z0-9_]+\}?$")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    name: str
    value: str
    why: str


def is_secret_name(name: str) -> bool:
    """Whether `name` denotes a credential, by whole `_`-delimited segment."""
    return bool(SECRET_SEGMENTS & set(name.upper().split("_")))


def is_url_name(name: str) -> bool:
    """Whether `name`'s value may embed a credential in its userinfo."""
    return name.upper().endswith(URL_SUFFIXES)


def _userinfo_password(value: str) -> str:
    """The literal password inside a connection URL, or "" if there is none.

    The userinfo run is greedy up to the last `@` before the path, and it
    admits both spaces and `?`. Both matter, and for the same reason:
    `postgresql://u:${DB_PASSWORD:?Set DB_PASSWORD in .env}@host` is the
    spelling this gate asks for, and it contains one of each. Excluding either
    made that URL parse as having no userinfo at all -- the right verdict
    reached without ever looking at the password, which is also how a literal
    password containing a space or a `?` got past.

    Stopping at `/` and `#` is what keeps this from reading a query string as
    userinfo: `http://host/p?a=b@c` cannot match, because the run cannot cross
    the path separator to reach that `@`.
    """
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/#]*)@", value)
    if not match:
        return ""
    userinfo = match.group(1)
    if ":" not in userinfo:
        return ""
    password = userinfo.split(":", 1)[1]
    # `postgresql://maistro:${DB_PASSWORD:?...}@host` is parameterised, which is
    # what the base profile does and what this gate wants people to do.
    if password.startswith("$"):
        return ""
    return password


_LITERAL = (
    "is a literal value committed to the repository — use ${VAR:?message} "
    "so the deployment refuses to start without one"
)
_FALLBACK = (
    "falls back to a non-empty default, so a caller who sets nothing "
    "still gets this value — use ${VAR:?message} so it refuses to start"
)


def _defaults_only_to_references(value: str) -> bool:
    """Whether every fallback in a `${A:-${B:-...}}` chain is another reference.

    Walks the chain and accepts it only if it ends in a required, plain or
    empty reference. Any literal anywhere -- `${A:-${B:-hunter2}}` -- is still
    a committed default, so this returns False and the caller flags it.
    """
    for _ in range(8):
        match = re.fullmatch(r"\$\{[A-Z0-9_]+:?-(.+)\}", value)
        if match is None:
            return False
        fallback = match.group(1).strip()
        if _REQUIRED.match(fallback) or _PLAIN.match(fallback) or _EMPTY_DEFAULT.match(fallback):
            return True
        value = fallback
    return False


def classify(value: str, *, name: str = "") -> str:
    """Return why `value` is unacceptable, or "" when it is fine."""
    stripped = value.strip().strip('"').strip("'")
    if not stripped or stripped in YAML_NULLS:
        # A YAML null removes a variable rather than supplying one, which is the
        # opposite of committing a credential. Rejecting it would block a valid
        # way to clear a secret an image otherwise provides.
        return ""
    if name and is_url_name(name):
        # The name carries no marker, so nothing above would have looked at this
        # value -- but `postgresql://user:pw@host` hands out a password all the
        # same.
        return (
            _LITERAL + " (the password is embedded in this connection URL's userinfo)"
            if _userinfo_password(stripped)
            else ""
        )
    if _REQUIRED.match(stripped) or _EMPTY_DEFAULT.match(stripped) or _PLAIN.match(stripped):
        return ""
    if _defaults_only_to_references(stripped):
        # `${LITELLM_API_KEY:-${LITELLM_MASTER_KEY:?msg}}`: a caller who sets
        # nothing gets a *refusal*, not a value, because the fallback is itself
        # a required reference. The reason this rule exists -- "a caller who
        # sets nothing still gets this value" -- does not hold, so flagging it
        # would push a correct layered default towards a worse spelling.
        return ""
    if re.match(r"^\$\{[A-Z0-9_]+:?-.+\}$", stripped):
        return _FALLBACK
    if stripped.startswith("$$"):
        # Compose reads `$$` as an escaped dollar, not a substitution: `$$hunter2`
        # reaches the container as the literal `$hunter2`. The production profile
        # relies on that for `$$REDIS_PASSWORD` inside a shell command, so the
        # spelling is legitimate -- which is exactly why accepting every value
        # starting with `$` let a committed credential through.
        return _LITERAL
    if stripped.startswith("$"):
        # Some other substitution form. Not a literal, so not a committed
        # credential; left alone rather than guessed at.
        return ""
    return _LITERAL


def compose_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    seen: set[Path] = set()
    for pattern in COMPOSE_GLOBS:
        for path in repo_root.glob(pattern):
            if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts):
                seen.add(path)
    return sorted(seen)


def scan_text(text: str, *, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        match = _LIST_FORM.match(line) or _MAP_FORM.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        # An inline comment is not part of the value.
        value = value.split(" #", 1)[0].strip()
        if not is_secret_name(name) and not is_url_name(name):
            continue
        why = classify(value, name=name)
        if why:
            findings.append(Finding(path=path, line_no=line_no, name=name, value=value, why=why))
    return findings


def scan(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in compose_files(repo_root):
        findings.extend(
            scan_text(path.read_text(encoding="utf-8"), path=str(path.relative_to(repo_root)))
        )
    findings.extend(unused_secret_findings(repo_root))
    return findings


#: `${VAR` -- an interpolation reference, in any value position. `$$VAR` (an
#: escaped dollar) does not match, and deliberately so: Compose hands the
#: literal to the container's shell, which is not a consumer of the .env name.
_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")

#: Names whose reader is another image, not this repository's code. Each entry
#: is a reviewed decision with its consumer named: adding one claims "some
#: process outside this tree reads this secret", and a reviewer should be able
#: to check that claim against the compose file that passes it.
_THIRD_PARTY_CONSUMERS: dict[str, str] = {
    "POSTGRES_PASSWORD": "the official postgres image",
    "REPLICATION_PASSWORD": "postgres streaming replication (deploy/init-replication.sh)",
    "REDIS_PASSWORD": "the official redis image",
    "LANGFUSE_PUBLIC_KEY": "the langfuse server image",
    "LANGFUSE_SECRET_KEY": "the langfuse server image",
    "LANGFUSE_NEXTAUTH_SECRET": "the langfuse server image",
    "NEXTAUTH_SECRET": "the langfuse server image",
    "CEREBRAS_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "COHERE_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "DEEPINFRA_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "DEEPSEEK_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "FIREWORKS_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "NVIDIA_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "SAMBANOVA_API_KEY": "the LiteLLM gateway, by provider-convention env name",
    "TOGETHER_API_KEY": "the LiteLLM gateway, by provider-convention env name",
}

_UNUSED_WHY = (
    "has no production reader: no code under packages/ consumes it and it is "
    "not a documented third-party consumer -- a secret-named variable nothing "
    "reads only creates false confidence; wire it up or remove it (#402)"
)


def _consumer_roots(repo_root: Path) -> tuple[Path, ...]:
    """Where a production reader of an env var may live.

    `packages/*/src` is the library and server code. Hive-conductor is a
    reference app whose backend is not under `src/`, and it is the production
    reader of `MAISTRO_ROUTER_API_KEY`, so its backend joins explicitly.
    `litellm_config.yaml` names provider keys (`os.environ/GEMINI_API_KEY`),
    making the tracked gateway config itself a consumer surface.
    """
    roots: list[Path] = [repo_root / "litellm_config.yaml"]
    packages = repo_root / "packages"
    if packages.is_dir():
        for package in sorted(packages.iterdir()):
            src = package / "src"
            if src.is_dir():
                roots.append(src)
    backend = packages / "hive-conductor" / "backend"
    if backend.is_dir():
        roots.append(backend)
    return tuple(roots)


def _is_test_path(path: Path) -> bool:
    """A test asserting a var name is not a production consumer of it."""
    return "tests" in path.parts or path.name.startswith("test_")


def production_consumer_corpus(repo_root: Path) -> str:
    """Every production source that can name an env var, lowercased once.

    Lowercased because the consumer of `MAISTRO_ROUTER_API_KEY` is often the
    pydantic field `maistro_router_api_key`, not a literal string.
    """
    chunks: list[str] = []
    for root in _consumer_roots(repo_root):
        if root.is_file():
            with suppress(OSError, UnicodeDecodeError):
                chunks.append(root.read_text(errors="replace"))
            continue
        for path in sorted(root.rglob("*.py")):
            if _is_test_path(path):
                continue
            with suppress(OSError, UnicodeDecodeError):
                chunks.append(path.read_text(errors="replace"))
    return "\n".join(chunks).lower()


def secret_named_references(text: str) -> dict[str, int]:
    """Secret-shaped names a Compose file uses, with each one's first line.

    Both shapes count: interpolation sources (`${VAR:?...}` -- what the .env
    must supply) and assignment names (`- VAR=...` -- what the container will
    read). The second is what makes the conductor's `MAISTRO_ROUTER_API_KEY`
    checkable: its reader is the container process, not another `${...}`.
    """
    found: dict[str, int] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for name in _REF.findall(line):
            if is_secret_name(name):
                found.setdefault(name, line_no)
        match = _LIST_FORM.match(line) or _MAP_FORM.match(line)
        if match and is_secret_name(match.group(1)):
            found.setdefault(match.group(1), line_no)
    return found


def unused_secret_findings(repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Secret-named Compose variables with no consumer anywhere (#402).

    A name passes if production code names it, the tracked LiteLLM config
    names it, or it is on the reviewed third-party list. Anything else is
    reported: the variable still *works* -- it just enforces nothing, which
    is the state #402 removed `MAISTRO_ACCESS_TOKEN` from.
    """
    corpus = production_consumer_corpus(repo_root)
    findings: list[Finding] = []
    for path in compose_files(repo_root):
        rel = str(path.relative_to(repo_root))
        for name, line_no in secret_named_references(path.read_text(encoding="utf-8")).items():
            if name in _THIRD_PARTY_CONSUMERS:
                continue
            if name.lower() in corpus:
                continue
            findings.append(
                Finding(path=rel, line_no=line_no, name=name, value="", why=_UNUSED_WHY)
            )
    return findings


def render(findings: list[Finding], scanned: int) -> str:
    if not findings:
        return f"ok: {scanned} tracked Compose file(s) hand out no credential"
    lines = [f"FAIL: {len(findings)} secret finding(s) in a deployment profile", ""]
    for finding in findings:
        lines.append(f"  {finding.path}:{finding.line_no}")
        # The name and the reason, never the value: printing it into a CI log
        # is the same exposure one more time.
        lines.append(f"    {finding.name} {finding.why}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    findings = scan(args.root)
    print(render(findings, len(compose_files(args.root))))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
