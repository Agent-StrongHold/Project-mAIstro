"""Building a Content-Security-Policy that cannot quietly stop being one (#310).

A CSP is a string, and a string is exactly the wrong shape for a security
control. `"default-src 'self'; script-src 'self' 'unsafe-inline'"` looks like a
policy, passes every test that checks the header is present, and permits the
attack the header exists to stop. The header being *set* is not the property
anyone wants; the header being *restrictive* is, and only reading it closely
tells the two apart.

So the mechanism lives here as a value with invariants rather than as
formatting. `ContentSecurityPolicy` refuses at construction the four ways a
policy is usually hollowed out:

- **`'unsafe-inline'` in `script-src`.** The single directive that returns a
  policy to no policy at all against injected markup, which is what a CSP is
  for. There is no argument for it that a nonce or a hash does not answer
  better, so this type does not accept one.
- **`'unsafe-eval'` anywhere.** Same reasoning, one step removed.
- **A missing floor.** `default-src` is what every unlisted fetch directive
  falls back to. Without it, `media-src`, `worker-src`, `manifest-src` and
  anything the spec adds next are unrestricted, and the policy reads
  restrictive while covering less than it appears to.
- **A missing `object-src`, `base-uri`, `form-action` or `frame-ancestors`.**
  The first three do not inherit from `default-src` usefully — `base-uri` and
  `form-action` do not inherit at all — and each is a documented bypass on its
  own: `<object>` executes plugins, `<base>` rewrites every relative URL on the
  page, and a rewritten `form action` exfiltrates whatever the user types next.
  `frame-ancestors` is the one that supersedes `X-Frame-Options`.

The *policy* — which origins a particular product's front end actually needs —
is not here. That is a fact about an application's own assets, and belongs with
the application (ADR-019). What this module knows is the shape a policy has to
have before it is worth serving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: The document's own origin.
SELF: Final = "'self'"

#: Nothing at all. Narrower than omitting the directive, which falls back to
#: `default-src`.
NONE: Final = "'none'"

#: Directives that must be stated rather than inherited, and why, in the order
#: a reader would want to meet them.
REQUIRED_DIRECTIVES: Final[tuple[str, ...]] = (
    "default-src",
    "object-src",
    "base-uri",
    "form-action",
    "frame-ancestors",
)

#: Source expressions that turn a policy back into no policy.
FORBIDDEN_IN_SCRIPT_SRC: Final = "'unsafe-inline'"
FORBIDDEN_ANYWHERE: Final = "'unsafe-eval'"

#: Directives that are a bare name with no source list. They are not "empty" —
#: they carry their whole meaning in being present — so they are the one case
#: where no sources is correct rather than a mistake.
VALUELESS_DIRECTIVES: Final[frozenset[str]] = frozenset({"upgrade-insecure-requests"})


class InsecurePolicyError(ValueError):
    """A policy that would be served but would not restrict anything."""


@dataclass(frozen=True)
class ContentSecurityPolicy:
    """A validated policy, and the header that carries it.

    Constructed from `{directive: sources}`. Sources are kept in the order
    given: a policy is read by people as often as by browsers, and reordering
    them alphabetically would put `'self'` in the middle of a list of origins.
    """

    directives: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def build(cls, directives: dict[str, tuple[str, ...]]) -> ContentSecurityPolicy:
        """Validate and freeze. Raises `InsecurePolicyError` on a hollow policy."""
        missing = [name for name in REQUIRED_DIRECTIVES if name not in directives]
        if missing:
            raise InsecurePolicyError(
                f"policy omits {', '.join(missing)} — an unlisted directive either "
                f"falls back to default-src or is unrestricted, and both read as "
                f"stricter than they are"
            )

        script = directives.get("script-src", ())
        if FORBIDDEN_IN_SCRIPT_SRC in script:
            raise InsecurePolicyError(
                f"script-src contains {FORBIDDEN_IN_SCRIPT_SRC}, which permits exactly "
                f"the injected script this header exists to block; use a nonce, a hash, "
                f"or move the script into a served file"
            )
        for name, sources in directives.items():
            if FORBIDDEN_ANYWHERE in sources:
                raise InsecurePolicyError(
                    f"{name} contains {FORBIDDEN_ANYWHERE}, which lets injected text "
                    f"become executable code"
                )
            if not sources and name not in VALUELESS_DIRECTIVES:
                raise InsecurePolicyError(
                    f"{name} has no sources — a fetch directive served as a bare name "
                    f"is read as {NONE}, which is rarely what the author meant; say "
                    f"{NONE} if it is"
                )

        return cls(tuple((name, tuple(sources)) for name, sources in directives.items()))

    def header_value(self) -> str:
        """The header's value, directives in declaration order."""
        return "; ".join(
            name if not sources else f"{name} {' '.join(sources)}"
            for name, sources in self.directives
        )

    def sources_for(self, directive: str) -> tuple[str, ...]:
        """What `directive` permits, or `()` if it is not stated."""
        return dict(self.directives).get(directive, ())

    @staticmethod
    def header_name(*, report_only: bool) -> str:
        """`Content-Security-Policy`, or the report-only header.

        Report-only is a rollout instrument, not a weaker setting: the browser
        evaluates the same policy and reports what it *would* have blocked
        without blocking it. Serving it under the enforcing name is the whole
        difference between finding out and finding out the hard way, so the two
        names come from one place rather than being spelled at each call site.
        """
        return "Content-Security-Policy-Report-Only" if report_only else "Content-Security-Policy"
