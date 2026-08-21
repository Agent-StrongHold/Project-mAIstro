# Canvas Studio POC — Phased Book Generation Pipeline
#
# Standalone React app at canvas-studio-poc/ for generating illustrated
# children's books using Azure GPT-image-1.5 (primary) + GPT-image-2 (fallback).
#
# NOT the Stronghold canvas module (specs/canvas-studio.yaml).
# This is a consumer-facing proof of concept for the phased approval pipeline.
#
# Architecture: BookWizard (4 steps) → BookWorkspace (5-step pipeline) → Export
# Persistence: Postgres via Express API, auto-save debounced 3s
# Image gen: Azure direct (browser→Azure), no backend proxy needed
# LLM text: LiteLLM at :4000 via Vite proxy

issue_number: POC-001
title: "Canvas Studio POC — phased book generation with AI image pipeline"
status: active
complexity: L

components:
  - name: BookWizard
    path: src/components/BookWizard.jsx
    description: "4-step wizard: Characters (multi-char + photo upload) → Style → Story → Book Details"

  - name: BookWorkspace
    path: src/components/BookWorkspace.jsx
    description: "5-step phased pipeline: Story → Style → Character → Storyboard → Pages"

  - name: CharacterStudio
    path: src/components/CharacterStudio.jsx
    description: "Standalone character builder — create characters independently from stories"

  - name: renderingPipeline
    path: src/lib/renderingPipeline.js
    description: "Azure image generation + edit (multipart/form-data), Gemini fallback, compositing"

  - name: refinementPass
    path: src/lib/refinementPass.js
    description: "AI-assisted polish via /images/edits, client-side canvas fallback"

  - name: templateEngine
    path: src/lib/templateEngine.js
    description: "Prompt builders, pose library, composition zones, style tokens"

  - name: storyApi
    path: src/lib/storyApi.js
    description: "LLM story decomposition via LiteLLM proxy"

  - name: persistence
    path: src/lib/persistence.js
    description: "Save/load books to Postgres via Express API"

  - name: templates
    path: src/lib/templates.js
    description: "Character template CRUD via Express API"

  - name: Express API
    path: server.js
    description: "REST API: /api/books, /api/templates, /api/characters → Postgres :5440"

  - name: CharacterNormalizer
    path: src/lib/characterNormalizer.js
    description: "Silhouette detection, head region, face mask for identity protection"

files_touched:
  - canvas-studio-poc/src/App.jsx
  - canvas-studio-poc/src/components/BookWizard.jsx
  - canvas-studio-poc/src/components/BookWorkspace.jsx
  - canvas-studio-poc/src/lib/renderingPipeline.js
  - canvas-studio-poc/src/lib/refinementPass.js
  - canvas-studio-poc/src/lib/templateEngine.js
  - canvas-studio-poc/src/lib/storyApi.js
  - canvas-studio-poc/src/lib/persistence.js
  - canvas-studio-poc/src/lib/templates.js
  - canvas-studio-poc/src/lib/characterNormalizer.js
  - canvas-studio-poc/server.js
  - canvas-studio-poc/vite.config.js


# ─────────────────────────────────────────────────────────────────────
# ACCEPTANCE CRITERIA
# ─────────────────────────────────────────────────────────────────────

acceptance_criteria:

  # ── Deployment chain ─────────────────────────────────────────────────
  - "azureImageGen tries deployments in order: gpt-image-1-5 (API 2025-04-01-preview), then gpt-image-2-1 (API 2025-03-01-preview); returns first success"
  - "azureImageEdit accepts a single data URL or array of data URLs; sends all as image[] via multipart/form-data"
  - "input_fidelity parameter maps float >= 0.7 to 'high', < 0.7 to 'low' (Azure only accepts these two string values)"
  - "All generation calls have 180s timeout with AbortController; timeout throws AbortError"

  # ── Image generation ─────────────────────────────────────────────────
  - "generateImage(prompt, size, quality) tries Azure first, then Gemini, then returns placeholder gradient"
  - "renderLayerDraft generates at 512x512 quality='low'"
  - "renderLayerFinal generates at 1024x1024 quality='medium'"
  - "renderStyleSample generates at 1024x1024 quality='medium' using style_token properties"
  - "renderStoryboardOverview generates at 1024x1024 quality='medium' showing all scenes in grid"

  # ── Character generation with reference photos ───────────────────────
  - "renderCharacterReferences accepts referenceImages: array of data URLs from uploaded photos"
  - "When referenceImages provided, calls azureImageEdit with all photos as image[] + character prompt + input_fidelity='high'"
  - "Prompt instructs model to preserve exact facial features, hair, skin tone from reference photos"
  - "Falls back to text-only generateImage if edit call fails for any reason"
  - "Character card in BookWizard accepts up to 5 reference photos via file input"
  - "Photos stored as base64 data URLs in character.reference_photos array"

  # ── Refinement pass ──────────────────────────────────────────────────
  - "refineScene tries azureImageEdit with composite image + refinement prompt + input_fidelity='high' first"
  - "If AI edit fails, falls back to client-side canvas: edge softening + palette unification + contrast normalization + face protection"
  - "Face protection: where face_mask is white, original composite pixels override refined pixels"
  - "Returns { composite, composite_original, refined: true, refinement_method: 'ai_edit'|'canvas_fallback' }"

  # ── Compositing ──────────────────────────────────────────────────────
  - "compositeScene renders layers sorted by z_index (ascending = back-to-front)"
  - "Background layers (slot='full_page') stretch to fill canvas dimensions"
  - "Character layers with pose.geo use anchor-snap compositing (ground_contact, seat_contact)"
  - "Generic slotted layers scale to fit slot bounds maintaining aspect ratio"

  # ── Phased pipeline ──────────────────────────────────────────────────
  - "Step 1 (Story): decomposeBook via LLM → editable scene list; Continue advances without regenerating"
  - "Step 2 (Style): Generate New adds to styleVersions[] array; VersionPicker selects active version"
  - "Step 3 (Character): Generate New adds to charVersions[]; reference photos from main character passed to edit call"
  - "Step 4 (Storyboard): Generate New adds to sbVersions[]; Start Pages advances to Step 5"
  - "Step 5 (Pages): Per-page layer workflow — Background/Character/Props as separate layers"
  - "Each layer has Retry (regen), Edit (change prompt + regen), HQ (upgrade to final quality) buttons"
  - "Layer version history: Retry/Edit/HQ push old image to history[]; clickable thumbnails to revert"
  - "Approve & Next runs refinement if all layers final, then generates next page drafts"
  - "Step navigation: any previously-visited step is clickable; no data lost on navigation"

  # ── Persistence ──────────────────────────────────────────────────────
  - "Auto-save debounced 3 seconds after last state change"
  - "On load: auto-resume if 1 saved book, show picker if multiple"
  - "books table: key TEXT PK, data JSONB; templates table: key TEXT PK, data JSONB; characters table: key TEXT PK, data JSONB"
  - "Express API on :5174 with /api/books, /api/templates, /api/characters CRUD"
  - "Vite dev server proxies /api → :5174 and /litellm → :4000"

  # ── Mobile responsive ────────────────────────────────────────────────
  - "Layout collapses to single column on < 768px viewport width"


# ─────────────────────────────────────────────────────────────────────
# GHERKIN ACCEPTANCE SCENARIOS
# ─────────────────────────────────────────────────────────────────────

gherkin_scenarios: |

  Feature: Azure deployment chain
    Scenario: GPT-image-1.5 succeeds on first try
      Given Azure deployment gpt-image-1-5 is healthy
      When azureImageGen is called with any prompt
      Then exactly 1 request is made to gpt-image-1-5 with api-version=2025-04-01-preview
      And the result is a data:image/png;base64,... URL

    Scenario: GPT-image-1.5 fails, falls back to GPT-image-2
      Given Azure deployment gpt-image-1-5 returns 500
      And gpt-image-2-1 is healthy
      When azureImageGen is called
      Then a request is made to gpt-image-1-5 (fails)
      Then a request is made to gpt-image-2-1 with api-version=2025-03-01-preview (succeeds)

    Scenario: Both deployments fail, falls back to Gemini
      Given both Azure deployments return errors
      And Gemini API key is configured
      When azureImageGen is called
      Then Gemini generateContent is called
      And the result is a data URL

    Scenario: All providers fail, returns placeholder
      Given Azure and Gemini are unavailable
      When generateImage is called with prompt "a cat"
      Then a gradient placeholder is returned
      And the placeholder canvas text contains "a cat" (truncated to 40 chars)

    Scenario: Generation times out after 180 seconds
      Given Azure takes >180s to respond
      When azureImageGen is called
      Then an AbortError is thrown

  Feature: Image edit with reference photos
    Scenario: Single reference photo produces style-guided character
      Given a valid PNG data URL as referenceImages
      When azureImageEdit is called with inputFidelity=0.9
      Then a multipart/form-data request is sent to /images/edits
      And the form contains image[] field with the decoded blob
      And input_fidelity is "high" (string, not float)

    Scenario: Multiple reference photos sent as image[] array
      Given 3 valid PNG data URLs as referenceImages
      When azureImageEdit is called
      Then the form contains 3 image[] entries
      And the prompt instructs face preservation

    Scenario: input_fidelity below 0.7 sends "low"
      When azureImageEdit is called with inputFidelity=0.5
      Then input_fidelity form field is "low"

    Scenario: input_fidelity above 0.7 sends "high"
      When azureImageEdit is called with inputFidelity=0.8
      Then input_fidelity form field is "high"

    Scenario: Edit endpoint returns 404 on gpt-image-1-5, tries gpt-image-2-1
      Given gpt-image-1-5 /images/edits returns 404
      And gpt-image-2-1 /images/edits succeeds
      When azureImageEdit is called
      Then gpt-image-1-5 is tried first (skipped on 404)
      Then gpt-image-2-1 succeeds and returns the image

    Scenario: Edit endpoint returns 429 on all deployments
      Given all deployments return 429
      When azureImageEdit is called
      Then an error is thrown containing "All Azure edit deployments failed"

  Feature: Character sheet generation with reference photos
    Scenario: Generate with 3 reference photos
      Given BookWizard has a main character with 3 reference_photos
      And style sample is approved at step 2
      When genChar is called in BookWorkspace
      Then renderCharacterReferences receives [photo1, photo2, photo3, styleSample]
      And azureImageEdit is called with all 4 images
      And the prompt contains "Preserve the child's exact facial features"

    Scenario: Generate with no reference photos
      Given BookWizard has a main character with 0 reference_photos
      And style sample is approved
      When genChar is called
      Then renderCharacterReferences receives [styleSample]
      And azureImageEdit is called with 1 image (style only)

    Scenario: Generate with no photos and no style sample
      Given no reference_photos and no style sample
      When genChar is called
      Then generateImage is called (text-to-image, no edit)

    Scenario: Photo-guided edit fails, falls back to text-only
      Given azureImageEdit throws "All Azure edit deployments failed"
      When genChar is called with reference photos
      Then generateImage is called as fallback
      And the log shows "Photo-guided generation failed (...), trying text-only..."

  Feature: Photo upload in BookWizard
    Scenario: Upload 3 photos for a character
      Given character card is expanded
      When user selects 3 PNG files via file input
      Then character.reference_photos contains 3 base64 data URLs
      And 3 thumbnails are displayed in the photo grid

    Scenario: Upload exceeds 5 photo limit
      Given character already has 3 reference_photos
      When user selects 4 more files
      Then only 2 are processed (capped at 5)
      And character.reference_photos has 5 entries

    Scenario: Remove a photo
      Given character has 3 reference_photos
      When user clicks 'x' on photo index 1
      Then character.reference_photos has 2 entries
      And the removed photo is gone from the grid

    Scenario: Photo thumbnail shown in character avatar
      Given character has reference_photos
      Then the character card avatar shows the first photo instead of the number

  Feature: Layer version history
    Scenario: Retry pushes old image to history
      Given a page layer has image_url=ImgA and no history
      When retryLayer is called
      Then the new image becomes layer.image_url
      And ImgA is pushed to layer.history
      And layer.historyIdx == 0

    Scenario: Three retries create three history entries
      Given layer has no history
      When retryLayer is called 3 times producing ImgA, ImgB, ImgC
      Then layer.history == [ImgA, ImgB]
      And layer.image_url == ImgC
      And 3 version thumbnails are shown (2 history + 1 current)

    Scenario: Revert to history version
      Given layer.history == [ImgA, ImgB] and image_url == ImgC
      When user clicks thumbnail for history index 0 (ImgA)
      Then layer.image_url == ImgA
      And history is preserved (not modified)
      And the composite is recalculated

    Scenario: Upgrade preserves history
      Given layer has history=[ImgA] and image_url=ImgB (draft)
      When upgradeLayer is called producing ImgC (final)
      Then layer.history == [ImgA, ImgB]
      And layer.image_url == ImgC
      And layer.quality == "final"

  Feature: Refinement pass
    Scenario: AI edit succeeds on first try
      Given a composite image exists and azureImageEdit returns a refined image
      When refineScene is called
      Then refinement_method == "ai_edit"
      And composite_original is the pre-refinement composite

    Scenario: AI edit fails, canvas fallback runs
      Given azureImageEdit throws an error
      When refineScene is called
      Then refinement_method == "canvas_fallback"
      And edge softening is applied at character slot boundaries
      And palette is shifted toward dominant color
      And face mask regions are restored from original

    Scenario: No face mask skips identity protection
      Given no character layer with face_mask
      When refineScene falls back to canvas
      Then face protection step is skipped

  Feature: Compositing
    Scenario: Background stretches to fill page
      Given page dims 1536x1024 and background layer with slot="full_page"
      When compositeScene is called
      Then background image is drawn at (0,0) sized 1536x1024

    Scenario: Character anchored to ground
      Given character layer with pose.anchor="ground_contact" and slot {x:0.3, y:0.2, w:0.4, h:0.7}
      When compositeScene is called
      Then character feet align with bottom of slot

    Scenario: Invisible layers excluded
      Given a layer with visible=false
      When compositeScene is called
      Then that layer is skipped entirely

  Feature: Auto-save persistence
    Scenario: State auto-saves 3 seconds after last change
      Given user edits a scene title
      When 3 seconds elapse with no further edits
      Then POST /api/books/{key} is called with current state

    Scenario: Rapid edits debounce to single save
      Given user edits 5 scene titles in 2 seconds
      When all edits complete
      Then only 1 POST /api/books is made (the last one)

    Scenario: Resume single saved book
      Given exactly 1 book exists in Postgres at step "pages"
      When the app loads
      Then it skips the landing page and resumes BookWorkspace at step "pages"

    Scenario: Multiple saved books show picker
      Given 3 books exist in Postgres
      When the app loads
      Then the landing page shows all 3 with Resume/Delete buttons

  Feature: Characters API
    Scenario: Save a character
      When POST /api/characters/my-char with {name, reference_photos, design}
      Then the character is upserted in the characters table

    Scenario: List characters
      Given 2 characters exist
      When GET /api/characters
      Then both are returned newest-first

    Scenario: Delete a character
      Given character "my-char" exists
      When DELETE /api/characters/my-char
      Then the row is removed


# ─────────────────────────────────────────────────────────────────────
# EDGE CASES
# ─────────────────────────────────────────────────────────────────────

edge_cases:

  - id: POC-EC-01
    area: generation
    description: "Azure returns b64_json (happy path) — converted to data URL"

  - id: POC-EC-02
    area: generation
    description: "Azure returns URL instead of b64_json — used as-is"

  - id: POC-EC-03
    area: generation
    description: "Azure returns empty data array — throws 'No image from Azure'"

  - id: POC-EC-04
    area: generation
    description: "Azure returns non-JSON error body — caught by .json().catch(() => ({}))"

  - id: POC-EC-05
    area: edit
    description: "data URL with non-image MIME (e.g. data:text/plain;base64,...) — dataUrlToBlob returns null, throws 'No valid images for edit'"

  - id: POC-EC-06
    area: edit
    description: "Empty array passed to azureImageEdit — throws 'No valid images for edit'"

  - id: POC-EC-07
    area: edit
    description: "Single string (non-array) passed to azureImageEdit — wrapped in array automatically"

  - id: POC-EC-08
    area: edit
    description: "Large image (>10MB base64) — atob succeeds (browser-dependent), Blob created, sent as multipart"

  - id: POC-EC-09
    area: upload
    description: "User uploads non-image file — browser file input filtered by accept='image/*', non-images shouldn't appear"

  - id: POC-EC-10
    area: upload
    description: "File read error during FileReader — that photo is silently skipped, others continue"

  - id: POC-EC-11
    area: compositing
    description: "Layer with no image_url (null) — skipped during compositing"

  - id: POC-EC-12
    area: compositing
    description: "Layer with no slot and no pose — centered at 80% scale as fallback"

  - id: POC-EC-13
    area: persistence
    description: "Save fails (Postgres down) — logged to console, no user crash, auto-save timer continues"

  - id: POC-EC-14
    area: persistence
    description: "Resume with corrupted JSON in Postgres — caught, treated as no save, fresh wizard starts"

  - id: POC-EC-15
    area: refinement
    description: "Composite image is a URL (not data URL) — loadImage fetches it, canvas draws it, refinement proceeds"

  - id: POC-EC-16
    area: refinement
    description: "Face mask image fails to load — face protection skipped gracefully"

  - id: POC-EC-17
    area: refinement
    description: "Edge mask image fails to load — edge softening skipped gracefully"

  - id: POC-EC-18
    area: navigation
    description: "User jumps from Step 5 back to Step 2, changes style, returns to Step 5 — pages keep their existing images (no auto-regen)"

  - id: POC-EC-19
    area: version-history
    description: "Revert layer while generating — no conflict, revert is instant (canvas-based), generation continues in background"

  - id: POC-EC-20
    area: rate-limit
    description: "Azure returns 429 on all deployments — error surfaces as 'All Azure edit deployments failed: RateLimitReached on gpt-image-1-5; RateLimitReached on gpt-image-2-1'"


# ─────────────────────────────────────────────────────────────────────
# INVARIANTS
# ─────────────────────────────────────────────────────────────────────

invariants:

  - name: generation_never_returns_null
    description: "generateImage always returns a string (data URL or placeholder), never null or undefined"
    kind: postcondition
    expression: "typeof generateImage(prompt, size, quality) === 'string'"
    severity: critical

  - name: version_history_never_loses_images
    description: "Once an image appears in a layer, it is never overwritten without being pushed to history[]"
    kind: state_invariant
    expression: "old_image_url ∈ layer.history after any retry/upgrade/edit operation"
    severity: critical

  - name: deployment_order_deterministic
    description: "Deployments are always tried in order [gpt-image-1-5, gpt-image-2-1]"
    kind: state_invariant
    expression: "deployment_sequence == ['gpt-image-1-5', 'gpt-image-2-1']"
    severity: high

  - name: input_fidelity_string_only
    description: "input_fidelity is always sent as 'high' or 'low' (never a float) to Azure"
    kind: postcondition
    expression: "form.get('input_fidelity') ∈ {'high', 'low'}"
    severity: critical

  - name: multipart_for_edits
    description: "azureImageEdit always uses multipart/form-data, never application/json"
    kind: postcondition
    expression: "request.headers['Content-Type'] contains 'multipart/form-data'"
    severity: critical

  - name: auto_save_debounced
    description: "Auto-save fires at most once per 3-second quiet period"
    kind: state_invariant
    expression: "save_calls_in_window(3s) <= 1"
    severity: high

  - name: no_image_data_leaks_to_console
    description: "Base64 image data is never logged to console (too large, would crash devtools)"
    kind: postcondition
    expression: "no log line contains 'data:image' prefix"
    severity: medium

  - name: photo_count_capped_at_5
    description: "A character never has more than 5 reference photos"
    kind: state_invariant
    expression: "character.reference_photos.length <= 5"
    severity: high
