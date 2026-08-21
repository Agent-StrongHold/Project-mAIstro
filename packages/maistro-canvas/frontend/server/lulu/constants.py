LULU_API_BASE = "https://api.lulu.com"
LULU_SANDBOX_BASE = "https://api.sandbox.lulu.com"
LULU_AUTH_URL = "/auth/realms/glasstree/protocol/openid-connect/token"
LULU_PRINT_JOBS_URL = "/print-jobs/"
LULU_SHIPPING_OPTIONS_URL = "/shipping-options/"
LULU_COST_CALCULATIONS_URL = "/print-job-cost-calculations/"
LULU_FILE_UPLOAD_URL = "/file-upload/"

# Dotted SKU format required after March 31, 2026.
# Legacy 27-char format deprecated, removal Feb 1, 2027.
# Format: [Trim].[Ink].[Quality].[Binding].[Paper].[Finish]
# Pricing: cost = base_price + (page_count * per_page_price)
# Source: lulu-print-api-spec-sheet.xlsx (3278 SKUs, updated 3/2026)

PICTURE_BOOK_FORMATS = {
    "0750X0750.FC.STD.PB.060UW444.MXX": {
        "name": "7.5x7.5 Small Square, standard color, perfect bind, matte",
        "trim_size": "7.5x7.5",
        "trim_size_mm": (191, 191),
        "trim_size_in": (7.5, 7.5),
        "bleed_size_in": (7.75, 7.75),
        "interior_color": "Full Color",
        "print_quality": "Standard",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.054,
    },
    "0750X0750.FC.PRE.PB.060UW444.MXX": {
        "name": "7.5x7.5 Small Square, premium color, perfect bind, matte",
        "trim_size": "7.5x7.5",
        "trim_size_mm": (191, 191),
        "trim_size_in": (7.5, 7.5),
        "bleed_size_in": (7.75, 7.75),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.193,
    },
    "0750X0750.FC.PRE.PB.080CW444.MXX": {
        "name": "7.5x7.5 Small Square, premium color, 80# coated, perfect bind, matte",
        "trim_size": "7.5x7.5",
        "trim_size_mm": (191, 191),
        "trim_size_in": (7.5, 7.5),
        "bleed_size_in": (7.75, 7.75),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "80# Coated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.2065,
    },
    "0750X0750.FC.STD.CW.060UW444.MXX": {
        "name": "7.5x7.5 Small Square, standard color, case wrap (hardcover), matte",
        "trim_size": "7.5x7.5",
        "trim_size_mm": (191, 191),
        "trim_size_in": (7.5, 7.5),
        "bleed_size_in": (7.75, 7.75),
        "interior_color": "Full Color",
        "print_quality": "Standard",
        "binding": "Case Wrap",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 24,
        "max_pages": 800,
        "base_price_usd": 10.55,
        "per_page_price_usd": 0.054,
    },
    "0750X0750.FC.PRE.CW.060UW444.MXX": {
        "name": "7.5x7.5 Small Square, premium color, case wrap (hardcover), matte",
        "trim_size": "7.5x7.5",
        "trim_size_mm": (191, 191),
        "trim_size_in": (7.5, 7.5),
        "bleed_size_in": (7.75, 7.75),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Case Wrap",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 24,
        "max_pages": 800,
        "base_price_usd": 10.55,
        "per_page_price_usd": 0.193,
    },
    "0850X0850.FC.STD.PB.060UW444.MXX": {
        "name": "8.5x8.5 Square, standard color, perfect bind, matte",
        "trim_size": "8.5x8.5",
        "trim_size_mm": (216, 216),
        "trim_size_in": (8.5, 8.5),
        "bleed_size_in": (8.75, 8.75),
        "interior_color": "Full Color",
        "print_quality": "Standard",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.054,
    },
    "0850X0850.FC.PRE.PB.060UW444.MXX": {
        "name": "8.5x8.5 Square, premium color, perfect bind, matte",
        "trim_size": "8.5x8.5",
        "trim_size_mm": (216, 216),
        "trim_size_in": (8.5, 8.5),
        "bleed_size_in": (8.75, 8.75),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.193,
    },
    "0850X0850.FC.PRE.PB.080CW444.MXX": {
        "name": "8.5x8.5 Square, premium color, 80# coated, perfect bind, matte",
        "trim_size": "8.5x8.5",
        "trim_size_mm": (216, 216),
        "trim_size_in": (8.5, 8.5),
        "bleed_size_in": (8.75, 8.75),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "80# Coated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.2065,
    },
    "0663X1025.FC.PRE.PB.070CW460.MIX": {
        "name": "6.63x10.25 Comic, premium color, 70# coated, perfect bind, matte",
        "trim_size": "6.63x10.25",
        "trim_size_mm": (168, 260),
        "trim_size_in": (6.63, 10.25),
        "bleed_size_in": (6.88, 10.5),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "70# Coated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.37,
        "per_page_price_usd": 0.2065,
    },
    "0850X1100.FC.STD.PB.060UW444.MXX": {
        "name": "8.5x11 US Letter, standard color, perfect bind, matte",
        "trim_size": "8.5x11",
        "trim_size_mm": (216, 279),
        "trim_size_in": (8.5, 11.0),
        "bleed_size_in": (8.75, 11.25),
        "interior_color": "Full Color",
        "print_quality": "Standard",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.054,
    },
    "0850X1100.FC.PRE.PB.060UW444.MXX": {
        "name": "8.5x11 US Letter, premium color, perfect bind, matte",
        "trim_size": "8.5x11",
        "trim_size_mm": (216, 279),
        "trim_size_in": (8.5, 11.0),
        "bleed_size_in": (8.75, 11.25),
        "interior_color": "Full Color",
        "print_quality": "Premium",
        "binding": "Perfect",
        "paper": "60# Uncoated White",
        "cover_finish": "Matte",
        "min_pages": 32,
        "max_pages": 800,
        "base_price_usd": 2.07,
        "per_page_price_usd": 0.193,
    },
}

# Backwards compat — maps old legacy IDs to dotted format
LEGACY_TO_DOTTED = {
    "0850X0850FCSTDPB060UW444GXX": "0850X0850.FC.STD.PB.060UW444.MXX",
    "0850X0850FCSTDPB080UW444GXX": "0850X0850.FC.STD.PB.080CW444.MXX",
    "0850X1100FCSTDPB060UW444GXX": "0850X1100.FC.STD.PB.060UW444.MXX",
    "0800X1000FCSTDPB060UW444GXX": "0850X1100.FC.STD.PB.060UW444.MXX",
}

POD_PACKAGE_IDS = PICTURE_BOOK_FORMATS

DEFAULT_PACKAGE = "0750X0750.FC.STD.PB.060UW444.MXX"


# Spine width: (pages / 444) + 0.06 inches for perfect bind
def _spine_width(pages: int) -> float:
    return (pages / 444) + 0.06


SPINE_WIDTH_FORMULA_PAPERBACK = _spine_width

SHIPPING_LEVELS = {
    "GROUND_HD": "FedEx Home (5 business days, residential)",
    "GROUND_BUS": "FedEx Ground (5 business days, business)",
    "EXPEDITED": "FedEx 2 Day",
    "EXPRESS": "FedEx Standard Overnight",
    "PRIORITY_MAIL": "USPS Priority Mail (5 business days)",
    "MAIL": "FedEx Smart Post (economy, 7-8 days)",
    "GROUND": "Ground (international)",
}

BLEED_MARGIN_IN = 0.125
SAFETY_MARGIN_IN = 0.5
GUTTER_MARGIN_IN = 0.125  # for 61-150 pages; 0 for <60, 0.5 for 151-400
