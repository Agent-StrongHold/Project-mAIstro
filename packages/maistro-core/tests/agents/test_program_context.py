"""program_context.py — per-persona interview registry (Persona/Workspace Phase B)."""

from __future__ import annotations

from maistro.agents.program_context import (
    INTERVIEW_STEPS,
    INTERVIEW_TEMPLATES,
    ProgramContext,
    apply_interview_answer,
    current_interview_question,
    interview_steps_for,
)


def test_interview_steps_alias_matches_pm_fleet_template() -> None:
    """Backward-compat: existing INTERVIEW_STEPS consumers (maistro.agents.hyperagent)
    must see exactly today's fixed 5-question PM Fleet script, unchanged."""
    assert INTERVIEW_TEMPLATES["pm_fleet"] == INTERVIEW_STEPS
    assert len(INTERVIEW_STEPS) == 5


def test_unknown_use_case_falls_back_to_generic() -> None:
    assert interview_steps_for("some_new_persona") == INTERVIEW_TEMPLATES["_generic"]


def test_default_use_case_is_pm_fleet() -> None:
    ctx = ProgramContext.empty("u1")
    q = current_interview_question(ctx)
    assert q == INTERVIEW_TEMPLATES["pm_fleet"][0]


def test_generic_use_case_asks_generic_questions() -> None:
    ctx = ProgramContext.empty("u1", project_id="ws-canvas")
    q = current_interview_question(ctx, use_case="canvas_creative")
    assert q == INTERVIEW_TEMPLATES["_generic"][0]


def test_generic_interview_completes_after_its_own_shorter_script() -> None:
    ctx = ProgramContext.empty("u1", project_id="ws-canvas")
    for answer in ["My Workspace", "Ship the thing", "GitHub", "Never delete prod"]:
        ctx = apply_interview_answer(ctx, answer, use_case="canvas_creative")
    assert ctx.interview_complete is True
    assert ctx.interview_step == len(INTERVIEW_TEMPLATES["_generic"])


def test_pm_fleet_five_question_flow_is_unchanged() -> None:
    ctx = ProgramContext.empty("u1")
    answers = [
        "Q3 Platform Migration",
        "Ship auth v2\nCut latency 30%",
        "Jira, GitHub, Slack",
        "Vendor API rate limits",
        "VP Eng, Design Lead",
    ]
    for answer in answers:
        ctx = apply_interview_answer(ctx, answer)
    assert ctx.interview_complete is True
    assert ctx.program_name == "Q3 Platform Migration"
    assert ctx.goals == ["Ship auth v2", "Cut latency 30%"]
    assert ctx.stakeholders == ["VP Eng", "Design Lead"]


def test_generic_interview_finalization_uses_neutral_wording_not_pm_phrasing() -> None:
    """A non-PM persona finishing the generic interview must not get PM-specific
    'dependency'/'milestone' phrasing injected into its context."""
    ctx = ProgramContext.empty("u1", project_id="ws-canvas")
    for answer in ["My Workspace", "Ship the thing", "GitHub", "Never delete prod"]:
        ctx = apply_interview_answer(ctx, answer, use_case="canvas_creative")
    assert ctx.interview_complete is True
    assert ctx.summary.startswith("Workspace: My Workspace.")
    assert "Program:" not in ctx.summary
    for q in ctx.open_questions:
        assert "dependency" not in q.lower()
        assert "milestone" not in q.lower()


def test_pm_fleet_finalization_keeps_its_original_wording() -> None:
    ctx = ProgramContext.empty("u1")
    answers = [
        "Q3 Platform Migration",
        "Ship auth v2",
        "Jira, GitHub, Slack",
        "Vendor API rate limits",
        "VP Eng, Design Lead",
    ]
    for answer in answers:
        ctx = apply_interview_answer(ctx, answer)
    assert ctx.summary.startswith("Program: Q3 Platform Migration.")
    assert ctx.open_questions == [
        "What is the single highest-risk dependency this month?",
        "Which milestone should we protect first?",
    ]


def test_two_workspaces_for_one_user_track_independent_interview_progress() -> None:
    """Phase B acceptance bar: two personas for the same user run independently."""
    pm_ctx = ProgramContext.empty("u1", project_id="ws-pm")
    canvas_ctx = ProgramContext.empty("u1", project_id="ws-canvas")

    pm_ctx = apply_interview_answer(pm_ctx, "Q3 Platform Migration")
    assert pm_ctx.interview_step == 1
    assert canvas_ctx.interview_step == 0  # untouched

    canvas_ctx = apply_interview_answer(canvas_ctx, "My Workspace", use_case="canvas_creative")
    assert canvas_ctx.interview_step == 1
    assert pm_ctx.interview_step == 1  # still independent

    assert pm_ctx.project_id == "ws-pm"
    assert canvas_ctx.project_id == "ws-canvas"
    assert pm_ctx.user_id == canvas_ctx.user_id == "u1"


class TestCustomInterviewSteps:
    """A persona's own declared interview script (PersonaTemplate.interview,
    threaded through as `custom_steps`) takes priority over both the canned
    use_case scripts and the generic fallback -- PersonaWizard's authoring
    slice."""

    _CUSTOM = (
        {"field": "program_name", "agent": "host", "question": "What's this workspace for?"},
        {"field": "vibe", "agent": "host", "question": "What vibe are we going for?"},
    )

    def test_custom_steps_win_over_the_generic_fallback(self) -> None:
        assert interview_steps_for("brand_new_persona", self._CUSTOM) == self._CUSTOM

    def test_custom_steps_win_over_a_known_use_cases_canned_script(self) -> None:
        assert interview_steps_for("pm_fleet", self._CUSTOM) == self._CUSTOM

    def test_empty_custom_steps_falls_back_to_use_case_resolution(self) -> None:
        assert interview_steps_for("pm_fleet", ()) == INTERVIEW_TEMPLATES["pm_fleet"]
        assert interview_steps_for("pm_fleet", None) == INTERVIEW_TEMPLATES["pm_fleet"]

    def test_current_interview_question_uses_custom_steps(self) -> None:
        ctx = ProgramContext.empty("u1", project_id="ws-1")
        q = current_interview_question(ctx, use_case="brand_new_persona", custom_steps=self._CUSTOM)
        assert q == self._CUSTOM[0]

    def test_apply_interview_answer_advances_through_custom_steps(self) -> None:
        ctx = ProgramContext.empty("u1", project_id="ws-1")
        ctx = apply_interview_answer(
            ctx, "A dinner party planner", use_case="brand_new_persona", custom_steps=self._CUSTOM
        )
        assert ctx.interview_step == 1
        assert ctx.program_name == "A dinner party planner"  # known field -> typed capture

        ctx = apply_interview_answer(
            ctx, "Warm and playful", use_case="brand_new_persona", custom_steps=self._CUSTOM
        )
        assert ctx.interview_step == 2
        assert ctx.interview_complete is True
        # "vibe" isn't a known ProgramContext field -- still captured as a
        # freeform fact rather than silently dropped.
        assert any("vibe" in f and "Warm and playful" in f for f in ctx.facts)
