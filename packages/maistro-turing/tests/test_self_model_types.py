"""Tests for self_model/types.py: personality, mood, todo, and node-kind types."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_turing.self_model.types import (
    ActivationContributor,
    ContributorOrigin,
    Hobby,
    Interest,
    Mood,
    NodeKind,
    Passion,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    PersonalityRevision,
    Preference,
    PreferenceKind,
    SelfTodo,
    SelfTodoRevision,
    Skill,
    SkillKind,
    Trait,
    current_level,
    facet_node_id,
    guess_node_kind,
)


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------- PersonalityFacet


class TestPersonalityFacet:
    def test_valid_facet_constructs(self) -> None:
        facet = PersonalityFacet(
            node_id=facet_node_id(Trait.OPENNESS, "creativity"),
            self_id="self-1",
            trait=Trait.OPENNESS,
            facet_id="creativity",
            score=3.5,
            last_revised_at=_now(),
        )
        assert facet.score == 3.5
        assert facet.node_id == "facet:openness.creativity"

    def test_score_below_range_raises(self) -> None:
        with pytest.raises(ValueError, match="facet score out of range"):
            PersonalityFacet(
                node_id="x",
                self_id="self-1",
                trait=Trait.OPENNESS,
                facet_id="creativity",
                score=0.5,
                last_revised_at=_now(),
            )

    def test_score_above_range_raises(self) -> None:
        with pytest.raises(ValueError, match="facet score out of range"):
            PersonalityFacet(
                node_id="x",
                self_id="self-1",
                trait=Trait.OPENNESS,
                facet_id="creativity",
                score=5.5,
                last_revised_at=_now(),
            )

    def test_unknown_facet_id_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown facet_id"):
            PersonalityFacet(
                node_id="x",
                self_id="self-1",
                trait=Trait.OPENNESS,
                facet_id="not_a_real_facet",
                score=3.0,
                last_revised_at=_now(),
            )

    def test_facet_belonging_to_wrong_trait_raises(self) -> None:
        with pytest.raises(ValueError, match="does not belong to trait"):
            PersonalityFacet(
                node_id="x",
                self_id="self-1",
                trait=Trait.OPENNESS,
                facet_id="sincerity",  # belongs to HONESTY_HUMILITY
                score=3.0,
                last_revised_at=_now(),
            )

    def test_missing_self_id_raises(self) -> None:
        with pytest.raises(ValueError, match="self_id is required"):
            PersonalityFacet(
                node_id="x",
                self_id="",
                trait=Trait.OPENNESS,
                facet_id="creativity",
                score=3.0,
                last_revised_at=_now(),
            )


# --------------------------------------------------------------- PersonalityItem


class TestPersonalityItem:
    def test_valid_item_constructs(self) -> None:
        item = PersonalityItem(
            node_id="item-1",
            self_id="self-1",
            item_number=1,
            prompt_text="I enjoy trying new things.",
            keyed_facet="creativity",
            reverse_scored=False,
        )
        assert item.item_number == 1

    def test_item_number_below_range_raises(self) -> None:
        with pytest.raises(ValueError, match="item_number out of range"):
            PersonalityItem(
                node_id="x",
                self_id="self-1",
                item_number=0,
                prompt_text="p",
                keyed_facet="creativity",
                reverse_scored=False,
            )

    def test_item_number_above_range_raises(self) -> None:
        with pytest.raises(ValueError, match="item_number out of range"):
            PersonalityItem(
                node_id="x",
                self_id="self-1",
                item_number=201,
                prompt_text="p",
                keyed_facet="creativity",
                reverse_scored=False,
            )

    def test_unknown_keyed_facet_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown keyed_facet"):
            PersonalityItem(
                node_id="x",
                self_id="self-1",
                item_number=1,
                prompt_text="p",
                keyed_facet="not_real",
                reverse_scored=False,
            )


# ------------------------------------------------------------- PersonalityAnswer


class TestPersonalityAnswer:
    def test_valid_answer_constructs(self) -> None:
        answer = PersonalityAnswer(
            node_id="x",
            self_id="self-1",
            item_id="item-1",
            revision_id=None,
            answer_1_5=3,
            justification_text="seems about right",
            asked_at=_now(),
        )
        assert answer.answer_1_5 == 3

    @pytest.mark.parametrize("bad_answer", [0, 6, -1])
    def test_answer_out_of_range_raises(self, bad_answer: int) -> None:
        with pytest.raises(ValueError, match=r"answer must be 1\.\.5"):
            PersonalityAnswer(
                node_id="x",
                self_id="self-1",
                item_id="item-1",
                revision_id=None,
                answer_1_5=bad_answer,
                justification_text="x",
                asked_at=_now(),
            )

    def test_justification_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="justification_text exceeds 200 chars"):
            PersonalityAnswer(
                node_id="x",
                self_id="self-1",
                item_id="item-1",
                revision_id=None,
                answer_1_5=3,
                justification_text="x" * 201,
                asked_at=_now(),
            )

    def test_justification_at_limit_is_allowed(self) -> None:
        answer = PersonalityAnswer(
            node_id="x",
            self_id="self-1",
            item_id="item-1",
            revision_id=None,
            answer_1_5=3,
            justification_text="x" * 200,
            asked_at=_now(),
        )
        assert len(answer.justification_text) == 200


# ----------------------------------------------------------- PersonalityRevision


class TestPersonalityRevision:
    def test_valid_revision_constructs(self) -> None:
        revision = PersonalityRevision(
            node_id="x",
            self_id="self-1",
            revision_id="rev-1",
            ran_at=_now(),
            sampled_item_ids=[f"item-{i}" for i in range(20)],
            deltas_by_facet={"creativity": 0.1},
        )
        assert len(revision.sampled_item_ids) == 20

    def test_wrong_sample_size_raises(self) -> None:
        with pytest.raises(ValueError, match="retest sample must be exactly 20 items"):
            PersonalityRevision(
                node_id="x",
                self_id="self-1",
                revision_id="rev-1",
                ran_at=_now(),
                sampled_item_ids=[f"item-{i}" for i in range(19)],
                deltas_by_facet={},
            )


# --------------------------------------------------------------------- Passion


class TestPassion:
    def test_valid_passion_constructs(self) -> None:
        passion = Passion(
            node_id="x",
            self_id="self-1",
            text="building things",
            strength=0.8,
            rank=1,
            first_noticed_at=_now(),
        )
        assert passion.strength == 0.8

    @pytest.mark.parametrize("bad_strength", [-0.1, 1.1])
    def test_strength_out_of_range_raises(self, bad_strength: float) -> None:
        with pytest.raises(ValueError, match="strength out of range"):
            Passion(
                node_id="x",
                self_id="self-1",
                text="t",
                strength=bad_strength,
                rank=0,
                first_noticed_at=_now(),
            )

    def test_negative_rank_raises(self) -> None:
        with pytest.raises(ValueError, match="rank must be >= 0"):
            Passion(
                node_id="x",
                self_id="self-1",
                text="t",
                strength=0.5,
                rank=-1,
                first_noticed_at=_now(),
            )


# ----------------------------------------------------------------------- Hobby


def test_hobby_defaults() -> None:
    hobby = Hobby(node_id="x", self_id="self-1", name="woodworking", description="making things")
    assert hobby.strength == 0.5
    assert hobby.last_engaged_at is None


# -------------------------------------------------------------------- Interest


def test_interest_defaults() -> None:
    interest = Interest(
        node_id="x", self_id="self-1", topic="astronomy", description="stars and stuff"
    )
    assert interest.last_noticed_at is None


# ------------------------------------------------------------------ Preference


class TestPreference:
    def test_valid_preference_constructs(self) -> None:
        pref = Preference(
            node_id="x",
            self_id="self-1",
            kind=PreferenceKind.LIKE,
            target="coffee",
            strength=0.9,
            rationale="tastes good",
        )
        assert pref.kind == PreferenceKind.LIKE

    @pytest.mark.parametrize("bad_strength", [-0.5, 1.5])
    def test_strength_out_of_range_raises(self, bad_strength: float) -> None:
        with pytest.raises(ValueError, match="strength out of range"):
            Preference(
                node_id="x",
                self_id="self-1",
                kind=PreferenceKind.DISLIKE,
                target="t",
                strength=bad_strength,
                rationale="r",
            )


# ----------------------------------------------------------------------- Skill


class TestSkill:
    def test_valid_skill_constructs(self) -> None:
        skill = Skill(
            node_id="x",
            self_id="self-1",
            name="python",
            kind=SkillKind.CODING,
            stored_level=0.7,
            last_practiced_at=_now(),
        )
        assert skill.stored_level == 0.7
        assert skill.best_version == 0
        assert skill.active_coaching is None

    @pytest.mark.parametrize("bad_level", [-0.1, 1.1])
    def test_stored_level_out_of_range_raises(self, bad_level: float) -> None:
        with pytest.raises(ValueError, match="stored_level out of range"):
            Skill(
                node_id="x",
                self_id="self-1",
                name="python",
                kind=SkillKind.CODING,
                stored_level=bad_level,
                last_practiced_at=_now(),
            )

    def test_current_level_returns_stored_level_unchanged(self) -> None:
        skill = Skill(
            node_id="x",
            self_id="self-1",
            name="python",
            kind=SkillKind.CODING,
            stored_level=0.65,
            last_practiced_at=_now(),
        )
        # No decay model — current_level always equals stored_level regardless of `at`.
        assert current_level(skill, _now()) == 0.65


# -------------------------------------------------------------------- SelfTodo


class TestSelfTodo:
    def test_valid_active_todo_constructs(self) -> None:
        todo = SelfTodo(
            node_id="x",
            self_id="self-1",
            text="learn rust",
            motivated_by_node_id="passion-1",
        )
        assert todo.status.value == "active"

    def test_missing_motivated_by_raises(self) -> None:
        with pytest.raises(ValueError, match="motivated_by_node_id is required"):
            SelfTodo(
                node_id="x",
                self_id="self-1",
                text="t",
                motivated_by_node_id="",
            )

    def test_text_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="todo text exceeds 500 chars"):
            SelfTodo(
                node_id="x",
                self_id="self-1",
                text="x" * 501,
                motivated_by_node_id="passion-1",
            )

    def test_completed_without_outcome_raises(self) -> None:
        from maistro_turing.self_model.types import TodoStatus

        with pytest.raises(ValueError, match="completed todo requires non-empty outcome_text"):
            SelfTodo(
                node_id="x",
                self_id="self-1",
                text="t",
                motivated_by_node_id="passion-1",
                status=TodoStatus.COMPLETED,
            )

    def test_completed_with_blank_outcome_raises(self) -> None:
        from maistro_turing.self_model.types import TodoStatus

        with pytest.raises(ValueError, match="completed todo requires non-empty outcome_text"):
            SelfTodo(
                node_id="x",
                self_id="self-1",
                text="t",
                motivated_by_node_id="passion-1",
                status=TodoStatus.COMPLETED,
                outcome_text="   ",
            )

    def test_completed_with_outcome_succeeds(self) -> None:
        from maistro_turing.self_model.types import TodoStatus

        todo = SelfTodo(
            node_id="x",
            self_id="self-1",
            text="t",
            motivated_by_node_id="passion-1",
            status=TodoStatus.COMPLETED,
            outcome_text="done",
        )
        assert todo.outcome_text == "done"


# -------------------------------------------------------------- SelfTodoRevision


class TestSelfTodoRevision:
    def test_valid_revision_constructs(self) -> None:
        rev = SelfTodoRevision(
            node_id="x",
            self_id="self-1",
            todo_id="todo-1",
            revision_num=1,
            text_before="old",
            text_after="new",
            revised_at=_now(),
        )
        assert rev.revision_num == 1

    def test_revision_num_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="revision_num starts at 1"):
            SelfTodoRevision(
                node_id="x",
                self_id="self-1",
                todo_id="todo-1",
                revision_num=0,
                text_before="old",
                text_after="new",
                revised_at=_now(),
            )


# ----------------------------------------------------------------------- Mood


class TestMood:
    def test_valid_mood_constructs(self) -> None:
        mood = Mood(self_id="self-1", valence=0.5, arousal=0.5, focus=0.5, last_tick_at=_now())
        assert mood.valence == 0.5

    @pytest.mark.parametrize("bad_valence", [-1.1, 1.1])
    def test_valence_out_of_range_raises(self, bad_valence: float) -> None:
        with pytest.raises(ValueError, match="valence out of range"):
            Mood(
                self_id="self-1",
                valence=bad_valence,
                arousal=0.5,
                focus=0.5,
                last_tick_at=_now(),
            )

    @pytest.mark.parametrize("bad_arousal", [-0.1, 1.1])
    def test_arousal_out_of_range_raises(self, bad_arousal: float) -> None:
        with pytest.raises(ValueError, match="arousal out of range"):
            Mood(
                self_id="self-1",
                valence=0.0,
                arousal=bad_arousal,
                focus=0.5,
                last_tick_at=_now(),
            )

    @pytest.mark.parametrize("bad_focus", [-0.1, 1.1])
    def test_focus_out_of_range_raises(self, bad_focus: float) -> None:
        with pytest.raises(ValueError, match="focus out of range"):
            Mood(
                self_id="self-1",
                valence=0.0,
                arousal=0.5,
                focus=bad_focus,
                last_tick_at=_now(),
            )


# ------------------------------------------------------------ ActivationContributor


class TestActivationContributor:
    def test_valid_contributor_constructs(self) -> None:
        contributor = ActivationContributor(
            node_id="x",
            self_id="self-1",
            target_node_id="facet:openness.creativity",
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="rule-1",
            source_kind="rule",
            weight=0.5,
            origin=ContributorOrigin.RULE,
            rationale="boosted by recent activity",
        )
        assert contributor.weight == 0.5

    def test_self_targeting_raises(self) -> None:
        with pytest.raises(ValueError, match="contributor cannot target itself"):
            ActivationContributor(
                node_id="x",
                self_id="self-1",
                target_node_id="same-id",
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id="same-id",
                source_kind="rule",
                weight=0.5,
                origin=ContributorOrigin.RULE,
                rationale="r",
            )

    @pytest.mark.parametrize("bad_weight", [-1.1, 1.1])
    def test_weight_out_of_range_raises(self, bad_weight: float) -> None:
        with pytest.raises(ValueError, match="contributor weight out of range"):
            ActivationContributor(
                node_id="x",
                self_id="self-1",
                target_node_id="target",
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id="source",
                source_kind="rule",
                weight=bad_weight,
                origin=ContributorOrigin.RULE,
                rationale="r",
            )

    def test_retrieval_origin_without_expiry_raises(self) -> None:
        with pytest.raises(ValueError, match="retrieval contributors must set expires_at"):
            ActivationContributor(
                node_id="x",
                self_id="self-1",
                target_node_id="target",
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id="source",
                source_kind="retrieval",
                weight=0.5,
                origin=ContributorOrigin.RETRIEVAL,
                rationale="r",
                expires_at=None,
            )

    def test_non_retrieval_origin_with_expiry_raises(self) -> None:
        with pytest.raises(ValueError, match="others must not"):
            ActivationContributor(
                node_id="x",
                self_id="self-1",
                target_node_id="target",
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id="source",
                source_kind="rule",
                weight=0.5,
                origin=ContributorOrigin.RULE,
                rationale="r",
                expires_at=_now(),
            )

    def test_retrieval_origin_with_expiry_succeeds(self) -> None:
        contributor = ActivationContributor(
            node_id="x",
            self_id="self-1",
            target_node_id="target",
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="source",
            source_kind="retrieval",
            weight=0.5,
            origin=ContributorOrigin.RETRIEVAL,
            rationale="r",
            expires_at=_now(),
        )
        assert contributor.expires_at is not None


# ------------------------------------------------------------------ guess_node_kind


class TestGuessNodeKind:
    @pytest.mark.parametrize(
        ("node_id", "expected"),
        [
            ("facet:openness.creativity", NodeKind.PERSONALITY_FACET),
            ("passion-1", NodeKind.PASSION),
            ("hobby-1", NodeKind.HOBBY),
            ("interest-1", NodeKind.INTEREST),
            ("pref-1", NodeKind.PREFERENCE),
            ("skill-1", NodeKind.SKILL),
            ("totally-unrecognized-id", NodeKind.PERSONALITY_FACET),
        ],
    )
    def test_guesses_correct_kind(self, node_id: str, expected: NodeKind) -> None:
        assert guess_node_kind(node_id) == expected
