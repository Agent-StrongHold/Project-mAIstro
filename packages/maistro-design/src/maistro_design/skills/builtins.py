"""Built-in design skills covering the five shipped modes (prototype/deck/template/design-system/image)."""

from maistro_design.types import (
    DesignSkill,
    DiscoveryField,
    OutputFormat,
    RenderSlot,
    SkillMode,
)

_CODE_OUTPUT_INSTRUCTIONS = """## Code Output Instructions

When the user requests React/TSX output:

1. Generate a single, self-contained `.tsx` file that exports a default React component.
2. Use functional components and React hooks (useState, useEffect). No class components.
3. Style exclusively with Tailwind utility classes. No CSS-in-JS, no CSS modules, no inline styles.
4. Import only:
   - `react` (React, useState, useEffect, etc.)
   - Tailwind CSS (already available in the rendering environment)
5. Do not make external API calls. Use local state for all interactivity.
6. Include a JSDoc comment at the top with the component's purpose and discovery response summary.
7. Ensure the component is accessible (ARIA labels, semantic HTML, keyboard navigation)."""

BUILTINS: list[DesignSkill] = [
    # ── Prototype ────────────────────────────────────────────────────────────
    DesignSkill(
        slug="login-flow",
        render_slot=RenderSlot.REFLOWABLE_WEB,
        name="Login Flow",
        mode=SkillMode.PROTOTYPE,
        description="Interactive login/auth flow prototype with form states and error handling.",
        featured=True,
        output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],
        tags=["auth", "forms", "ux"],
        system_prompt=f"""You are designing an interactive login/authentication flow prototype.

The user has provided a design system with colors, typography, and spacing tokens.
Follow the design guidelines strictly to ensure visual consistency.

{_CODE_OUTPUT_INSTRUCTIONS}""",
        discovery_form=[
            DiscoveryField(
                key="auth_methods",
                label="Authentication methods",
                description="Which auth methods should the flow support?",
                field_type="multiselect",
                options=("Email/Password", "Magic Link", "OAuth/SSO", "Passkey"),
                default="Email/Password",
            ),
            DiscoveryField(
                key="brand_tone",
                label="Brand tone",
                description="What tone should the UI convey?",
                field_type="select",
                options=("Professional", "Friendly", "Minimal", "Bold"),
                default="Professional",
            ),
        ],
    ),
    DesignSkill(
        slug="agent-browser",
        render_slot=RenderSlot.REFLOWABLE_WEB,
        name="Agent Browser UI",
        mode=SkillMode.PROTOTYPE,
        description="Browser-like UI shell for agentic web browsing workflows.",
        featured=True,
        output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],
        tags=["agent", "browser", "automation"],
        system_prompt=f"""You are designing a browser-like UI shell for agentic web automation.

The user has specified the primary action the agent will perform.
Build a realistic browser interface that supports this workflow.

{_CODE_OUTPUT_INSTRUCTIONS}""",
        discovery_form=[
            DiscoveryField(
                key="primary_action",
                label="Primary action",
                description="What is the main thing the agent does in the browser?",
                field_type="text",
                default="Research and summarize web pages",
            ),
        ],
    ),
    # ── Deck ─────────────────────────────────────────────────────────────────
    DesignSkill(
        slug="pitch-deck",
        render_slot=RenderSlot.DECK,
        name="Pitch Deck",
        mode=SkillMode.DECK,
        description="Investor-ready pitch deck with structured slides.",
        featured=True,
        output_formats=[
            OutputFormat.HTML,
            OutputFormat.MARKDOWN,
            OutputFormat.REACT_TSX,
            OutputFormat.PPTX,
            OutputFormat.PDF,
        ],
        system_prompt=f"""You are designing an investor-ready pitch deck.

Structure each slide clearly with:
- Strong headline (one key idea per slide)
- Supporting visuals or data
- Consistent visual hierarchy across all slides

{_CODE_OUTPUT_INSTRUCTIONS}

For REACT_TSX: Generate a self-contained React component that renders slides with useState-based navigation.
For PPTX/PDF: Structure as slide metadata and content suitable for conversion.""",
        tags=["pitch", "investor", "startup"],
        discovery_form=[
            DiscoveryField(
                key="company_name",
                label="Company / product name",
                description="Name of the company or product.",
                field_type="text",
            ),
            DiscoveryField(
                key="one_liner",
                label="One-liner",
                description="What does the company do in one sentence?",
                field_type="text",
            ),
            DiscoveryField(
                key="stage",
                label="Funding stage",
                description="Current funding stage.",
                field_type="select",
                options=("Pre-seed", "Seed", "Series A", "Series B+"),
                default="Seed",
            ),
            DiscoveryField(
                key="slide_count",
                label="Number of slides",
                description="How many slides?",
                field_type="select",
                options=("10", "12", "15", "20"),
                default="12",
            ),
        ],
    ),
    DesignSkill(
        slug="product-demo-deck",
        render_slot=RenderSlot.DECK,
        name="Product Demo Deck",
        mode=SkillMode.DECK,
        description="Feature walkthrough deck for customer demos and sales.",
        output_formats=[
            OutputFormat.HTML,
            OutputFormat.MARKDOWN,
            OutputFormat.REACT_TSX,
            OutputFormat.PPTX,
            OutputFormat.PDF,
        ],
        system_prompt=f"""You are designing a product demo walkthrough deck.

Each slide should:
- Focus on one feature or capability
- Include clear call-to-action for next steps
- Use real product screenshots or mockups where appropriate
- Build toward purchase decision

{_CODE_OUTPUT_INSTRUCTIONS}

For REACT_TSX: Generate a self-contained React component with slide navigation and interactive elements.
For PPTX/PDF: Structure for easy conversion to presentation format.""",
        tags=["demo", "sales", "product"],
        discovery_form=[
            DiscoveryField(
                key="product_name",
                label="Product name",
                description="Name of the product being demoed.",
                field_type="text",
            ),
            DiscoveryField(
                key="audience",
                label="Target audience",
                description="Who is this demo for?",
                field_type="select",
                options=("Enterprise buyers", "Developers", "Executives", "End users"),
                default="Enterprise buyers",
            ),
            DiscoveryField(
                key="key_features",
                label="Key features to highlight",
                description="Comma-separated list of the top 3-5 features.",
                field_type="text",
            ),
        ],
    ),
    # ── Template ─────────────────────────────────────────────────────────────
    DesignSkill(
        slug="landing-page",
        render_slot=RenderSlot.REFLOWABLE_WEB,
        name="Landing Page",
        mode=SkillMode.TEMPLATE,
        description="Conversion-optimised landing page with hero, features, and CTA sections.",
        featured=True,
        output_formats=[OutputFormat.HTML, OutputFormat.CSS, OutputFormat.REACT_TSX],
        system_prompt=f"""You are designing a conversion-optimized landing page.

Use the provided design system strictly. Follow best practices for:
- Clear hierarchy and visual flow
- Compelling headlines and value propositions
- Strong call-to-action placement
- Responsive layout across device sizes

{_CODE_OUTPUT_INSTRUCTIONS}""",
        tags=["landing", "marketing", "conversion"],
        discovery_form=[
            DiscoveryField(
                key="product_name",
                label="Product name",
                description="Name of the product or service.",
                field_type="text",
            ),
            DiscoveryField(
                key="headline",
                label="Hero headline",
                description="The main value proposition headline.",
                field_type="text",
            ),
            DiscoveryField(
                key="cta_text",
                label="CTA button text",
                description="Call-to-action button label.",
                field_type="text",
                default="Get started",
            ),
            DiscoveryField(
                key="section_count",
                label="Number of sections",
                description="How many content sections below the hero?",
                field_type="select",
                options=("3", "4", "5", "6"),
                default="4",
            ),
        ],
    ),
    DesignSkill(
        slug="email-template",
        render_slot=RenderSlot.REFLOWABLE_WEB,
        name="Email Template",
        mode=SkillMode.TEMPLATE,
        description="Responsive HTML email template for transactional or marketing sends.",
        output_formats=[OutputFormat.HTML, OutputFormat.REACT_TSX],
        tags=["email", "marketing", "responsive"],
        system_prompt=f"""You are designing a responsive email template.

Email constraints:
- Use inline styles (CSS will be inlined by mail clients)
- Support dark mode where possible
- Test on major email clients (Gmail, Outlook, Apple Mail)
- Clear single-column layout for mobile

{_CODE_OUTPUT_INSTRUCTIONS}""",
        discovery_form=[
            DiscoveryField(
                key="email_type",
                label="Email type",
                description="What kind of email is this?",
                field_type="select",
                options=("Welcome", "Transactional", "Newsletter", "Re-engagement"),
                default="Welcome",
            ),
            DiscoveryField(
                key="sender_name",
                label="Sender name",
                description="Who is sending this email?",
                field_type="text",
            ),
        ],
    ),
    # ── Design System ─────────────────────────────────────────────────────────
    DesignSkill(
        slug="brand-guidelines",
        name="Brand Guidelines",
        mode=SkillMode.DESIGN_SYSTEM,
        description="Generate a brand guidelines document from a design system.",
        featured=True,
        output_formats=[
            OutputFormat.HTML,
            OutputFormat.MARKDOWN,
            OutputFormat.REACT_TSX,
            OutputFormat.PDF,
            OutputFormat.DOCX,
            OutputFormat.PNG,
        ],
        system_prompt=f"""You are creating comprehensive brand guidelines documentation.

Cover:
- Brand purpose and mission
- Visual identity (logo, color palette, typography)
- Voice and tone guidelines
- Component library overview
- Usage dos and don'ts
- Real-world application examples

{_CODE_OUTPUT_INSTRUCTIONS}

For REACT_TSX: Generate an interactive brand showcase component with color swatches, typography samples, and component gallery.
For PDF: Create a printable guidelines document with clear sections and consistent formatting.
For DOCX: Generate an editable Word document suitable for distribution to stakeholders.
For PNG: Render visual style guide assets (color palette, typography scale).""",
        tags=["brand", "guidelines", "identity"],
        discovery_form=[
            DiscoveryField(
                key="brand_name",
                label="Brand name",
                description="Name of the brand.",
                field_type="text",
            ),
            DiscoveryField(
                key="brand_values",
                label="Brand values",
                description="3-5 core brand values or adjectives.",
                field_type="text",
                default="Innovative, Trustworthy, Human",
            ),
            DiscoveryField(
                key="sections",
                label="Sections to include",
                description="Which sections should the guidelines cover?",
                field_type="multiselect",
                options=("Logo", "Colors", "Typography", "Spacing", "Voice & Tone", "Components"),
                default="Logo",
            ),
        ],
    ),
    DesignSkill(
        slug="design-token-sheet",
        name="Design Token Sheet",
        mode=SkillMode.DESIGN_SYSTEM,
        description="Generate CSS custom properties and JSON token export for a design system.",
        output_formats=[
            OutputFormat.CSS,
            OutputFormat.JSON,
            OutputFormat.REACT_TSX,
            OutputFormat.PDF,
            OutputFormat.PNG,
        ],
        system_prompt=f"""You are generating a comprehensive design token reference sheet.

Include:
- Color tokens (with contrast ratios for accessibility)
- Typography tokens (font families, sizes, weights, line heights)
- Spacing tokens (margins, padding, gaps)
- Border radius tokens
- Shadow/elevation tokens
- Motion/animation tokens
- Z-index scale

{_CODE_OUTPUT_INSTRUCTIONS}

For REACT_TSX: Generate an interactive token browser component with searchable token list, live preview, and copy-to-clipboard functionality.
For CSS: Output CSS custom properties (variables) ready for production use.
For JSON: Export token definitions in standardized format (Design Tokens Community Group format).
For PDF: Create a visual token reference guide with swatches and specifications.
For PNG: Render visual token scale assets (color palette, typography samples, spacing grid).""",
        tags=["tokens", "css", "design-system"],
        discovery_form=[
            DiscoveryField(
                key="primary_color",
                label="Primary brand color",
                description="Hex color for the primary brand color.",
                field_type="color",
                default="#6366f1",
            ),
            DiscoveryField(
                key="font_family",
                label="Primary font family",
                description="CSS font-family stack for body text.",
                field_type="text",
                default="Inter, system-ui, sans-serif",
            ),
            DiscoveryField(
                key="border_radius",
                label="Base border radius",
                description="Base border-radius value (e.g. 4px, 8px, 0.5rem).",
                field_type="text",
                default="8px",
            ),
        ],
    ),
    # ── Image ─────────────────────────────────────────────────────────────────
    DesignSkill(
        slug="hero-image",
        name="Hero Image",
        mode=SkillMode.IMAGE,
        description="Generate a hero/banner image for marketing or product pages.",
        output_formats=[OutputFormat.PNG],
        tags=["image", "hero", "marketing"],
        discovery_form=[
            DiscoveryField(
                key="subject",
                label="Image subject",
                description="What should the image depict?",
                field_type="text",
            ),
            DiscoveryField(
                key="style",
                label="Visual style",
                description="What visual style should the image have?",
                field_type="select",
                options=("Photorealistic", "Illustrated", "Abstract", "Minimal", "3D render"),
                default="Photorealistic",
            ),
            DiscoveryField(
                key="aspect_ratio",
                label="Aspect ratio",
                description="Image dimensions.",
                field_type="select",
                options=("16:9", "4:3", "1:1", "3:2"),
                default="16:9",
            ),
        ],
    ),
    DesignSkill(
        slug="social-card",
        name="Social Card",
        mode=SkillMode.IMAGE,
        description="Open Graph / Twitter card image for social sharing.",
        output_formats=[OutputFormat.PNG],
        tags=["image", "social", "og"],
        discovery_form=[
            DiscoveryField(
                key="title",
                label="Card title",
                description="Main title text for the card.",
                field_type="text",
            ),
            DiscoveryField(
                key="subtitle",
                label="Subtitle / tagline",
                description="Supporting text below the title.",
                field_type="text",
                required=False,
            ),
        ],
    ),
]


def load_builtins(registry: object) -> None:
    """Register all built-in design skills into a registry."""
    for skill in BUILTINS:
        registry.register(skill)  # type: ignore[attr-defined]
