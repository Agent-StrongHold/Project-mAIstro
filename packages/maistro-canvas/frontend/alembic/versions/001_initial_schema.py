"""create_initial_schema

Revision ID: 001_initial
Revises:
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "creators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), unique=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), server_default=""),
        sa.Column("bio", sa.String(), server_default=""),
        sa.Column(
            "style_preferences",
            postgresql.JSONB(),
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), unique=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), server_default=""),
        sa.Column("source", sa.String(), server_default=""),
        sa.Column("source_id", sa.String(), server_default=""),
        sa.Column("email_consent", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "characters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            nullable=False,
        ),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("pronouns", sa.String(), server_default=""),
        sa.Column("nickname", sa.String(), server_default=""),
        sa.Column("photo_url", sa.String(), nullable=False),
        sa.Column("ai_features", postgresql.JSONB(), server_default="{}"),
        sa.Column("parent_overrides", postgresql.JSONB(), server_default="{}"),
        sa.Column("effective_features", postgresql.JSONB(), server_default="{}"),
        sa.Column("character_sheet_url", sa.String(), server_default=""),
        sa.Column("sheet_generated", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("book_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_characters_customer_id", "characters", ["customer_id"])

    op.create_table(
        "story_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), unique=True, nullable=False),
        sa.Column("display_title", sa.String(), nullable=False),
        sa.Column("title_pattern", sa.String(), nullable=False),
        sa.Column("age_range", postgresql.JSONB(), server_default="[]"),
        sa.Column("page_count", sa.Integer(), server_default="32"),
        sa.Column("illustration_style", sa.String(), server_default="full_color"),
        sa.Column("compatible_products", postgresql.JSONB(), server_default="[]"),
        sa.Column("required_variables", postgresql.JSONB(), server_default="[]"),
        sa.Column("optional_variables", postgresql.JSONB(), server_default="[]"),
        sa.Column("wizard_steps", postgresql.JSONB(), server_default="[]"),
        sa.Column("story_prompt", sa.String(), server_default=""),
        sa.Column("scene_structure", postgresql.JSONB(), server_default="[]"),
        sa.Column("description", sa.String(), server_default=""),
        sa.Column("themes", postgresql.JSONB(), server_default="[]"),
        sa.Column("etsy_tags", postgresql.JSONB(), server_default="[]"),
        sa.Column("preview_image_url", sa.String(), server_default=""),
        sa.Column("sample_book_url", sa.String(), server_default=""),
        sa.Column("max_characters", sa.Integer(), server_default="1"),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id")),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column(
            "parent_template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("story_templates.id")
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_story_templates_slug", "story_templates", ["slug"], unique=True)

    op.create_table(
        "product_formats",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("pod_package_id", sa.String(), nullable=False),
        sa.Column("price_usd", sa.Float(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("trim_size_in", postgresql.JSONB(), nullable=False),
        sa.Column("bleed_size_in", postgresql.JSONB(), nullable=False),
        sa.Column("binding", sa.String(), nullable=False),
        sa.Column("paper", sa.String(), nullable=False),
        sa.Column("color_mode", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default=""),
        sa.Column("weight_oz", sa.Float(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("characters.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("story_templates.id"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(), sa.ForeignKey("product_formats.id"), nullable=False),
        sa.Column("status", sa.String(), server_default="PENDING"),
        sa.Column("variables", postgresql.JSONB(), server_default="{}"),
        sa.Column("source", sa.String(), server_default=""),
        sa.Column("source_id", sa.String(), server_default=""),
        sa.Column("interior_pdf_url", sa.String(), server_default=""),
        sa.Column("cover_pdf_url", sa.String(), server_default=""),
        sa.Column("lulu_job_id", sa.String(), server_default=""),
        sa.Column("tracking_number", sa.String(), server_default=""),
        sa.Column("tracking_url", sa.String(), server_default=""),
        sa.Column("tracking_carrier", sa.String(), server_default=""),
        sa.Column("price_paid", sa.Float(), server_default="0"),
        sa.Column("print_cost", sa.Float(), server_default="0"),
        sa.Column("error_message", sa.String(), server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_template_id", "orders", ["template_id"])

    op.create_table(
        "generation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id")),
        sa.Column(
            "template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("story_templates.id")
        ),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id")),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("scene_number", sa.Integer()),
        sa.Column("page_number", sa.Integer()),
        sa.Column("iteration", sa.Integer(), server_default="1"),
        sa.Column("input_context", postgresql.JSONB(), server_default="{}"),
        sa.Column("ai_output", sa.String(), server_default=""),
        sa.Column("ai_output_url", sa.String(), server_default=""),
        sa.Column("ai_output_metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("verdict", sa.String(), server_default="pending"),
        sa.Column("edited_output", sa.String(), server_default=""),
        sa.Column("edited_output_url", sa.String(), server_default=""),
        sa.Column("edit_reason", sa.String(), server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_gen_attempts_order_id", "generation_attempts", ["order_id"])
    op.create_index(
        "ix_gen_attempts_creator_accepted",
        "generation_attempts",
        ["creator_id"],
        postgresql_where=sa.text("verdict IN ('accepted', 'edited')"),
    )
    op.create_index(
        "ix_gen_attempts_creator_rejected",
        "generation_attempts",
        ["creator_id"],
        postgresql_where=sa.text("verdict = 'rejected'"),
    )

    op.create_table(
        "page_layout_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("story_templates.id")
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id")),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True)),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("layout_state", postgresql.JSONB(), server_default="{}"),
        sa.Column("diff_from_previous", postgresql.JSONB(), server_default="{}"),
        sa.Column("affected_element_id", sa.String(), server_default=""),
        sa.Column("edit_action", sa.String(), server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "order_id", "page_number", "version"),
    )

    op.create_table(
        "feature_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "character_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("characters.id"),
            nullable=False,
        ),
        sa.Column("feature_name", sa.String(), nullable=False),
        sa.Column("ai_value", sa.String(), nullable=False),
        sa.Column("ai_confidence", sa.Float(), server_default="0"),
        sa.Column("corrected_value", sa.String(), nullable=False),
        sa.Column("photo_url", sa.String(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_feature_corrections_character_id", "feature_corrections", ["character_id"])
    op.create_index("ix_feature_corrections_feature_name", "feature_corrections", ["feature_name"])


def downgrade():
    op.drop_table("feature_corrections")
    op.drop_table("page_layout_versions")
    op.drop_table("generation_attempts")
    op.drop_table("orders")
    op.drop_table("product_formats")
    op.drop_table("story_templates")
    op.drop_table("characters")
    op.drop_table("customers")
    op.drop_table("creators")
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE")
