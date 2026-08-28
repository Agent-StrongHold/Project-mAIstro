"""The grammar a model identifier has to satisfy before it reaches a shell (#309).

`tools/run_rsi_isolated.sh` interpolated `GENOME_MODELS` into a `bash -lc`
payload that had just sourced `/run/gateway.env`:

    python -m maistro_rsi.free_router --roster '$GENOME_MODELS' --free-count 2

A single apostrophe in a model name closes the quote, and everything after it
runs as shell in a container holding the gateway credentials. The value is not
merely operator-supplied: the free-router step *rewrites* `GENOME_MODELS` from
the output of a container that queried OpenRouter, so the string that lands in
the payload comes off the network.

The wrapper's own fix is to stop interpolating — values now cross into the
container as environment variables the inner shell expands as variables rather
than as source text. This module is the second half: a grammar, applied on the
host **before any credential is mounted**, so a malformed roster is refused
while the blast radius is still an exit code.

## The grammar

A gateway model alias is a path-ish token: provider, family, name, and an
optional tag — `openrouter/meta-llama/llama-3.1-8b-instruct:free`,
`gemini/gemini-2.5-flash`, `code`. Every character any of those needs is in
`ALLOWED_CHARACTERS`, and nothing else is admitted:

    A-Z a-z 0-9 . _ - / : +

ASCII only, deliberately. Refusing non-ASCII is not about what a model may be
called — it is that the separators an attacker reaches for when an ASCII filter
is in the way (U+2028 LINE SEPARATOR, U+00A0 NO-BREAK SPACE, U+3000 IDEOGRAPHIC
SPACE) are all non-ASCII, and an allow-list of ASCII refuses the whole family
without needing to enumerate it.

An identifier may not *begin* with `-`. It would be a well-formed token by every
rule above and would still be read by the receiving CLI as an option rather than
a value.

## The limits

`MAX_IDENTIFIER_LENGTH` and `MAX_ROSTER_SIZE` are not the grammar; they bound
what a caller can make the wrapper carry. A roster is a handful of model groups
in every real use, and the ceilings are far above that — they exist so that a
generated or hostile list cannot become an argument vector nothing downstream
sized for.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Final

#: The characters a gateway model alias is built from.
ALLOWED_CHARACTERS: Final = "A-Za-z0-9._/:+-"

#: One identifier. Anchored, so a match is the whole token rather than a
#: substring of something longer that happens to contain a legal run.
IDENTIFIER_PATTERN: Final = re.compile(rf"\A[{ALLOWED_CHARACTERS}]+\Z")

#: Longest single identifier. The longest real alias observed here is under 60
#: characters; this leaves room without leaving the door open.
MAX_IDENTIFIER_LENGTH: Final = 128

#: Most identifiers in one roster. Real rosters are 2-8 entries.
MAX_ROSTER_SIZE: Final = 32

#: Only these are trimmed from an entry's edges. `str.strip()` would also strip
#: U+00A0 and the other Unicode spaces, silently *repairing* a value engineered
#: to carry one — and a separator quietly removed is a separator not reported.
_TRIMMED: Final = " \t"


class InvalidModelIdentifier(ValueError):
    """A roster entry that must not be allowed to reach a command line."""


def validate_identifier(value: str) -> str:
    """Return `value` unchanged, or raise `InvalidModelIdentifier`."""
    if not value:
        raise InvalidModelIdentifier("empty model identifier")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise InvalidModelIdentifier(
            f"model identifier is {len(value)} characters, over the "
            f"{MAX_IDENTIFIER_LENGTH}-character limit"
        )
    if value.startswith("-"):
        raise InvalidModelIdentifier(
            f"{value!r} begins with '-', which the receiving command would read as "
            f"an option rather than a model"
        )
    if not IDENTIFIER_PATTERN.match(value):
        offending = sorted({c for c in value if not IDENTIFIER_PATTERN.match(c)})
        rendered = ", ".join(f"U+{ord(c):04X}" for c in offending)
        raise InvalidModelIdentifier(
            f"{value!r} contains characters outside [{ALLOWED_CHARACTERS}]: {rendered}"
        )
    return value


def parse_roster(raw: str) -> tuple[str, ...]:
    """A comma-separated roster, validated entry by entry.

    Splits on `,` and nothing else. A newline, a semicolon or a Unicode
    separator inside an entry is *not* treated as a delimiter — it makes that
    entry invalid, which is the answer that stops rather than the answer that
    reinterprets.
    """
    if not raw.strip(_TRIMMED):
        return ()

    entries = [entry.strip(_TRIMMED) for entry in raw.split(",")]
    if len(entries) > MAX_ROSTER_SIZE:
        raise InvalidModelIdentifier(
            f"roster has {len(entries)} entries, over the {MAX_ROSTER_SIZE} limit"
        )
    return tuple(validate_identifier(entry) for entry in entries)


def canonical_roster(raw: str) -> str:
    """The roster re-joined from validated entries.

    Emitting what was parsed rather than echoing the input is the point: the
    caller then uses a string this module has vouched for, not the one it was
    handed, so any leading space or trailing comma that survived validation
    cannot travel onwards.
    """
    return ",".join(parse_roster(raw))


def main(argv: list[str] | None = None) -> int:
    """Validate a roster for a shell caller: canonical form on stdout, or exit 1.

    `tools/run_rsi_isolated.sh` runs this before it mounts the gateway
    credentials, so a refusal happens while nothing sensitive is in reach. It
    runs the FILE, not `-m maistro_rsi.model_identifiers`: `-m` initialises the
    package, whose `__init__` imports `coordinator` and third-party
    dependencies, and the wrapper's whole premise is that the host needs
    nothing but Docker. This module imports only the standard library so that
    stays true.
    """
    parser = argparse.ArgumentParser(
        prog="python -m maistro_rsi.model_identifiers",
        description="Validate a comma-separated model roster before it reaches a command line.",
    )
    parser.add_argument("--roster", required=True, help="comma-separated model identifiers")
    parser.add_argument(
        "--single",
        action="store_true",
        help="the value names ONE model; a comma-separated list is refused",
    )
    arguments = parser.parse_args(argv)

    try:
        canonical = canonical_roster(arguments.roster)
        if arguments.single and canonical.count(",") >= 1:
            raise InvalidModelIdentifier(
                f"expected one model identifier, got {canonical.count(',') + 1}: "
                f"{arguments.roster!r}"
            )
        print(canonical)
    except InvalidModelIdentifier as refusal:
        print(f"refusing model roster: {refusal}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
