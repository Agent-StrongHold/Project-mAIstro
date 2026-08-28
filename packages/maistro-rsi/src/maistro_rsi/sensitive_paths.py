"""Which paths sit on the agent's own containment surface, and the matcher.

Split out of ``quarantine.py`` (#303) for two reasons.

The first is dependency weight. ``quarantine.py`` imports Warden, which pulls
the whole security stack; the classifier itself is pure string work over path
fragments. ``scripts/check-promotion-surface.py`` has to consult the *real*
matcher rather than reimplement it -- an earlier gate reimplemented this logic
and drifted from it -- and a static gate that needs the security stack
installed to answer "is this path protected" is a gate that gets skipped in the
lint job. Nothing here imports anything outside the standard library, and
nothing here imports at all.

The second is that the classifier is now itself a governed object. #303's rule
is that a candidate must not be able to edit the thing that decides whether its
edit needs review, in the change that edit authorizes. That is easier to state,
and to check, when the decision lives in one small module with its own tests.

``quarantine.py`` re-exports both names, so existing callers are unaffected.
"""

from __future__ import annotations

# Path fragments that mark the agent's own containment surface. A diff touching
# any of these isn't blocked -- it's escalated to require adversarial review on
# top of Warden + the full test suite, because a change here changes what
# *future* self-modifications are allowed to get away with.
#
# The list used to name individual modules inside `maistro_rsi/` and
# `maistro_evolve/`, added one at a time as each omission was found by a human
# reading a diff. #303 found three more that way -- `local_loop.py`, which
# fast-forwards the baseline branch; `merge.py`, which decides which candidates
# land; and `code_fixer.py`, which executes candidate code -- and the pattern of
# discovery is the actual defect. `scripts/check-promotion-surface.py` now
# derives the requirement from the import graph reachable from the promotion
# and execution entry points, and the two directory patterns below are strictly
# broader than the ~20 file patterns they replace.
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    # --- the self-improvement machine, whole --------------------------------
    # Every module under these decides, scores, executes or applies a
    # self-modification. Enumerating them individually is how the omissions got
    # in; a directory pattern cannot fall behind a new file.
    "maistro_rsi/",
    "maistro_evolve/",
    # The builders agent the loop drives: it runs candidate code, and it owns
    # the sandbox selection that decides where that code runs.
    "maistro_bootstrap/builders/",
    "maistro_bootstrap/repo_root.py",
    # --- their own tests ----------------------------------------------------
    # A candidate that edits the classifier *and* the tests pinning it in one
    # diff authorizes itself. Protecting the code without its tests leaves that
    # open, so both suites escalate.
    "maistro-rsi/tests/",
    "maistro-evolve/tests/",
    # --- what the loop reaches into -----------------------------------------
    "maistro/security/",
    # The shared client is where the outbound guard is *installed*:
    # `_guard_built_transports` wraps the real transports with
    # `maistro.security.outbound.guarded`. The policy living under
    # `maistro/security/` does not help if the installation can be deleted
    # here, so protecting the policy without its installation left the egress
    # boundary removable by a diff that never touches a protected path
    # (Codex, #513). This module was previously *tolerated* on exactly that
    # reasoning, which was true about where the policy is written and beside
    # the point about where it takes effect.
    "maistro/http.py",
    # `SandboxSettings` lives here: `network_disabled`, the sandbox image, and
    # the microVM kernel/rootfs defaults. The protected sandbox implementations
    # read these values, so a candidate flipping `network_disabled` gives
    # itself network access without touching any protected module. Tolerated
    # before because it "makes no acceptance decision" -- correct, and not the
    # question: it makes a containment decision (Codex, #513).
    "maistro/config/settings.py",
    "maistro/tools/sandbox/",
    # Opening a pull request is a promotion path: it is how a candidate's diff
    # leaves the sandbox and reaches human reviewers, and a change here can
    # decide which branch or repository receives it.
    "maistro/tools/git/",
    # Cumulative action-budget enforcement.
    "maistro/policy/",
    # SafeHarnessRunner composes Warden and the ActionGate but lives under
    # capabilities/, so the "maistro/security/" pattern above never saw it.
    "maistro/capabilities/providers/",
    # The DAG-synthesis substrate that lets an agent spawn further
    # sub-agents/DAGs: the recursion-depth cap and the two node kinds that
    # dispatch through it.
    "maistro/graph/depth.py",
    "maistro/graph/nodes/agent_synth_dag.py",
    "maistro/graph/nodes/agent_spawn_harness.py",
    # The durable executor carries the actual depth-cap *enforcement* between
    # nodes (it's what increments/surfaces synth_depth across checkpoints) --
    # a diff here can defang the cap just as effectively as touching depth.py
    # itself. Matched at directory granularity: the whole package persists
    # depth state, so `executor.py` alone left its siblings uncovered.
    "maistro/graph/durable_runs/",
    # --- the gates, and the ratchet baselines they read ---------------------
    # Previously the only thing standing between the loop and its own CI config
    # was a sentence in a prompt telling the model not to touch it.
    ".github/",
    "quality/",
    # The sandbox kit: it sets the backend *and* attests the isolation that
    # makes LocalSandbox safe (see sandbox/microvm.py).
    "sbx/",
    # The ratchets and vendoring scripts that assert all of the above is intact,
    # and their tests. A guard outside the surface it guards is not a guard: a
    # diff could otherwise edit a checker and the list it protects in one commit
    # and still leave CI green. The `vendor_*.py` scripts additionally carry the
    # pinned digests of the vendored graders, so weakening one of them is
    # equivalent to editing the grader itself.
    "scripts/check_enumerations.py",
    "scripts/check-promotion-surface.py",
    "scripts/vendor_ifeval.py",
    "scripts/vendor_bfcl.py",
    "tests/test_check_enumerations.py",
    "tests/test_check_promotion_surface.py",
)


def normalize_touched_path(path: str) -> str:
    """A diff path in the one spelling the patterns are written against."""
    normalized = path.replace("\\", "/")
    # removeprefix, not lstrip("./"): lstrip takes a character set and would
    # eat the leading dot of ".github/..." — turning a containment surface
    # into an unmatched path. That exact bug shipped once.
    while normalized.startswith("./"):
        normalized = normalized.removeprefix("./")
    return normalized


def matches_sensitive_pattern(path: str) -> bool:
    """True if ``path`` falls on the containment surface.

    Segment-boundary matching, not raw substring: directory patterns match at
    the path start or after a ``/``; file patterns must match a whole trailing
    path segment. Raw ``pattern in path`` accepted ``notmaistro/security/x``
    and rejected nothing adjacent — both directions were wrong.
    """
    normalized = normalize_touched_path(path)
    for pattern in SENSITIVE_PATH_PATTERNS:
        if pattern.endswith("/"):
            if normalized.startswith(pattern) or f"/{pattern}" in normalized:
                return True
        elif normalized == pattern or normalized.endswith(f"/{pattern}"):
            return True
    return False
