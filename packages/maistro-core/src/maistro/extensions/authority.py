"""Requested-authority computation for extension installs (#953, M9-B2).

Permissions are the extension authority currency: an install may never widen
what was granted before without the authority delta surfacing as new, named
permissions that an operator explicitly approves. The delta is computed
against a scope baseline — permissions already granted to this extension in
this scope (its currently-active version) plus platform pre-approvals — so the
authorization decision shows exactly what is genuinely new.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_permission(token: str) -> str:
    """Validate one permission token and return it unchanged.

    The grammar is shared with the manifest parser: lowercase dotted tokens
    (``network.http``, ``storage.workspace``). Anything else is a manifest
    defect and must be rejected at parse time, not normalized into something
    the operator didn't read.
    """
    if (
        not isinstance(token, str)
        or re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", token) is None
    ):
        raise ValueError(f"malformed permission token: {token!r}")
    return token


@dataclass(frozen=True)
class AuthorityBaseline:
    """Authority already held, against which a request is compared."""

    #: Permissions granted to this extension by its currently-active version
    #: in the target scope (empty for a first install).
    previously_granted: frozenset[str] = frozenset()
    #: Permissions the platform pre-approves without operator review.
    pre_approved: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AuthorityDelta:
    """What a requested permission set changes against its baseline."""

    #: Requested permissions not covered by the baseline — the set an
    #: authorization decision is really about.
    new: tuple[str, ...] = ()
    #: Requested permissions the baseline already covers.
    retained: tuple[str, ...] = ()
    #: Baseline permissions the request does not ask for (context only; B2
    #: installs never silently drop existing grants — that is #954's
    #: upgrade/rollback authority rule).
    dropped: tuple[str, ...] = ()

    @property
    def requires_authorization(self) -> bool:
        """True when the request asks for authority the baseline lacks."""
        return bool(self.new)


def compute_authority_delta(
    requested: tuple[str, ...] | list[str],
    baseline: AuthorityBaseline,
) -> AuthorityDelta:
    """Compute the authority delta of a requested permission set."""
    requested_set = {normalize_permission(token) for token in requested}
    covered = baseline.previously_granted | baseline.pre_approved
    new = tuple(sorted(requested_set - covered))
    retained = tuple(sorted(requested_set & covered))
    dropped = tuple(sorted(baseline.previously_granted - requested_set))
    return AuthorityDelta(new=new, retained=retained, dropped=dropped)
