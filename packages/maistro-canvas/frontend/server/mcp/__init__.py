from .bg_removal import remove_background
from .character import (
    CharacterFeatures,
    CharacterSheet,
    analyze_photo,
    create_character_sheet_from_photo,
    generate_character_sheet,
    generate_reference_image,
)
from .character_normalizer import (
    HeadRegion,
    Normalization,
    Region,
    Silhouette,
    build_face_mask,
    detect_head_region,
    detect_silhouette,
    normalize_character,
)
from .feature_extractor import ExtractedFeatures, build_photo_derived_design, extract_features
from .illustration import (
    IllustrationResult,
    generate_coloring_book_illustrations,
    generate_picture_book_illustrations,
)
from .image_provider import generate_image
from .pdf_composer import compose_cover, compose_interior
from .pipeline import OrderSpec, PipelineResult, run_pipeline
from .products import PRODUCTS, ProductSpec, get_product, list_products
from .refinement import RefinementResult, StyleToken, refine_scene
from .story import Story, StoryPage, generate_story, validate_story

__all__ = [
    "PRODUCTS",
    "CharacterFeatures",
    "CharacterSheet",
    "ExtractedFeatures",
    "HeadRegion",
    "IllustrationResult",
    "Normalization",
    "OrderSpec",
    "PipelineResult",
    "ProductSpec",
    "RefinementResult",
    "Region",
    "Silhouette",
    "Story",
    "StoryPage",
    "StyleToken",
    "analyze_photo",
    "build_face_mask",
    "build_photo_derived_design",
    "compose_cover",
    "compose_interior",
    "create_character_sheet_from_photo",
    "detect_head_region",
    "detect_silhouette",
    "extract_features",
    "generate_character_sheet",
    "generate_coloring_book_illustrations",
    "generate_image",
    "generate_picture_book_illustrations",
    "generate_reference_image",
    "generate_story",
    "get_product",
    "list_products",
    "normalize_character",
    "refine_scene",
    "remove_background",
    "run_pipeline",
    "validate_story",
]
