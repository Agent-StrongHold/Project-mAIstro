from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductSpec:
    id: str
    name: str
    description: str
    pod_package_id: str
    retail_price_usd: float
    page_count: int
    trim_width_in: float
    trim_height_in: float
    bleed_in: float = 0.125
    safety_margin_in: float = 0.5
    gutter_margin_in: float = 0.125
    interior_color: str = "Full Color"
    print_quality: str = "Premium"
    binding: str = "Perfect"
    paper: str = "80# Coated White"
    cover_finish: str = "Matte"
    art_styles: tuple[str, ...] = ("bold_simple", "detailed_ornate")
    min_pages: int = 32
    max_pages: int = 800
    base_price_usd: float = 0.0
    per_page_price_usd: float = 0.0
    interest_themes: tuple[str, ...] = ()
    interest_pages_per_theme: int = 0

    @property
    def trim_width_pt(self) -> float:
        return self.trim_width_in * 72

    @property
    def trim_height_pt(self) -> float:
        return self.trim_height_in * 72

    @property
    def bleed_width_pt(self) -> float:
        return (self.trim_width_in + 2 * self.bleed_in) * 72

    @property
    def bleed_height_pt(self) -> float:
        return (self.trim_height_in + 2 * self.bleed_in) * 72

    @property
    def spine_width_in(self) -> float:
        return (self.page_count / 444) + 0.06

    @property
    def spine_width_pt(self) -> float:
        return self.spine_width_in * 72

    @property
    def cover_width_pt(self) -> float:
        return (
            self.bleed_in
            + self.trim_width_in
            + self.spine_width_in
            + self.trim_width_in
            + self.bleed_in
        ) * 72

    @property
    def cover_height_pt(self) -> float:
        return (self.bleed_in + self.trim_height_in + self.bleed_in) * 72

    def print_cost(self, quantity: int = 1) -> float:
        unit = self.base_price_usd + (self.page_count * self.per_page_price_usd)
        return round(unit * quantity, 2)

    def margin(self, retail: float | None = None, quantity: int = 1) -> float:
        r = retail or self.retail_price_usd
        return round(r - self.print_cost(quantity), 2)


INTEREST_THEME_MENU: dict[str, tuple[str, ...]] = {
    "Animals": (
        "Dinosaurs",
        "Ocean Life",
        "Horses & Unicorns",
        "Safari",
        "Bugs & Butterflies",
        "Pets",
    ),
    "Fantasy": (
        "Dragons",
        "Fairies & Elves",
        "Mermaids",
        "Magic & Wizards",
        "Castles & Knights",
        "Superheroes",
    ),
    "Adventure": (
        "Space & Astronauts",
        "Pirates",
        "Jungle Exploration",
        "Construction Vehicles",
        "Trains",
        "Robots",
    ),
    "Nature": (
        "Flowers & Gardens",
        "Forest Animals",
        "Weather & Seasons",
        "Farm",
        "Mountains",
        "Rainbows",
    ),
    "Activities": (
        "Sports",
        "Dance & Music",
        "Cookoking & Baking",
        "Science Lab",
        "Art & Painting",
        "Camping",
    ),
    "Culture": (
        "World Landmarks",
        "Mythology",
        "Holidays & Celebrations",
        "Under the Sea",
        "Dinosaur World",
        "Enchanted Forest",
    ),
}

ALL_THEME_OPTIONS: list[str] = []
for _cat, _themes in INTEREST_THEME_MENU.items():
    ALL_THEME_OPTIONS.extend(_themes)


COLORING_INTEREST_THEMES = tuple(ALL_THEME_OPTIONS)


PRODUCTS: dict[str, ProductSpec] = {
    "picture-book-7.5": ProductSpec(
        id="picture-book-7.5",
        name="Picture Book (Small Square)",
        description="32-page full-color illustrated storybook. Your child is the main character.",
        pod_package_id="0750X0750.FC.PRE.PB.080CW444.MXX",
        retail_price_usd=24.99,
        page_count=32,
        trim_width_in=7.5,
        trim_height_in=7.5,
        interior_color="Full Color",
        print_quality="Premium",
        binding="Perfect",
        paper="80# Coated White",
        cover_finish="Matte",
        min_pages=32,
        max_pages=800,
        base_price_usd=2.07,
        per_page_price_usd=0.2065,
    ),
    "picture-book-9x7": ProductSpec(
        id="picture-book-9x7",
        name="Picture Book (Landscape)",
        description="32-page full-color illustrated storybook in classic landscape format.",
        pod_package_id="0900X0700.FC.PRE.PB.080CW444.MXX",
        retail_price_usd=24.99,
        page_count=32,
        trim_width_in=9.0,
        trim_height_in=7.0,
        interior_color="Full Color",
        print_quality="Premium",
        binding="Perfect",
        paper="80# Coated White",
        cover_finish="Matte",
        min_pages=32,
        max_pages=800,
        base_price_usd=2.07,
        per_page_price_usd=0.2065,
    ),
    "coloring-standard": ProductSpec(
        id="coloring-standard",
        name="Coloring Book (Standard)",
        description="32-page black & white coloring book. Perfect bind.",
        pod_package_id="0850X1100.BW.STD.PB.060UW444.MXX",
        retail_price_usd=9.99,
        page_count=32,
        trim_width_in=8.5,
        trim_height_in=11.0,
        interior_color="Black & White",
        print_quality="Standard",
        binding="Perfect",
        paper="60# Uncoated White",
        cover_finish="Matte",
        art_styles=("bold_simple", "detailed_ornate"),
        min_pages=32,
        max_pages=800,
        base_price_usd=2.07,
        per_page_price_usd=0.037,
        interest_themes=COLORING_INTEREST_THEMES,
        interest_pages_per_theme=0,
    ),
    "coloring-premium": ProductSpec(
        id="coloring-premium",
        name="Coloring Book (Premium)",
        description=(
            "150-page black & white coil-bound coloring book. "
            "Lays flat. 75 character pages + 75 themed pages."
        ),
        pod_package_id="0850X1100.BW.STD.CO.060UW444.MXX",
        retail_price_usd=25.99,
        page_count=150,
        trim_width_in=8.5,
        trim_height_in=11.0,
        interior_color="Black & White",
        print_quality="Standard",
        binding="Coil",
        paper="60# Uncoated White",
        cover_finish="Matte",
        art_styles=("bold_simple", "detailed_ornate"),
        min_pages=2,
        max_pages=470,
        base_price_usd=6.68,
        per_page_price_usd=0.037,
        interest_themes=COLORING_INTEREST_THEMES,
        interest_pages_per_theme=25,
    ),
}


def get_product(product_id: str) -> ProductSpec:
    if product_id not in PRODUCTS:
        raise KeyError(f"Unknown product: {product_id}. Available: {list(PRODUCTS.keys())}")
    return PRODUCTS[product_id]


def list_products() -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "retail_price_usd": p.retail_price_usd,
            "print_cost_usd": p.print_cost(),
            "margin_usd": p.margin(),
            "margin_pct": round(p.margin() / p.retail_price_usd * 100, 1),
            "page_count": p.page_count,
            "trim_size": f"{p.trim_width_in}x{p.trim_height_in}",
            "binding": p.binding,
            "paper": p.paper,
        }
        for p in PRODUCTS.values()
    ]
