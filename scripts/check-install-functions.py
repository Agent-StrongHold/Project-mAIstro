#!/usr/bin/env python3
"""Gate: every function the supported installer invokes is defined or deliberately external (#807).

The gap this closes
-------------------
``install.sh`` shipped a call to ``upsert_env`` (the real helper is
``set_env_value``) on the branch that only runs for Docker Desktop's
non-default macOS socket path. Every gate stayed green: the Linux clean-install
run never executes that branch, and shellcheck does not report calls to
undefined functions (it assumes sourced content it cannot see), so the defect
was structurally invisible until a supported macOS install died with
``upsert_env: command not found`` before any container started.

This gate closes that hole statically. For each installer entry point it:

1. collects the functions the file defines;
2. extracts every word that can reach command position — including inside
   ``$( ... )`` and ``<( ... )`` substitutions — while skipping heredoc bodies
   (they hold Python and prose, not shell) and ``case`` patterns (they are
   data, and ``Darwin)`` must not read as an invocation of ``Darwin``);
3. asserts each such word is one of: a function defined in the same file, a
   bash reserved word or builtin, or a command explicitly allowlisted below as
   intentionally external.

The allowlist is the "intentionally external" half of the contract: adding a
dependency on a new host binary is a reviewed decision (one entry, with its
justification), and a typo'd or undefined helper fails the gate on the PR that
introduces it instead of on a user's machine.

Known, deliberate limits: commands prefixed by variable assignments
(``VAR=x cmd``), backtick substitutions, and ``case`` inside a substitution
are not extracted. None of those shapes occurs in the installers, and each
would only narrow the net (a false negative), never fail a correct file.

Stdlib only, like the other ``scripts/check-*.py`` gates.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The supported installer entry points, checked by default.
DEFAULT_TARGETS = ("install.sh", "get.sh")

#: Bash reserved words: syntactic, never looked up as commands.
RESERVED_WORDS = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "in",
        "function",
        "select",
        "time",
        "coproc",
        "!",
        "{",
        "}",
    }
)

#: Bash builtins (POSIX special + regular). Kept as a fixed set rather than
#: resolved against the running bash so the gate cannot drift with the CI
#: image's shell.
BUILTINS = frozenset(
    {
        ":",
        ".",
        "source",
        "alias",
        "bg",
        "bind",
        "break",
        "builtin",
        "caller",
        "cd",
        "command",
        "compgen",
        "complete",
        "continue",
        "declare",
        "dirs",
        "disown",
        "echo",
        "enable",
        "eval",
        "exec",
        "exit",
        "export",
        "false",
        "fc",
        "fg",
        "getopts",
        "hash",
        "help",
        "history",
        "jobs",
        "kill",
        "let",
        "local",
        "logout",
        "mapfile",
        "popd",
        "printf",
        "pushd",
        "pwd",
        "read",
        "readarray",
        "readonly",
        "return",
        "set",
        "shift",
        "shopt",
        "suspend",
        "test",
        "times",
        "trap",
        "true",
        "type",
        "typeset",
        "ulimit",
        "umask",
        "unalias",
        "unset",
        "wait",
    }
)

#: Commands the installers may depend on from the host. Every entry is a
#: reviewed decision recording *why* the command is allowed to come from
#: outside this repository — so a typo'd helper cannot hide behind an
#: unexamined allowlist hit, and so dropping a real dependency shows up as a
#: failing invocation on the PR that drops it.
EXTERNAL_COMMANDS = {
    "apt": "Linux: package front end used alongside apt-get for the docker runtime",
    "apt-get": "Linux: install the Docker runtime stack when missing",
    "awk": "POSIX text tool: parse checksum manifests and command output",
    "basename": "POSIX: file names from paths",
    "brew": "macOS: install the Docker runtime stack when missing",
    "cat": "POSIX file tool: usage text and heredoc output",
    "chmod": "POSIX file tool: modes on generated files",
    "colima": "macOS container runtime option chosen by choose_macos_runtime",
    "cp": "POSIX file tool: lay down the source tree in archive installs",
    "curl": "documented dependency: release download and health probes",
    "cut": "POSIX text tool: parse command output",
    "date": "POSIX: timestamped log lines",
    "dirname": "POSIX: derive SCRIPT_DIR companions",
    "docker": "documented dependency: compose runtime",
    "docker-compose": "legacy compose v1 spelling accepted by detect_compose_cmd",
    "dockerd": "WSL2 fallback: start the daemon unsupervised when no init system has it",
    "find": "POSIX file tool: prune stale files from archive installs",
    "git": "get.sh clones/updates the source checkout; install.sh reads its tag",
    "gh": "get.sh release download fallback (GitHub CLI)",
    "grep": "POSIX text tool: inspect command output",
    "head": "POSIX text tool: inspect command output",
    "install": "POSIX file tool: place generated files",
    "lima": "legacy spelling of the colima VM manager, accepted alongside limactl",
    "limactl": "colima's backing VM manager: start/stop the Linux VM",
    "mkdir": "POSIX file tool: create install and plan directories",
    "mktemp": "POSIX: scratch files for downloads",
    "mv": "POSIX file tool: renames during install",
    "nohup": "WSL2 fallback: keep the unsupervised dockerd alive past the installer",
    "open": "macOS: open the UI in the default browser after install",
    "podman": "documented alternative compose runtime",
    "podman-compose": "documented alternative compose runtime",
    "py": "Windows launcher fallback probed by ensure_python",
    "python": "fallback spelling of python3 probed by ensure_python",
    "python3": "documented dependency (>= 3.11): scripts/secret_env.py and probes",
    "pkill": (
        "procps/BSD: the arm64 check's timeout reaps the credential helper "
        "docker spawned, which is what blocks; killing docker alone leaves it"
    ),
    "rm": "POSIX file tool: cleanup of generated files",
    "rmdir": (
        "POSIX file tool: take down an adopted unfinished install's directory. "
        "Chosen over rm -rf because it refuses a non-empty directory, so "
        "anything get.sh did not expect makes it stop instead of deleting it"
    ),
    "sed": "POSIX stream editor: rewrite generated files",
    "service": "WSL2: supervised init-system start of the Docker daemon",
    "setx": "Windows (Git Bash/MSYS): persist MAISTRO_REPO_ROOT across shells",
    "sleep": "POSIX: bounded retry loops",
    "sort": "POSIX text tool",
    "sw_vers": "macOS: OS version before choosing a runtime",
    "sudo": "documented escalation for system packages and the docker group",
    "systemctl": "Linux: supervised init-system start of the Docker daemon",
    "tail": "POSIX text tool: inspect command output",
    "tar": "POSIX archive tool: unpack downloaded releases",
    "tee": "POSIX: mirror output into log files",
    "touch": "POSIX file tool: archive-install marker",
    "tr": "POSIX text tool",
    "uname": "POSIX: detect OS and architecture",
    "uv": "documented dependency: the installer bootstraps and drives the uv toolchain",
    "wc": "POSIX text tool",
    "xargs": "POSIX: batch command construction",
}

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=[^=]?")

#: Only words that could name a shell function are asserted. Flags, paths,
#: globs, quoted strings and parameter-expansion debris fail this and are
#: ignored.
_WORD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_REDIRECTION_RE = re.compile(r"^\d*(>>?|<&|>&)\s*\S+\s*")

#: Keywords that may prefix the command word of a simple command.
_LEADING_KEYWORDS = ("if", "then", "elif", "else", "do", "time", "!", "while", "until")

#: `<<[-]WORD` heredoc openers, possibly quoted. The `<<<` herestring's first
#: `<<` is excluded: the term pattern cannot match a third `<`.
_HEREDOC_RE = re.compile(r"<<-?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

_FUNCTION_DEF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)")

#: Placeholder occupying a word position with data. When it lands at a
#: fragment's head ("${UV_CMD[@]}" tool install) the real command word was the
#: expansion — not statically checkable — and the words after it are its
#: ARGUMENTS, so the fragment must yield no candidate at all. Mid-fragment
#: placeholders are inert: only a fragment's head is ever a candidate.
DATA_PLACEHOLDER = " \x01 "

#: Everything that can end one simple command and begin another. `{`/`}` group
#: commands; the debris this creates inside `${...}` expansions is filtered by
#: _WORD_RE.
_SEPARATOR_RE = re.compile(r"[\n;|&(){}]")


def _strip_comment(line: str) -> str:
    """Drop an unquoted `#` comment. Truncating a quoted `#` can only lose a
    command word (a false negative), never invent one."""
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in (" ", "\t")):
            return line[:i]
        i += 1
    return line


def _balanced(text: str, open_idx: int) -> tuple[str, int]:
    """Return the inside of the paren group whose `(` is at ``open_idx`` and
    the index just past its close, honouring quotes."""
    depth = 0
    quote: str | None = None
    i = open_idx
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
        i += 1
    return text[open_idx + 1 :], len(text)


def _brace_balanced(text: str, open_idx: int) -> tuple[str, int]:
    """The inside of the `${` expansion whose `{` is at ``open_idx`` and the
    index just past its `}`. Braces nest (`${a:-${b}}`)."""
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
        i += 1
    return text[open_idx + 1 :], len(text)


def _skip_quoted(text: str, open_idx: int) -> int:
    """Index just past the quoted span opening at ``open_idx``."""
    quote = text[open_idx]
    i = open_idx + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quote == '"':
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return len(text)


def _ends_with_assignment(text: str) -> bool:
    """True if ``text`` ends with an `=`/`+=`/`-=` right before a paren group:
    that group is an array or compound literal (data), not a subshell."""
    return re.search(r"[+\-]?=\s*$", text) is not None


def _unquoted_paren(text: str) -> int:
    """Index of the first top-level `)` outside quotes, or -1."""
    quote: str | None = None
    depth = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == "\\" and quote == '"':
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return i
            depth -= 1
    return -1


def _logical_lines(source: str) -> list[tuple[int, str]]:
    """(first_line_number, text) with heredoc bodies removed and backslash
    continuations joined.

    Heredoc bodies are data, not shell — the installers embed whole Python
    programs in them. An unquoted terminator matches after whitespace
    stripping, which is the `<<-` contract plus a little slack.
    """
    out: list[tuple[int, str]] = []
    terminators: list[str] = []
    pending: list[str] = []
    pending_no = 0
    for no, raw in enumerate(source.splitlines(), start=1):
        if terminators:
            if raw.strip() == terminators[-1]:
                terminators.pop()
            continue
        if pending:
            pending.append(raw)
            if not raw.rstrip().endswith("\\"):
                # A backslash continuation splices the lines into one; join
                # with a space like bash does, or list items (`for key in \\\n                # OPENAI_API_KEY ...`) would re-split into command positions.
                text = " ".join(pending)
                pending = []
                out.append((pending_no, _strip_comment(text)))
            continue
        line = _strip_comment(raw)
        if line.rstrip().endswith("\\"):
            pending = [line]
            pending_no = no
            continue
        for match in _HEREDOC_RE.finditer(line):
            terminators.append(match.group(2))
        out.append((no, line))
    if pending:
        out.append((pending_no, _strip_comment("\n".join(pending))))
    return out


def _first_command_word(fragment: str) -> str | None:
    """The word bash would look up as a command if ``fragment`` began a simple
    command, or None (assignment, flag, redirection, keyword list, debris)."""
    rest = fragment.strip()
    while True:
        rest = _REDIRECTION_RE.sub("", rest, count=1).lstrip()
        tokens = rest.split()
        if not tokens:
            return None
        head = tokens[0]
        if head in _LEADING_KEYWORDS:
            rest = rest[len(head) :].lstrip()
            continue
        if head == "for" and len(tokens) >= 2 and _WORD_RE.match(tokens[1]):
            rest = rest[len(head) :].lstrip()
            rest = rest[len(tokens[1]) :].lstrip()
            continue
        # `for x in a b c` / `case w in p1|p2`: everything after `in` is data.
        if head == "in":
            return None
        break
    if _ASSIGNMENT_RE.match(head):
        return None
    if _WORD_RE.match(head):
        return head
    return None


def _scan_special(text: str, i: int) -> tuple[str, str, int] | None:
    """Classify the shell construct starting at ``text[i]``.

    Returns ``(kind, inside, after)`` — ``kind`` is ``arith`` (an arithmetic
    expansion: variables, never commands), ``subst`` (a command/process
    substitution: genuinely commands inside), ``param`` (a `${...}`
    expansion: the name is data), ``single``/``double`` (a quoted span), or
    ``paren`` (an unmatched-context paren group). ``inside`` is the span's
    content and ``after`` the index past its end. ``None`` when ``text[i]`
    begins no special construct.
    """
    ch = text[i]
    nxt = text[i + 1 : i + 2]
    if ch == "(" and nxt == "(":
        inside, after = _balanced(text, i)
        return "arith", inside, after
    if ch == "$" and nxt == "(":
        if text[i + 2 : i + 3] == "(":
            inside, after = _balanced(text, i + 1)
            return "arith", inside, after
        inside, after = _balanced(text, i + 1)
        return "subst", inside, after
    if ch in ("<", ">") and nxt == "(":
        inside, after = _balanced(text, i + 1)
        return "subst", inside, after
    if ch == "$" and nxt == "{":
        inside, after = _brace_balanced(text, i + 1)
        return "param", inside, after
    if ch in ("'", '"'):
        return "single" if ch == "'" else "double", "", _skip_quoted(text, i)
    if ch == "(":
        inside, after = _balanced(text, i)
        return "paren", inside, after
    return None


def _extract_line(text: str, words: list[tuple[str, int]], line: int) -> None:
    """Collect command-position words from one logical line.

    One quote-aware pass lifts everything that is not plain shell out of the
    text before separator splitting (see _scan_special for the constructs).
    Quoted spans, `${...}` names, arithmetic and array literals become DATA
    placeholders; command/process substitutions recurse because their contents
    genuinely hold commands.
    """
    plain: list[str] = []
    substitutions: list[str] = []
    i = 0
    while i < len(text):
        scanned = _scan_special(text, i)
        if scanned is None:
            plain.append(text[i])
            i += 1
            continue
        kind, inside, after = scanned
        if kind == "subst":
            substitutions.append(inside)
            plain.append(" ")
        elif kind == "paren":
            if _ends_with_assignment("".join(plain)):
                # Array/compound literal: data, however command-shaped.
                plain.append(DATA_PLACEHOLDER)
            else:
                substitutions.append(inside)
                plain.append(" ")
        else:
            # arith / param / single / double: data wherever they sit.
            if kind == "param":
                substitutions.extend(_substitutions_inside(inside))
            elif kind == "double":
                # Double quotes interpolate: a $(...) inside them is still a
                # command substitution ("$(docker context inspect ...)") and
                # must be checked, not dismissed as message prose.
                substitutions.extend(_substitutions_inside(text[i + 1 : after - 1]))
            plain.append(DATA_PLACEHOLDER)
        i = after
    _collect_fragment_heads("".join(plain), words, line)
    for inner in substitutions:
        _extract_line(inner, words, line)


def _collect_fragment_heads(plain: str, words: list[tuple[str, int]], line: int) -> None:
    """Record the head word of each simple command in already-lifted text."""
    for fragment in _SEPARATOR_RE.split(plain):
        word = _first_command_word(fragment)
        if word is not None:
            words.append((word, line))


def _substitutions_inside(expansion: str) -> list[str]:
    """Command substitutions embedded in a `${...}` expansion's default or
    replacement text (`${TAG:-$(fallback)}`): the name is data, an embedded
    `$(...)` is not."""
    found: list[str] = []
    i = 0
    while i < len(expansion):
        ch = expansion[i]
        nxt = expansion[i + 1 : i + 2]
        if ch == "$" and nxt == "(":
            inside, after = _balanced(expansion, i + 1)
            found.append(inside)
            i = after
            continue
        if ch in ("<", ">") and nxt == "(":
            inside, after = _balanced(expansion, i + 1)
            found.append(inside)
            i = after
            continue
        if ch in ("'", '"'):
            i = _skip_quoted(expansion, i)
            continue
        i += 1
    return found


def _pattern_to_command(line: str) -> str:
    """Inside a ``case`` block, only the text after the branch's `)` is shell.
    The pattern itself (``Darwin)``, ``unix://*)``, ``"")``) is data."""
    cut = _unquoted_paren(line)
    return line[cut + 1 :] if cut >= 0 else ""


def defined_functions(source: str) -> dict[str, int]:
    """name -> defining line number, for `name() {` definitions."""
    found: dict[str, int] = {}
    for no, line in _logical_lines(source):
        match = _FUNCTION_DEF_RE.match(line.strip())
        if match:
            found.setdefault(match.group(1), no)
    return found


def invoked_commands(source: str) -> list[tuple[str, int]]:
    """(word, line) for every word that can reach command position."""
    words: list[tuple[str, int]] = []
    case_depth = 0
    for no, line in _logical_lines(source):
        stripped = line.strip()
        head = stripped.split()[0] if stripped.split() else ""
        if head == "case":
            case_depth += 1
            continue
        if head == "esac":
            case_depth -= 1
            continue
        if case_depth > 0:
            _extract_line(_pattern_to_command(line), words, no)
        else:
            _extract_line(line, words, no)
    return words


def undefined_invocations(source: str) -> list[tuple[str, int]]:
    """Invocations that are neither defined here nor deliberately external."""
    defined = defined_functions(source)
    return [
        (word, line)
        for word, line in invoked_commands(source)
        if word not in defined
        and word not in RESERVED_WORDS
        and word not in BUILTINS
        and word not in EXTERNAL_COMMANDS
    ]


def check(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for word, line in undefined_invocations(source):
            failures.append(
                f"{path}:{line}: '{word}' is invoked but neither defined in the file, "
                "a shell builtin/reserved word, nor allowlisted as intentionally "
                "external (see EXTERNAL_COMMANDS in scripts/check-install-functions.py)"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="installer scripts to check (default: the supported entry points)",
    )
    args = parser.parse_args(argv)
    paths = args.files or [ROOT / name for name in DEFAULT_TARGETS]
    missing = [p for p in paths if not p.is_file()]
    for path in missing:
        print(f"error: {path} does not exist", file=sys.stderr)
    failures = check(paths) if not missing else [f"missing target: {p}" for p in missing]
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(
            f"\ncheck-install-functions: {len(failures)} undefined invocation(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
