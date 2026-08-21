from __future__ import annotations

from ..models.product_format import ProductFormat
from ..models.story_template import StoryTemplate
from .loader import load_all_templates, yaml_to_story_template

PRODUCTS = [
    {
        "id": "picture_book",
        "name": "Picture Book",
        "pod_package_id": "0750X0750.FC.PRE.PB.080CW444.MXX",
        "price_usd": 24.99,
        "page_count": 32,
        "trim_size_in": [7.5, 7.5],
        "bleed_size_in": [7.75, 7.75],
        "binding": "Perfect",
        "paper": "80# Coated White",
        "color_mode": "Full Color",
        "description": "32-page full-color picture book, 7.5x7.5 inches",
        "weight_oz": 7.0,
    },
    {
        "id": "picture_book_landscape",
        "name": "Picture Book (Landscape)",
        "pod_package_id": "0900X0700.FC.PRE.PB.080CW444.MXX",
        "price_usd": 24.99,
        "page_count": 32,
        "trim_size_in": [9.0, 7.0],
        "bleed_size_in": [9.25, 7.25],
        "binding": "Perfect",
        "paper": "80# Coated White",
        "color_mode": "Full Color",
        "description": "32-page full-color picture book, 9x7 inches landscape",
        "weight_oz": 7.0,
    },
    {
        "id": "coloring_standard",
        "name": "Coloring Standard",
        "pod_package_id": "0850X1100.BW.STD.PB.060UW444.MXX",
        "price_usd": 9.99,
        "page_count": 32,
        "trim_size_in": [8.5, 11.0],
        "bleed_size_in": [8.75, 11.25],
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "color_mode": "Black & White",
        "description": "32-page black & white coloring book, 8.5x11 inches",
        "weight_oz": 5.0,
    },
    {
        "id": "coloring_premium",
        "name": "Coloring Premium",
        "pod_package_id": "0850X1100.BW.STD.CO.060UW444.MXX",
        "price_usd": 25.99,
        "page_count": 150,
        "trim_size_in": [8.5, 11.0],
        "bleed_size_in": [8.75, 11.25],
        "binding": "Coil",
        "paper": "60# Uncoated White",
        "color_mode": "Black & White",
        "description": "150-page black & white coloring book, 8.5x11 inches, spiral bound",
        "weight_oz": 14.0,
    },
]


def seed_products(session) -> int:
    count = 0
    for data in PRODUCTS:
        existing = session.get(ProductFormat, data["id"])
        if existing:
            continue
        product = ProductFormat(**data)
        session.add(product)
        count += 1
    session.commit()
    return count


def seed_templates(session) -> int:
    count = 0
    for raw in load_all_templates():
        existing = session.exec(
            StoryTemplate.__table__.select().where(StoryTemplate.slug == raw["slug"])
        ).first()
        if existing:
            continue
        fields = yaml_to_story_template(raw)
        template = StoryTemplate(**fields)
        session.add(template)
        count += 1
    session.commit()
    return count


def seed_all(session) -> dict:
    products = seed_products(session)
    templates = seed_templates(session)
    return {"products": products, "templates": templates}
