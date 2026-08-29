#!/usr/bin/env python3
"""Gate: no secret reaches an image build context, whichever builder runs (#308).

The defect
----------
`Dockerfile.rsi-runner` copies the repository root into an image that then
executes agent-authored code. There was no root `.dockerignore`, and the
`Dockerfile.rsi-runner.dockerignore` beside it did not mention `.env` at all —
so the database password, the LiteLLM gateway key and every provider key in
that file were one `docker build` away from an image a candidate runs inside.

The subtler half is which file applies. `<dockerfile>.dockerignore` is read by
**BuildKit only**; the classic builder ignores it and falls back to the root
`.dockerignore`. Two files that disagree mean the protection depends on
`DOCKER_BUILDKIT`, the daemon version, or whatever tool shelled out to
`docker build` — none of which is a property anyone can check by reading the
Dockerfile.

So this gate asserts five things:

1. Both ignore files exist and carry the **same rules in the same order**.
   Comments may differ; rules may not. Order is part of the meaning — Docker
   resolves a path by the last rule that matches it.
2. Those rules deny every pattern in `MUST_DENY` — the secret set. A rule that
   is merely present is not enough: it has to be there in both files, because
   either one may be the one that runs.
3. Every exception (`!rule`) is one that was written down, with its reason, in
   `EXPECTED_NEGATIONS`. An exception is the only construct that can undo a
   denial, so an unrecognised one fails rather than being trusted.
4. The **finished** rule set, evaluated in order, excludes every path in
   `SECRET_PROBES` and keeps every path in `KEPT_PROBES`. This is the question
   (2) cannot answer: an exception added below the secret rules re-includes
   what they denied without changing whether the denial is written (#510).
5. No rule denies a **tracked** path. `**/data/` is the natural rule to reach
   for and it would silently strip `packages/hive-conductor/backend/data/` and
   the BFCL benchmark corpus out of every image. A build context missing source
   files fails late, confusingly, and in the image rather than here.

Usage
-----
    python3 scripts/check-build-context.py
"""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_IGNORE = ROOT / ".dockerignore"
RUNNER_IGNORE = ROOT / "Dockerfile.rsi-runner.dockerignore"

#: Dockerfiles whose image ends up executing agent-authored code. A bare
#: `COPY . ` in one of these is the defect this gate is named for: it makes
#: the image's contents a claim about everything that exists rather than
#: about what the build needs.
CANDIDATE_IMAGES: tuple[str, ...] = ("Dockerfile.rsi-runner",)

#: Every one of these must be denied, in BOTH files. Each is something whose
#: presence in an image an operator would consider an incident, not a bug.
MUST_DENY: tuple[tuple[str, str], ...] = (
    (".env", "the database password, gateway key and every provider key"),
    ("**/.env", "the same file anywhere under the context"),
    (".env.*", "the same file under any suffix an operator gave it"),
    ("**/.env.*", "the same, anywhere under the context"),
    ("gateway.env", "the LiteLLM gateway key under its own filename"),
    ("**/gateway.env", "the same, anywhere under the context"),
    ("/.git", "every secret ever committed and later removed"),
    ("*.pem", "private keys"),
    ("**/*.pem", "private keys anywhere under the context"),
    ("*.p12", "PKCS#12 client certificates and their keys"),
    ("**/*.p12", "the same, anywhere under the context"),
    ("*.pfx", "PKCS#12 under its other name"),
    ("**/*.pfx", "the same, anywhere under the context"),
    ("id_rsa*", "ssh private keys"),
    ("**/id_rsa*", "ssh private keys anywhere under the context"),
    ("id_ed25519*", "ssh private keys"),
    ("**/id_ed25519*", "ssh private keys anywhere under the context"),
    ("*.age", "age-encrypted vault material (SPEC-011)"),
    ("**/*.age", "the same, anywhere under the context"),
    (".age-key*", "the age identity that decrypts the vault"),
    ("**/.age-key*", "the same, anywhere under the context"),
    ("recovery-phrase*", "the vault recovery phrase (#360)"),
    ("**/recovery-phrase*", "the same, anywhere under the context"),
    ("/secrets/", "anything an operator put somewhere named for what it is"),
    ("**/secrets/", "the same, anywhere under the context"),
    ("/.venv", "host-specific, and tooling caches credentials in it"),
    ("/rsi-reports/", "previous candidates' exported patches and scorecards"),
)

#: Every negation the files are allowed to carry, and why. A negation is the
#: one construct that can UNDO a denial, so the set is closed: an unrecognised
#: `!rule` fails the gate rather than being read and trusted (Codex, #510).
EXPECTED_NEGATIONS: dict[str, str] = {
    "!.env.example": (
        "documentation with no value in it; a gate demanding its denial would "
        "be demanding the docs be removed"
    ),
    "!**/.env.example": "the same file wherever a package keeps its own",
    "!packages/hive-conductor/frontend/dist": (
        "the backend image's Dockerfile copies this generated bundle, and this "
        "root file governs that build too"
    ),
    "!packages/hive-conductor/frontend/dist/**": "the bundle's contents, not just the directory",
}

#: Paths that must end up EXCLUDED after the whole ordered rule set is applied,
#: not merely mentioned by some rule in it.
#:
#: The difference is the finding: `MUST_DENY` asks whether a denial is written,
#: and a negation added below it can undo every one without changing that
#: answer. Docker resolves a path by the LAST rule that matches, so the only
#: honest question is what the file says about a path once it has finished
#: talking. Each probe is a real shape an operator's tree takes -- at the root
#: and again under `packages/`, because the runner copies that whole tree.
SECRET_PROBES: tuple[tuple[str, str], ...] = (
    (".env", "the operator's own environment file"),
    ("packages/provider/.env", "a package-local environment file"),
    ("packages/hive-conductor/frontend/dist/.env", "one under a re-included build output"),
    (".env.local", "an environment file by its other name"),
    ("packages/provider/.env.local", "the same, under a package"),
    ("gateway.env", "the LiteLLM gateway key"),
    ("packages/provider/gateway.env", "the same, under a package"),
    ("server.pem", "a private key at the root"),
    ("packages/provider/client.pem", "a private key under a package"),
    ("client.p12", "a PKCS#12 bundle at the root"),
    ("packages/provider/client.p12", "a PKCS#12 bundle under a package"),
    ("client.pfx", "PKCS#12 under its other name"),
    ("packages/provider/client.pfx", "the same, under a package"),
    ("id_rsa", "an ssh key at the root"),
    ("packages/provider/id_rsa", "an ssh key under a package"),
    ("id_ed25519", "an ssh key at the root"),
    ("packages/provider/id_ed25519", "an ssh key under a package"),
    ("vault/master.age", "age-encrypted vault material"),
    ("packages/provider/backup.age", "the same, under a package"),
    (".age-key.txt", "the identity that decrypts all of it"),
    ("packages/provider/.age-key.txt", "the same, under a package"),
    ("recovery-phrase.txt", "the vault recovery phrase (#360)"),
    ("packages/provider/recovery-phrase.txt", "the same, under a package"),
    ("secrets/token", "a directory named for what is in it"),
    ("packages/provider/secrets/token", "the same, under a package"),
    (".git/config", "the history, which holds every secret ever removed"),
    (".venv/lib/python3.12/site-packages/keyring.json", "credentials cached by tooling"),
    ("rsi-reports/cycle-3/export.patch", "a previous candidate's exported patch"),
)

#: Paths that must survive the same evaluation. The exceptions exist for a
#: reason and a gate that only checked denials could be satisfied by denying
#: everything.
KEPT_PROBES: tuple[tuple[str, str], ...] = (
    (".env.example", "documentation the image is supposed to carry"),
    ("packages/maistro-core/.env.example", "the same, under a package"),
    (
        "packages/hive-conductor/frontend/dist/index.js",
        "the generated bundle the backend image copies",
    ),
)


def rules(text: str) -> list[str]:
    """The ignore file's rules: every non-comment, non-blank line."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _tracked_paths() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return [line for line in listed.stdout.splitlines() if line]


def _segment_regex(segment: str) -> str:
    """One path segment of a Docker ignore pattern, as a regex.

    `*` and `?` stop at a separator here, which is the entire point: `fnmatch`
    lets `*` cross `/`, so `*.p12` appeared to deny
    `packages/provider/client.p12` when Docker denies only `client.p12`. The
    approximation was documented as biased toward false failures; it was in
    fact hiding the root-relative-pattern defect from the gate that was
    supposed to find it (Codex, #510).
    """
    out: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            close = segment.find("]", index + 1)
            if close == -1:
                out.append(re.escape(char))
            else:
                out.append(segment[index : close + 1])
                index = close
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


@cache
def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """A Docker ignore pattern as an anchored regex over a whole path.

    `**` spans path segments; everything else is confined to one. The trailing
    group is Docker's directory rule: excluding `secrets` excludes everything
    under it, which is why a rule naming a directory needs no `/**`.
    """
    parts: list[str] = []
    segments = pattern.split("/")
    for position, segment in enumerate(segments):
        if segment == "**":
            parts.append(".*" if position == len(segments) - 1 else "(?:[^/]+/)*")
        else:
            parts.append(_segment_regex(segment) + ("/" if position < len(segments) - 1 else ""))
    return re.compile("".join(parts) + "(?:/.*)?$")


def denies(rule: str, path: str) -> bool:
    """Whether `rule` excludes `path`, as Docker's matcher would.

    Docker matches relative to the context root, so a bare `vault/` denies the
    top-level directory only — unlike gitignore, where it denies one at any
    depth. The rules are written with a leading `/` where top-level is what is
    meant, so both readings agree and nobody has to know which applies.
    """
    pattern = rule.lstrip("/").rstrip("/")
    return bool(_pattern_regex(pattern).match(path))


def _effective_rule(ruleset: list[str], path: str) -> str | None:
    """The rule Docker would resolve `path` by: the LAST one that matches it.

    This is the whole difference between "a denial is written" and "the path is
    denied". A negation below a denial wins, so any question about what reaches
    the image has to be asked of the finished file rather than of its lines.
    """
    last: str | None = None
    for rule in ruleset:
        if denies(rule.lstrip("!"), path):
            last = rule
    return last


def _is_denied(ruleset: list[str], path: str) -> bool:
    """Whether `path` is excluded once the whole ordered rule set is applied."""
    rule = _effective_rule(ruleset, path)
    return rule is not None and not rule.startswith("!")


def _unexpected_negations(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """A negation nobody wrote down is the one construct that undoes a denial."""
    failures: list[str] = []
    for name, ruleset in ((ROOT_IGNORE.name, root_rules), (RUNNER_IGNORE.name, runner_rules)):
        for rule in ruleset:
            if rule.startswith("!") and rule not in EXPECTED_NEGATIONS:
                failures.append(
                    f"  {name} carries the unrecognised exception {rule!r} — an exception "
                    f"re-includes what a denial above it excluded, so each one is listed "
                    f"in EXPECTED_NEGATIONS with the reason it exists"
                )
    return failures


def _probes_resolve_correctly(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """Evaluate the ordered rule set, rather than reading it for keywords."""
    failures: list[str] = []
    for name, ruleset in ((ROOT_IGNORE.name, root_rules), (RUNNER_IGNORE.name, runner_rules)):
        for path, what in SECRET_PROBES:
            if not _is_denied(ruleset, path):
                landed = _effective_rule(ruleset, path)
                because = (
                    f"the last rule matching it is {landed!r}" if landed else "no rule matches it"
                )
                failures.append(f"  {name} would let {path!r} into the context — {what}; {because}")
        for path, what in KEPT_PROBES:
            if _is_denied(ruleset, path):
                landed = _effective_rule(ruleset, path)
                failures.append(
                    f"  {name} excludes {path!r}, which the build needs — {what}; "
                    f"the last rule matching it is {landed!r}"
                )
    return failures


def _divergence(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """The two files must carry the same rules; comments may differ."""
    if root_rules == runner_rules:
        return []
    only_root = [r for r in root_rules if r not in runner_rules]
    only_runner = [r for r in runner_rules if r not in root_rules]
    return [
        f"  {ROOT_IGNORE.name} and {RUNNER_IGNORE.name} carry different rules — "
        f"BuildKit reads one and the classic builder the other, so the protection "
        f"would depend on which ran.\n"
        f"      only in {ROOT_IGNORE.name}: {only_root or '(none)'}\n"
        f"      only in {RUNNER_IGNORE.name}: {only_runner or '(none)'}"
    ]


def _missing_denials(root_rules: list[str], runner_rules: list[str]) -> list[str]:
    """Every secret pattern, in BOTH files: either one may be the one that runs."""
    failures: list[str] = []
    for pattern, why in MUST_DENY:
        for name, ruleset in ((ROOT_IGNORE.name, root_rules), (RUNNER_IGNORE.name, runner_rules)):
            if pattern not in ruleset:
                failures.append(f"  {name} does not deny {pattern!r} — {why}")
    for negation, why in sorted(EXPECTED_NEGATIONS.items()):
        if negation not in root_rules:
            failures.append(f"  {ROOT_IGNORE.name} lost {negation!r}; {why}")
    return failures


def _over_broad(root_rules: list[str]) -> list[str]:
    """A rule that denies a tracked file empties the image of source."""
    failures: list[str] = []
    for path in _tracked_paths():
        if not _is_denied(root_rules, path):
            continue
        failures.append(
            f"  rule {_effective_rule(root_rules, path)!r} denies the TRACKED file "
            f"{path!r} — a build context missing source fails late and inside the image"
        )
    return failures


def _dockerfiles() -> list[str]:
    """Every tracked Dockerfile, whatever it is named."""
    out: list[str] = []
    for path in _tracked_paths():
        name = Path(path).name
        if name.endswith(".dockerignore"):
            continue
        if name == "Dockerfile" or name.startswith("Dockerfile."):
            out.append(path)
    return out


def _copy_sources(dockerfile: Path) -> list[tuple[int, str]]:
    """Context paths a Dockerfile copies, with the line each is on.

    `--from=` copies take from an earlier stage or another image rather than
    from the build context, so they are not this file's business.
    """
    found: list[tuple[int, str]] = []
    for number, raw in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.upper().startswith("COPY ") or "--from=" in line:
            continue
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        for source in tokens[:-1]:
            if source in {".", "./"} or "*" in source:
                continue
            found.append((number, source))
    return found


def _denied_copy_sources(root_rules: list[str]) -> list[str]:
    """A rule here can break a build over there (#510).

    This file governs every `docker build` rooted at the repository, not only
    the RSI runner's. `**/dist` was written for build output and silently took
    `packages/hive-conductor/frontend/dist/` out of the backend image's
    context, where its Dockerfile copies it — a failure that surfaces inside a
    build log, after the base image and the dependency layers are already
    built, rather than here in a second.

    Existence is `_missing_copy_sources`' question; this one is only about
    whether the ignore rules would remove it.
    """
    failures: list[str] = []
    for name in _dockerfiles():
        for number, source in _copy_sources(ROOT / name):
            probe = source.rstrip("/")
            if _is_denied(root_rules, probe):
                failures.append(
                    f"  {name}:{number} copies {source!r} from the context, and "
                    f"{_effective_rule(root_rules, probe)!r} excludes it — the build "
                    f"would fail at that COPY"
                )
    return failures


def _bare_copy(dockerfile: Path) -> list[str]:
    """`COPY . ` into an image that runs candidate code."""
    failures: list[str] = []
    for number, raw in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.upper().startswith("COPY "):
            continue
        sources = [t for t in line.split()[1:] if not t.startswith("--")]
        if len(sources) >= 2 and sources[0] in {".", "./"}:
            failures.append(
                f"  {dockerfile.name}:{number}: `{line}` copies the whole context into an "
                f"image that runs agent-authored code — name what the build needs instead, "
                f"so a new top-level directory has to be added deliberately"
            )
    return failures


def _missing_copy_sources(dockerfile: Path) -> list[str]:
    """A COPY naming something that is not there fails the build late.

    Late meaning: after the base image is pulled and the apt layer is built, in
    CI, with the reason buried in a build log — rather than here, in a second.
    """
    failures: list[str] = []
    for number, raw in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.upper().startswith("COPY ") or "--from=" in line:
            continue
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        for source in tokens[:-1]:
            if source in {".", "./"} or "*" in source:
                continue
            if not (ROOT / source).exists():
                failures.append(
                    f"  {dockerfile.name}:{number}: COPY source {source!r} does not exist"
                )
    return failures


def audit() -> list[str]:
    """One message per divergence, missing denial, or over-broad rule."""
    missing = [
        f"  {p.name} does not exist" for p in (ROOT_IGNORE, RUNNER_IGNORE) if not p.is_file()
    ]
    if missing:
        return missing

    root_rules = rules(ROOT_IGNORE.read_text(encoding="utf-8"))
    runner_rules = rules(RUNNER_IGNORE.read_text(encoding="utf-8"))

    failures = (
        _divergence(root_rules, runner_rules)
        + _missing_denials(root_rules, runner_rules)
        + _unexpected_negations(root_rules, runner_rules)
        + _probes_resolve_correctly(root_rules, runner_rules)
        + _over_broad(root_rules)
        + _denied_copy_sources(root_rules)
    )
    for name in CANDIDATE_IMAGES:
        dockerfile = ROOT / name
        if not dockerfile.is_file():
            failures.append(f"  {name} does not exist")
            continue
        failures += _bare_copy(dockerfile) + _missing_copy_sources(dockerfile)
    return failures


def main() -> int:
    failures = audit()
    if failures:
        print(f"FAIL: {len(failures)} problem(s) with the image build context:\n")
        print("\n".join(failures))
        print(
            "\n`Dockerfile.rsi-runner` copies this context into an image that runs "
            "\nagent-authored code. `.env` reaching it is an incident, not a bug."
        )
        return 1

    print(
        f"ok: both ignore files carry the same {len(rules(ROOT_IGNORE.read_text(encoding='utf-8')))} "
        f"rule(s), deny all {len(MUST_DENY)} secret pattern(s), and exclude nothing tracked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
