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
    # --- the Conductor's own RSI execution surface --------------------------
    # The product ships two production entry points for the capabilities this
    # list governs, and the `maistro_rsi/` and `maistro_evolve/` patterns above
    # never reached them because they live in the Conductor's flat backend:
    # `services/rsi.py` constructs and runs `LocalRsiLoop`, and `routes/rsi.py`
    # approves a candidate patch and applies it with `git am`. Applying a
    # self-modification patch is a promotion, wherever the code that does it
    # happens to live (Codex, #513).
    "hive-conductor/backend/services/rsi.py",
    "hive-conductor/backend/routes/rsi.py",
    # The #509 dispatch backend: it builds the ``docker run`` argv that decides
    # WHERE a run's candidate code executes — caps, mounts, network, user,
    # interpreter resolution. A candidate that could edit it could move its own
    # execution back onto the host without touching either file above — the
    # same one-diff authorization hole the test-suite patterns below close for
    # the classifier itself, so its pinning suite travels with it.
    "hive-conductor/backend/services/rsi_container_dispatch.py",
    "hive-conductor/backend/tests/test_rsi_container_dispatch.py",
    # The services package initializer, on the same reasoning as the others
    # below: a docstring today, on the runtime import path regardless.
    "hive-conductor/backend/services/__init__.py",
    # The acceptance-criteria trees (#109): docs/specs/SPEC-*.md enumerate the
    # ACs the loop's spec-completion signal is scored against. A candidate that
    # can rewrite the contract can manufacture its own success evidence, so the
    # trees escalate here AND sit on the stricter evaluator-oracle surface
    # below, where a candidate diff touching them is vetoed before scoring.
    "docs/specs/",
    # Package initializers on the promotion path. Python executes these before
    # the module actually imported, so they are on the runtime import path even
    # when they only re-export. They are re-export shims *today*, and a
    # tolerance recording that would outlive the fact -- the next reader would
    # inherit a reason that was checked once. Escalating them costs an
    # adversarial review only when somebody edits a re-export shim, which is
    # rare; the alternative costs nothing until it costs containment
    # (Codex, #513).
    "maistro/__init__.py",
    "maistro/config/__init__.py",
    "maistro/observability/__init__.py",
    "maistro/quota/__init__.py",
    "maistro/tools/__init__.py",
    "maistro/types/__init__.py",
    "maistro_bootstrap/__init__.py",
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
    # The governed capability-effect boundary (#55/#1362): governed_invocation
    # evaluates the invocation policy and enforces the durable approvals it
    # consults; authority.py and approval_store.py are the approval authority
    # and its durable record; invocation.py is the external-effect boundary and
    # the invocation stores are its durable state. A candidate that can edit
    # any of these can weaken the approval/effect gate without touching
    # security/ or capabilities/providers/, so they sit on the sensitive
    # surface instead of being tolerated as baseline admission (Codex review,
    # chore/authorize-effect-door-promotion).
    "maistro/capabilities/governed_invocation.py",
    "maistro/capabilities/authority.py",
    "maistro/capabilities/approval_store.py",
    # binding_store.py is the gate itself, not a record of one: `_resolve` and
    # `_scope_checked` enforce registration, disablement, revocation, and
    # workspace/project/node/capability scope before every physical effect.
    # `binding.py` next to it really is an inert dataclass and stays tolerated;
    # this one is where a candidate would weaken the check and authorize its
    # own effects without touching a protected module (Codex, #1758).
    "maistro/capabilities/binding_store.py",
    "maistro/capabilities/invocation.py",
    "maistro/capabilities/invocation_store.py",
    "maistro/capabilities/pg_invocation_store.py",
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
    # --- the Conductor's RSI containment, now that the gate can see it ------
    # `packages/*/src` never matched the Conductor's flat backend, so these were
    # invisible to the promotion-surface walk until #513 added that source root
    # and rooted `services.rsi` / `routes.rsi`. They are not newly reachable;
    # they are newly *visible*, and both make containment decisions.
    #
    # `rsi_execution_policy` IS the containment: it resolves which repository an
    # HTTP-initiated run may touch, which argument vector it may execute, and
    # whether isolation is available at all. A candidate editing it authorizes
    # its own path and its own command.
    "services/rsi_execution_policy.py",
    # And the settings the policy reads — `rsi_repo_roots` above all. Protecting
    # the policy while leaving its inputs editable is the same mistake #513
    # found with `maistro/http.py`: the rule is written in one file and takes
    # effect from another.
    "hive-conductor/backend/config.py",
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


# The evaluator-oracle surface (#109): the artifacts that DEFINE what success
# means for a candidate -- the scorer, the scenario corpus it is judged
# against, the ratchet baselines, and the acceptance-criteria trees. This is a
# STRICTER tier than ``SENSITIVE_PATH_PATTERNS``: sensitive paths escalate a
# diff to adversarial review before it may leave the sandbox, while a candidate
# that edits the oracle it is scored against must be vetoed BEFORE the mutated
# oracle produces its acceptance evidence (``LocalRsiLoop`` enforces this at
# scoring time, see ``evaluator_oracle.py``). RSI may satisfy the oracle; it
# may not edit it. Human governance changes remain possible through the
# explicit ``allow_evaluator_mutation`` override (recorded, never silent) and
# through ordinary reviewed PRs, which never pass through the loop.
#
# Entries here follow the same segment-boundary matching rules as
# ``SENSITIVE_PATH_PATTERNS``. Keep the list derived from what the scoring
# path actually consumes; every entry must match tracked files (the generated-
# artifact guard patterns live in ``evaluator_oracle.GENERATED_ORACLE_PATTERNS``
# because they deliberately match untracked output).
EVALUATOR_ORACLE_PATTERNS: tuple[str, ...] = (
    # The scoring machine, whole: candidate_fitness, fail_first, regression
    # judge, test inventory, spec tracker, scorecard, benchmark harnesses. A
    # candidate that edits any of them is judged by the thing it just changed.
    "maistro_rsi/",
    "maistro_evolve/",
    # The tests that pin the evaluator: same one-diff authorization hole the
    # sensitive list closes, one tier stricter -- the mutated tests ARE the
    # acceptance evidence the test command produces.
    "maistro-rsi/tests/",
    "maistro-evolve/tests/",
    # The vendored graders carry the pinned digests of the scenario corpora;
    # weakening one is editing the exam.
    "scripts/vendor_ifeval.py",
    "scripts/vendor_bfcl.py",
    # Ratchet baselines: the recorded floors the quality gates score against.
    "quality/",
    # The acceptance-criteria trees (docs/specs/SPEC-*.md): the contracts the
    # spec-completion signal scores against. Additions are the designed
    # spec_proposed contribution and stay allowed -- the enforcement layer
    # (evaluator_oracle.py) vetoes MUTATIONS of oracle files tracked at the
    # base revision, so a candidate can contract new work but cannot rewrite
    # the definition of done it inherits.
    "docs/specs/",
)

# Generated artifacts a candidate diff may never carry (#109): compiled
# bytecode, package build output and import-time hook files can hijack the
# oracle's own execution (a crafted .pyc with a matching source header, a
# sitecustomize.py imported before the scorer) without any listed path looking
# edited. A leading ``*`` marks a SUBSTRING pattern (``*.egg-info/`` matches
# any ``<pkg>.egg-info/`` directory — segment-boundary matching can't express
# a suffix inside a segment); everything else matches at segment boundaries
# like the sensitive tier. They live here rather than in
# EVALUATOR_ORACLE_PATTERNS because they are untracked by design — a
# dead-pattern ratchet over them would fail on exactly the property that
# makes them dangerous.
GENERATED_ORACLE_PATTERNS: tuple[str, ...] = (
    "__pycache__/",
    "*.egg-info/",
    "sitecustomize.py",
    "usercustomize.py",
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


def _matches_segment_patterns(path: str, patterns: tuple[str, ...]) -> bool:
    """Segment-boundary matching shared by both pattern tiers.

    Directory patterns match at the path start or after a ``/``; file patterns
    must match a whole trailing path segment. Raw ``pattern in path`` accepted
    ``notmaistro/security/x`` and rejected nothing adjacent — both directions
    were wrong.
    """
    for pattern in patterns:
        if pattern.endswith("/"):
            if path.startswith(pattern) or f"/{pattern}" in path:
                return True
        elif path == pattern or path.endswith(f"/{pattern}"):
            return True
    return False


def matches_evaluator_oracle_pattern(path: str) -> bool:
    """True if ``path`` sits on the evaluator-oracle surface (#109).

    Same matcher semantics as :func:`matches_sensitive_pattern` (including
    :func:`normalize_touched_path`), over the stricter oracle tier -- kept as a
    separate function so the two surfaces can drift deliberately, not
    accidentally.
    """
    return _matches_segment_patterns(normalize_touched_path(path), EVALUATOR_ORACLE_PATTERNS)


def matches_sensitive_pattern(path: str) -> bool:
    """True if ``path`` falls on the containment surface.

    Segment-boundary matching, not raw substring: directory patterns match at
    the path start or after a ``/``; file patterns must match a whole trailing
    path segment. Raw ``pattern in path`` accepted ``notmaistro/security/x``
    and rejected nothing adjacent — both directions were wrong.
    """
    return _matches_segment_patterns(normalize_touched_path(path), SENSITIVE_PATH_PATTERNS)
