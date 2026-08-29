#!/usr/bin/env python3
"""A credential field may not be named by its placeholder (#375).

Every password and API-key field in the Conductor's front end took its
accessible name from placeholder text. A placeholder is not a name. It
disappears the moment there is a value -- so a screen-reader user who tabs back
to a half-filled form is told nothing -- and it can change with state: the LLM
key field read `API key` or `key stored -- replace?` depending on the server's
answer, so the field's *name* changed under the user. The setup wizard had two
fields whose entire name was `password`, one for the admin account and one for
the daily user, indistinguishable to anything that could not see the layout.

Two rules, both about the same thing from different sides:

1. **No raw `type="password"` outside the shared components.** Secret fields go
   through `SecretField`, which supplies a real `<label htmlFor>`, associates
   the hint, error and saved-secret state through `aria-describedby`, and
   carries the show/hide control. A raw one is how the defect comes back.
2. **On the credential and authentication surfaces, no control is named only by
   its placeholder.** A raw `<input>` there must carry an `id` (paired with a
   `<label htmlFor>`), an `aria-label`, or an `aria-labelledby`. This catches
   the non-secret half -- the username beside the password is just as unnamed,
   and just as useless to announce.

Neither is a substitute for the browser check in
`tests/e2e/credential-labels.spec.ts`, which asks a real accessibility tree
what each field is actually called. This is the cheap ratchet that also reaches
the surfaces that check cannot get to: the ones behind authentication and
behind server state.

Run: python scripts/check-secret-field-labels.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "packages" / "hive-conductor" / "frontend" / "src"

#: Where `SecretField` and `TextField` themselves live. The one file allowed to
#: render a password input, because it is what makes the others unnecessary.
SHARED = FRONTEND / "components" / "shared.tsx"

#: The surfaces this issue is about: anywhere a user types a credential.
CREDENTIAL_SURFACES = (
    "pages/Login.tsx",
    "pages/Setup.tsx",
    "pages/Settings.tsx",
    "pages/Credentials.tsx",
    "components/LlmProviders.tsx",
)

_PASSWORD_INPUT = re.compile(r'type\s*=\s*"password"')

_INPUT_START = re.compile(r"<input\b")


def _blank(out: list[str], text: str, start: int, opener: str, closer: str) -> int:
    """Blank one comment in place and return the index just past it."""
    end = text.find(closer, start + len(opener))
    end = len(text) if end < 0 else end + (len(closer) if closer != "\n" else 0)
    for position in range(start, end):
        if out[position] != "\n":
            out[position] = " "
    return end


def _without_comments(text: str) -> str:
    """`text` with comment bodies blanked, offsets and line breaks preserved.

    A `{/* ... <input> ... */}` note about this very rule is enough to fail it
    otherwise -- which happened on the first run, on a comment explaining the
    fix. Blanking rather than deleting keeps every reported line number honest.
    """
    out = list(text)
    index = 0
    quote = ""
    while index < len(text):
        char = text[index]
        if quote:
            index += 2 if char == "\\" else 1
            if char == quote:
                quote = ""
            continue
        if char in "\"'`":
            quote = char
        elif text.startswith("/*", index):
            index = _blank(out, text, index, "/*", "*/")
            continue
        elif text.startswith("//", index):
            index = _blank(out, text, index, "//", "\n")
            continue
        index += 1
    return "".join(out)


def _tag_attributes(text: str, start: int) -> str:
    """The attribute text of the `<input` tag beginning at `start`.

    Scanned rather than matched. A regex ending at the first `>` stops inside
    `onChange={(e) => ...}` -- and since the naming attribute usually comes
    *after* the handler, that reads a named field as unnamed and an unnamed one
    as named, depending only on attribute order. Measured: it reported five
    findings on this repo, of which two were correctly-labelled controls.
    """
    depth = 0
    quote = ""
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0:
            return text[start:index]
        index += 1
    return text[start:]


_NAMED = ("aria-label", "aria-labelledby", "id=", "id ")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # pragma: no cover - only when scanning outside the repo
        return str(path)


def raw_password_inputs(root: Path, shared: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.tsx")):
        if path == shared:
            continue
        text = _without_comments(path.read_text(encoding="utf-8"))
        for match in _PASSWORD_INPUT.finditer(text):
            findings.append(
                Finding(
                    _display(path),
                    _line_of(text, match.start()),
                    'renders a raw `type="password"` input; use `SecretField` from '
                    "components/shared, which carries the label, the description and "
                    "the show/hide control",
                )
            )
    return findings


def placeholder_named_inputs(root: Path, surfaces: tuple[str, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for relative in surfaces:
        path = root / relative
        if not path.is_file():
            findings.append(Finding(relative, 0, "listed as a credential surface but missing"))
            continue
        text = _without_comments(path.read_text(encoding="utf-8"))
        for match in _INPUT_START.finditer(text):
            attrs = _tag_attributes(text, match.end())
            if any(marker in attrs for marker in _NAMED):
                continue
            findings.append(
                Finding(
                    _display(path),
                    _line_of(text, match.start()),
                    "renders an <input> with no `id`, `aria-label` or `aria-labelledby`, "
                    "so a placeholder is the only name it can have",
                )
            )
    return findings


def audit(root: Path = FRONTEND, shared: Path = SHARED) -> list[Finding]:
    return [
        *raw_password_inputs(root, shared),
        *placeholder_named_inputs(root, CREDENTIAL_SURFACES),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    if not FRONTEND.is_dir():
        print(f"FAIL: {_display(FRONTEND)} is missing", file=sys.stderr)
        return 1

    findings = audit()
    if findings:
        print(f"FAIL: {len(findings)} credential field(s) rely on a placeholder for a name\n")
        for finding in findings:
            print(f"  {finding.render()}")
        print(
            "\nA placeholder disappears as soon as the field has a value, and it can change "
            "with state (#375). Give the field a persistent associated label."
        )
        return 1

    print(
        "OK: no raw password input outside components/shared.tsx, and every input on the "
        f"{len(CREDENTIAL_SURFACES)} credential surfaces can carry an associated label"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
