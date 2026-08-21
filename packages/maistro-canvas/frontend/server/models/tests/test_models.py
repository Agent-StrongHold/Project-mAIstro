from __future__ import annotations

import uuid

from server.models import (
    Character,
    Creator,
    Customer,
    FeatureCorrection,
    GenerationAttempt,
    Order,
    OrderStatus,
    PageLayoutVersion,
    ProductFormat,
    StoryTemplate,
    merge_features,
)
from server.templates.loader import load_all_templates, load_template, yaml_to_story_template
from server.templates.seed import PRODUCTS


class TestCreator:
    def test_create(self):
        c = Creator(email="test@example.com", name="Test")
        assert c.email == "test@example.com"
        assert c.is_active is True
        assert c.id is not None

    def test_default_fields(self):
        c = Creator(email="a@b.com", name="A")
        assert c.display_name == ""
        assert c.bio == ""
        assert c.style_preferences == {}


class TestCustomer:
    def test_create(self):
        c = Customer(email="buyer@example.com", name="Buyer")
        assert c.source == ""
        assert c.email_consent is False

    def test_source_tracking(self):
        c = Customer(email="e@e.com", name="E", source="etsy", source_id="12345")
        assert c.source == "etsy"
        assert c.source_id == "12345"


class TestCharacter:
    def test_create(self):
        cid = uuid.uuid4()
        ch = Character(
            customer_id=cid,
            name="Emma",
            age=5,
            photo_url="/uploads/photo.jpg",
        )
        assert ch.name == "Emma"
        assert ch.age == 5
        assert ch.sheet_generated is False
        assert ch.book_count == 0

    def test_creator_character(self):
        ch = Character(
            customer_id=uuid.uuid4(),
            creator_id=uuid.uuid4(),
            name="Sample Kid",
            age=6,
            photo_url="/uploads/sample.jpg",
        )
        assert ch.creator_id is not None

    def test_ai_features_immutable_pattern(self):
        ai = {"hair_color": "brown", "eye_color": "blue", "skin_tone": "fair"}
        ch = Character(
            customer_id=uuid.uuid4(),
            name="A",
            age=5,
            photo_url="/x.jpg",
            ai_features=ai,
        )
        assert ch.ai_features["hair_color"] == "brown"


class TestMergeFeatures:
    def test_no_overrides(self):
        ai = {"hair": "brown", "eyes": "blue"}
        assert merge_features(ai, {}) == {"hair": "brown", "eyes": "blue"}

    def test_override_single(self):
        ai = {"hair": "brown", "eyes": "blue"}
        assert merge_features(ai, {"hair": "black"}) == {"hair": "black", "eyes": "blue"}

    def test_override_multiple(self):
        ai = {"hair": "brown", "eyes": "blue", "skin": "fair"}
        overrides = {"hair": "black", "eyes": "green"}
        result = merge_features(ai, overrides)
        assert result == {"hair": "black", "eyes": "green", "skin": "fair"}

    def test_empty_ai(self):
        assert merge_features({}, {"hair": "black"}) == {"hair": "black"}

    def test_does_not_mutate_ai(self):
        ai = {"hair": "brown"}
        merge_features(ai, {"hair": "black"})
        assert ai["hair"] == "brown"


class TestStoryTemplate:
    def test_create(self):
        t = StoryTemplate(
            slug="test-story",
            display_title="Test Story",
            title_pattern="{child_name} and the Test",
        )
        assert t.slug == "test-story"
        assert t.page_count == 32
        assert t.illustration_style == "full_color"
        assert t.is_active is True

    def test_versioning(self):
        parent_id = uuid.uuid4()
        t = StoryTemplate(
            slug="test-v2",
            display_title="Test V2",
            title_pattern="Test",
            version=2,
            parent_template_id=parent_id,
        )
        assert t.version == 2
        assert t.parent_template_id == parent_id


class TestProductFormat:
    def test_create(self):
        p = ProductFormat(
            id="picture_book",
            name="Picture Book",
            pod_package_id="0750X0750.FC.PRE.PB.080CW444.MXX",
            price_usd=24.99,
            page_count=32,
            trim_size_in=[7.5, 7.5],
            bleed_size_in=[7.75, 7.75],
            binding="Perfect",
            paper="80# Coated White",
            color_mode="Full Color",
        )
        assert p.id == "picture_book"
        assert p.price_usd == 24.99
        assert p.is_active is True


class TestOrder:
    def test_create(self):
        o = Order(
            customer_id=uuid.uuid4(),
            character_id=uuid.uuid4(),
            template_id=uuid.uuid4(),
            product_id="picture_book",
        )
        assert o.status == "PENDING"
        assert o.variables == {}
        assert o.price_paid == 0

    def test_order_status_values(self):
        statuses = [s.value for s in OrderStatus]
        assert "PENDING" in statuses
        assert "FULFILLED" in statuses
        assert "FAILED" in statuses
        assert len(statuses) == 13


class TestGenerationAttempt:
    def test_create_with_order(self):
        ga = GenerationAttempt(
            order_id=uuid.uuid4(),
            stage="illustration",
            page_number=5,
        )
        assert ga.stage == "illustration"
        assert ga.verdict == "pending"
        assert ga.iteration == 1

    def test_create_template_authoring(self):
        ga = GenerationAttempt(
            stage="story_text",
            creator_id=uuid.uuid4(),
            input_context={"prompt": "test"},
            ai_output="Once upon a time...",
            verdict="edited",
            edited_output="Once upon a time, there lived...",
            edit_reason="needed more detail",
        )
        assert ga.order_id is None
        assert ga.verdict == "edited"

    def test_all_fields(self):
        ga = GenerationAttempt(
            stage="illustration",
            ai_output_metadata={"model": "flux-1-schnell", "latency_ms": 3200},
        )
        assert ga.ai_output_metadata["model"] == "flux-1-schnell"


class TestPageLayoutVersion:
    def test_create(self):
        pv = PageLayoutVersion(
            page_number=5,
            version=1,
            layout_state={"elements": [{"type": "text"}]},
        )
        assert pv.version == 1
        assert pv.edit_action == ""

    def test_with_diff(self):
        pv = PageLayoutVersion(
            page_number=5,
            version=3,
            layout_state={"elements": [{"x": 150}]},
            diff_from_previous={"element_id": "text_1", "changes": {"x": {"from": 100, "to": 150}}},
            affected_element_id="text_1",
            edit_action="move",
        )
        assert pv.edit_action == "move"
        assert pv.diff_from_previous["element_id"] == "text_1"


class TestFeatureCorrection:
    def test_create(self):
        fc = FeatureCorrection(
            character_id=uuid.uuid4(),
            feature_name="hair_color",
            ai_value="brown",
            ai_confidence=0.92,
            corrected_value="black",
            photo_url="/uploads/photo.jpg",
        )
        assert fc.feature_name == "hair_color"
        assert fc.corrected_value == "black"


class TestTemplateLoader:
    def test_load_dragon_template(self):
        data = load_template("dragons_new_friend.yaml")
        assert data["slug"] == "dragons-new-friend"
        assert data["page_count"] == 32
        assert len(data["required_variables"]) == 3
        assert data["required_variables"][0]["id"] == "child_name"
        assert len(data["scene_structure"]) == 16

    def test_load_all(self):
        templates = load_all_templates()
        assert len(templates) >= 1
        slugs = [t["slug"] for t in templates]
        assert "dragons-new-friend" in slugs

    def test_yaml_to_story_template(self):
        data = load_template("dragons_new_friend.yaml")
        fields = yaml_to_story_template(data)
        assert fields["slug"] == "dragons-new-friend"
        assert fields["display_title"] == "The Dragon's New Friend"
        assert "picture_book" in fields["compatible_products"]
        assert fields["max_characters"] == 1


class TestSeedData:
    def test_four_products(self):
        assert len(PRODUCTS) == 4
        ids = [p["id"] for p in PRODUCTS]
        assert "picture_book" in ids
        assert "coloring_premium" in ids

    def test_product_details(self):
        pb = next(p for p in PRODUCTS if p["id"] == "picture_book")
        assert pb["price_usd"] == 24.99
        assert pb["binding"] == "Perfect"
        assert pb["color_mode"] == "Full Color"

    def test_coloring_uses_uncoated(self):
        cs = next(p for p in PRODUCTS if p["id"] == "coloring_standard")
        assert "Uncoated" in cs["paper"]
        assert cs["color_mode"] == "Black & White"
