// Rendering Pipeline — consumes structured scene plans, produces deterministic generation calls.
// The AI picks templates; this pipeline renders them.
// Characters are normalized after generation: silhouette detect → scale → anchor snap.

import {
} from "./templateEngine";
import { normalizeCharacter, buildFaceMask } from "./characterNormalizer";
import { pipelineImage, editImage } from "./llmClient";

// Provider credentials live server-side only (see server.js /api/llm/*).
// These wrappers preserve the original signatures while delegating the
// actual provider calls to the Express proxy.

// Edit one or more images via the server proxy (Azure multipart server-side).
export async function azureImageEdit(imageDataUrls, prompt, size = "1024x1024", quality = "medium", inputFidelity = 0.8) {
  const url = await editImage({
    images: imageDataUrls,
    prompt,
    size,
    quality,
    input_fidelity: inputFidelity,
  });
  if (!url) throw new Error("No edited image");
  return url;
}

function makePlaceholder(label) {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext("2d");
  const h = [...label].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 360;
  const g = ctx.createLinearGradient(0, 0, 512, 512);
  g.addColorStop(0, `hsl(${h},50%,20%)`);
  g.addColorStop(1, `hsl(${(h + 60) % 360},60%,35%)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.font = "bold 14px monospace";
  ctx.textAlign = "center";
  ctx.fillText(label, 256, 256);
  return c.toDataURL("image/png");
}

async function generateImage(prompt, size, quality = "medium") {
  try {
    const url = await pipelineImage({ prompt, size, quality });
    if (url) return url;
  } catch { /* fall through to placeholder */ }
  return makePlaceholder(prompt.slice(0, 40));
}

// ── Scene Renderer ───────────────────────────────────────────────────────────

export async function renderScene(scenePlan, pageDims, onProgress) {
  const { w, h } = pageDims || { w: 1536, h: 1024 };
  const imgSize = w >= h ? "1024x1024" : "1024x1536";
  const result = {
    scene_id: scenePlan.id,
    title: scenePlan.title,
    scene_type: scenePlan.scene_type,
    page_text: scenePlan.page_text,
    character_slot: scenePlan.character_slot,
    composition: scenePlan.composition,
    layers: [],
    composite: null,
  };

  // Step 1: Background
  onProgress?.(`Generating background for "${scenePlan.title}"...`);
  try {
    const bgUrl = await generateImage(scenePlan.bg_prompt, imgSize);
    result.layers.push({
      name: "Background",
      type: "background",
      image_url: bgUrl,
      z_index: 0,
      slot: "full_page",
    });
  } catch (err) {
    onProgress?.(`Background failed: ${err.message}`);
    result.layers.push({
      name: "Background",
      type: "background",
      image_url: makePlaceholder("background"),
      z_index: 0,
      slot: "full_page",
    });
  }

  // Step 2: Character (skip for title_page / dedication)
  if (scenePlan.character_prompt) {
    onProgress?.(`Generating character for "${scenePlan.title}"...`);
    try {
      const rawUrl = await generateImage(scenePlan.character_prompt, "1024x1024");

      // Normalize: detect silhouette → scale → align to pose geometry
      const poseGeo = scenePlan.character_slot?.pose?.geo;
      onProgress?.(`Normalizing character for "${scenePlan.title}"...`);
      const normResult = await normalizeCharacter(rawUrl, poseGeo, 1024, 1024);

      const faceMask = normResult.head_region
        ? buildFaceMask(normResult.head_region, 1024)
        : null;

      result.layers.push({
        name: "Character",
        type: "character",
        image_url: normResult.normalized_url,
        raw_url: rawUrl !== normResult.normalized_url ? rawUrl : null,
        z_index: 10,
        slot: scenePlan.character_slot?.slot_bounds || scenePlan.composition?.character_slot,
        pose: scenePlan.character_slot?.pose,
        normalization: normResult.normalization,
        silhouette: normResult.silhouette,
        head_region: normResult.head_region,
        face_mask: faceMask,
      });

      if (normResult.normalization?.needs_correction) {
        onProgress?.(`Character normalized (scale: ${normResult.normalization.scale.toFixed(2)}, alignment: ${(normResult.normalization.alignment_score || 0).toFixed(2)})`);
      }
    } catch (err) {
      onProgress?.(`Character failed: ${err.message}`);
      result.layers.push({
        name: "Character",
        type: "character",
        image_url: makePlaceholder("character"),
        z_index: 10,
        slot: scenePlan.composition?.character_slot,
        pose: scenePlan.character_slot?.pose,
      });
    }
  }

  // Step 3: Props
  for (let i = 0; i < (scenePlan.prop_prompts || []).length; i++) {
    const prop = scenePlan.prop_prompts[i];
    onProgress?.(`Generating prop "${prop.name}" for "${scenePlan.title}"...`);
    try {
      const propUrl = await generateImage(prop.prompt, "1024x1024");
      result.layers.push({
        name: prop.name,
        type: "prop",
        image_url: propUrl,
        z_index: 5 + i,
        placement: prop.placement,
      });
    } catch (err) {
      onProgress?.(`Prop "${prop.name}" failed: ${err.message}`);
    }
  }

  // Step 4: Composite
  onProgress?.(`Compositing "${scenePlan.title}"...`);
  result.composite = await compositeScene(result, pageDims);

  onProgress?.(`Scene "${scenePlan.title}" complete.`);
  return result;
}

// ── Compositor ───────────────────────────────────────────────────────────────
// Places layers using anchor snapping and composition zone geometry.

export async function compositeScene(renderedScene, pageDims) {
  const { w = 1536, h = 1024 } = pageDims || {};
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  const loadImage = (url) =>
    new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = url;
    });

  const sorted = [...(renderedScene.layers || [])].sort(
    (a, b) => (a.z_index || 0) - (b.z_index || 0)
  );

  for (const layer of sorted) {
    if (layer.type === "text") {
      renderTextLayer(ctx, layer, w, h);
      continue;
    }

    const img = await loadImage(layer.image_url);
    if (!img) continue;

    if (layer.slot === "full_page") {
      // Background: stretch to fill entire page
      ctx.drawImage(img, 0, 0, w, h);
    } else if (layer.type === "character" && layer.pose?.geo) {
      // Character: anchor-snap using pose geometry
      await compositeAnchoredCharacter(ctx, img, layer, w, h);
    } else if (layer.slot && typeof layer.slot === "object") {
      // Generic slot-based placement
      await compositeSlotted(ctx, img, layer.slot, w, h);
    } else {
      // Fallback: centered
      const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight) * 0.8;
      const dw = img.naturalWidth * scale;
      const dh = img.naturalHeight * scale;
      ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
    }
  }

  return canvas.toDataURL("image/png");
}

async function compositeAnchoredCharacter(ctx, img, layer, pageW, pageH) {
  const slot = layer.slot || { x: 0.3, y: 0.2, w: 0.4, h: 0.7 };

  const slotPx = {
    x: slot.x * pageW,
    y: slot.y * pageH,
    w: slot.w * pageW,
    h: slot.h * pageH,
  };

  // Character should fill slot height, maintain aspect ratio
  const targetH = slotPx.h;
  const imgAspect = img.naturalWidth / img.naturalHeight;
  const targetW = targetH * imgAspect;

  // Anchor: snap feet to bottom of slot (ground_contact) or seat to slot center (seat_contact)
  const anchorType = layer.pose.anchor || "ground_contact";
  let drawX, drawY;

  if (anchorType === "ground_contact") {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y + slotPx.h - targetH;
  } else if (anchorType === "seat_contact") {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y + slotPx.h * 0.4 - targetH * 0.5;
  } else {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y;
  }

  ctx.drawImage(img, drawX, drawY, targetW, targetH);
}

async function compositeSlotted(ctx, img, slot, pageW, pageH) {
  const dx = Math.round(slot.x * pageW);
  const dy = Math.round(slot.y * pageH);
  const dw = Math.round(slot.w * pageW);
  const dh = Math.round(slot.h * pageH);

  const imgAspect = img.naturalWidth / img.naturalHeight;
  const slotAspect = dw / dh;
  let drawW, drawH, drawX, drawY;

  if (imgAspect > slotAspect) {
    drawH = dh;
    drawW = dh * imgAspect;
    drawX = dx - (drawW - dw) / 2;
    drawY = dy;
  } else {
    drawW = dw;
    drawH = dw / imgAspect;
    drawX = dx;
    drawY = dy - (drawH - dh) / 2;
  }

  ctx.drawImage(img, drawX, drawY, drawW, drawH);
}

function renderTextLayer(ctx, layer, pageW, pageH) {
  const isTitle = layer.name === "Title Text";
  const title = layer.text_content || "";
  const subtext = layer.subtext || "";

  if (!title && !subtext) return;

  const centerX = pageW / 2;
  const centerY = pageH / 2;

  if (isTitle) {
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    if (title) {
      const fontSize = Math.max(48, Math.min(pageW / 12, 120));
      ctx.font = `bold ${fontSize}px Georgia, "Times New Roman", serif`;
      ctx.fillStyle = "rgba(0,0,0,0.4)";
      ctx.fillText(title, centerX + 3, centerY - (subtext ? fontSize * 0.3 : 0) + 3);
      ctx.fillStyle = "#FFFFFF";
      ctx.strokeStyle = "rgba(0,0,0,0.5)";
      ctx.lineWidth = fontSize / 20;
      ctx.strokeText(title, centerX, centerY - (subtext ? fontSize * 0.3 : 0));
      ctx.fillText(title, centerX, centerY - (subtext ? fontSize * 0.3 : 0));
    }

    if (subtext) {
      const subSize = Math.max(18, Math.min(pageW / 30, 36));
      ctx.font = `italic ${subSize}px Georgia, "Times New Roman", serif`;
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fillText(subtext, centerX, centerY + 60);
    }
  } else {
    const padding = 40;
    const maxW = pageW - padding * 2;
    const fontSize = Math.max(16, Math.min(pageW / 40, 28));
    ctx.font = `${fontSize}px Georgia, "Times New Roman", serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#FFFFFF";

    const words = (layer.text_content || "").split(" ");
    const lines = [];
    let line = "";
    for (const word of words) {
      const test = line ? `${line} ${word}` : word;
      if (ctx.measureText(test).width > maxW) {
        if (line) lines.push(line);
        line = word;
      } else {
        line = test;
      }
    }
    if (line) lines.push(line);

    const lineHeight = fontSize * 1.5;
    const blockH = lines.length * lineHeight;
    const startY = pageH - padding - blockH - 20;

    ctx.fillStyle = "rgba(0,0,0,0.55)";
    const bgPad = 16;
    ctx.beginPath();
    ctx.roundRect(centerX - maxW / 2 - bgPad, startY - bgPad, maxW + bgPad * 2, blockH + bgPad * 2, 8);
    ctx.fill();

    ctx.fillStyle = "#FFFFFF";
    lines.forEach((l, i) => {
      ctx.fillText(l, centerX, startY + i * lineHeight + lineHeight / 2);
    });
  }
}

// ── Background Removal ────────────────────────────────────────────────────
// Removes near-white/grey backgrounds from generated images so layers
// composite properly. Uses edge-based flood fill from corners with a
// luminance threshold, then alpha-mattes the boundary for soft edges.

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = url;
  });
}

function luminance(r, g, b) {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

export async function removeBackground(imageDataUrl, threshold = 240, feather = 4) {
  const img = await loadImage(imageDataUrl);
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, 0);
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;
  const w = canvas.width;
  const h = canvas.height;

  // Build a mask: true = keep (foreground), false = remove (background)
  // Start from corners and flood-fill pixels that are "background-colored"
  const mask = new Uint8Array(w * h); // 0 = unvisited, 1 = bg, 2 = fg
  const isBgColor = (idx) => {
    const r = data[idx * 4];
    const g = data[idx * 4 + 1];
    const b = data[idx * 4 + 2];
    const lum = luminance(r, g, b);
    if (lum < threshold) return false;
    const maxC = Math.max(r, g, b);
    const minC = Math.min(r, g, b);
    if (maxC - minC > 50) return false;
    return true;
  };

  // BFS flood fill from all edge pixels
  const queue = [];
  for (let x = 0; x < w; x++) {
    if (isBgColor(x)) { mask[x] = 1; queue.push(x); }
    if (isBgColor((h - 1) * w + x)) { mask[(h - 1) * w + x] = 1; queue.push((h - 1) * w + x); }
  }
  for (let y = 0; y < h; y++) {
    if (isBgColor(y * w)) { mask[y * w] = 1; queue.push(y * w); }
    if (isBgColor(y * w + w - 1)) { mask[y * w + w - 1] = 1; queue.push(y * w + w - 1); }
  }

  let qi = 0;
  while (qi < queue.length) {
    const idx = queue[qi++];
    if (mask[idx] !== 1) continue;
    const x = idx % w;
    const y = (idx - x) / w;
    const neighbors = [];
    if (x > 0) neighbors.push(idx - 1);
    if (x < w - 1) neighbors.push(idx + 1);
    if (y > 0) neighbors.push(idx - w);
    if (y < h - 1) neighbors.push(idx + w);
    for (const ni of neighbors) {
      if (mask[ni] === 0 && isBgColor(ni)) {
        mask[ni] = 1;
        queue.push(ni);
      }
    }
  }

  // Mark remaining unvisited as foreground
  for (let i = 0; i < mask.length; i++) {
    if (mask[i] === 0) mask[i] = 2;
  }

  // Feather the alpha at boundaries for soft edges
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      if (mask[idx] === 1) {
        data[idx * 4 + 3] = 0;
      } else if (mask[idx] === 2 && feather > 0) {
        let minDist = feather + 1;
        for (let fy = -feather; fy <= feather; fy++) {
          for (let fx = -feather; fx <= feather; fx++) {
            const nx = x + fx;
            const ny = y + fy;
            if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
            if (mask[ny * w + nx] === 1) {
              const d = Math.sqrt(fx * fx + fy * fy);
              if (d < minDist) minDist = d;
            }
          }
        }
        if (minDist <= feather) {
          const alpha = Math.round(255 * (minDist / feather));
          data[idx * 4 + 3] = alpha;
        }
      }
    }
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas.toDataURL("image/png");
}

// ── Full Book Renderer ───────────────────────────────────────────────────────

export async function renderBook(bookPlan, onSceneProgress, onSceneComplete) {
  const results = [];
  const totalScenes = bookPlan.scenes.length;

  for (let i = 0; i < totalScenes; i++) {
    const scenePlan = bookPlan.scenes[i];
    onSceneProgress?.(`Scene ${i + 1}/${totalScenes}: ${scenePlan.title}`, i, totalScenes);

    try {
      const rendered = await renderScene(
        scenePlan,
        bookPlan.page_dims,
        onSceneProgress
      );
      results.push(rendered);
      onSceneComplete?.(rendered, i, totalScenes);
    } catch (err) {
      onSceneProgress?.(`Scene ${i + 1} failed: ${err.message}`);
      results.push({
        scene_id: scenePlan.id,
        title: scenePlan.title,
        error: err.message,
        layers: [],
        composite: makePlaceholder(scenePlan.title),
      });
    }
  }

  return {
    ...bookPlan,
    rendered_scenes: results,
    rendered_at: new Date().toISOString(),
    status: "rendered",
  };
}

export { generateImage, makePlaceholder };

// ── Layer Draft Generator ────────────────────────────────────────────────────
// Generates a single layer at draft quality (512x512, quality "low").

async function azureDraftGen(prompt, size = "1024x1024", quality = "low") {
  // Draft tier uses the mini deployments, selected server-side.
  const url = await pipelineImage({ prompt, size, quality, tier: "draft" });
  if (!url) throw new Error("Draft deployments failed");
  return url;
}

export async function renderLayerDraft(prompt, onProgress, referenceImage, layerType) {
  onProgress?.("Generating layer draft...");
  let url;
  if (referenceImage) {
    try {
      url = await azureImageEdit(referenceImage, prompt, "1024x1024", "low", 0.5);
    } catch { /* edit endpoint unavailable; fall through to the generate path */ }
  }
  if (!url) {
    try {
      url = await azureDraftGen(prompt, "1024x1024", "low");
    } catch {
      try {
        url = await generateImage(prompt, "1024x1024", "low");
      } catch (err) {
        onProgress?.(`Layer draft failed: ${err.message}`);
        return makePlaceholder(prompt.slice(0, 40));
      }
    }
  }
  if (layerType === "character" || layerType === "prop") {
    onProgress?.("Removing background...");
    try {
      url = await removeBackground(url);
    } catch { /* background removal is an enhancement; keep the original url */ }
  }
  return url;
}

// ── Layer Final Upgrade ──────────────────────────────────────────────────────

export async function renderLayerFinal(prompt, onProgress, referenceImage, layerType) {
  onProgress?.("Upgrading layer to final quality...");
  let url;
  if (referenceImage) {
    const upscalePrompt = [
      "Enhance this illustration to higher quality.",
      "Keep the EXACT same composition, colors, pose, and layout.",
      "Add finer detail, smoother gradients, crisper edges, and better lighting.",
      "Do NOT change the subject, pose, or scene in any way.",
      "This is a quality upgrade, not a new illustration.",
      prompt,
    ].join(" ");
    try {
      url = await azureImageEdit(referenceImage, upscalePrompt, "1024x1024", "medium", 0.9);
    } catch (err) {
      onProgress?.(`HQ edit failed (${err.message}), regenerating from text...`);
    }
  }
  if (!url) {
    try {
      url = await generateImage(prompt, "1024x1024", "medium");
    } catch (err) {
      onProgress?.(`Layer upgrade failed: ${err.message}`);
      return makePlaceholder(prompt.slice(0, 40));
    }
  }
  if (layerType === "character" || layerType === "prop") {
    onProgress?.("Removing background...");
    try {
      url = await removeBackground(url);
    } catch { /* background removal is an enhancement; keep the original url */ }
  }
  return url;
}

// ── Storyboard Overview ──────────────────────────────────────────────────────

export async function renderStoryboardOverview(plan, onProgress) {
  const sceneDescs = plan.scenes
    .slice(0, 12)
    .map((s, i) => `${i + 1}. ${s.title}: ${s.description || s.page_text || ""}`)
    .join("\n");

  const prompt = [
    `Children's book storyboard overview showing ${plan.scenes.length} scenes in a grid layout.`,
    `Style: ${plan.style_token?.technique || "warm watercolor illustration"}`,
    `Title: "${plan.title}"`,
    `Scenes:\n${sceneDescs}`,
    "Show each scene as a small thumbnail in a grid, numbered.",
    "Grid layout, 3-4 rows, each cell is a different scene.",
  ].join("\n");

  onProgress?.("Generating storyboard overview...");
  try {
    return await generateImage(prompt, "1024x1024", "medium");
  } catch (err) {
    onProgress?.(`Storyboard overview failed: ${err.message}`);
    return makePlaceholder("Storyboard Overview");
  }
}

// ── Character Reference Sheet (11 images) ────────────────────────────────────

const CHARACTER_REFS = [
  // Turnaround (4 large, square layout)
  { id: "front", label: "Front View", category: "turnaround", angle: "facing directly forward, front view, full body" },
  { id: "3q_left", label: "3/4 Left View", category: "turnaround", angle: "three-quarter view from the left, full body" },
  { id: "isometric", label: "Isometric View", category: "turnaround", angle: "isometric view, slightly elevated angle showing depth, full body" },
  { id: "running", label: "Running", category: "turnaround", angle: "running, mid-stride, shown from the side to show full motion, full body" },
  // Action poses (4 bottom strip)
  { id: "sitting", label: "Sitting Cross-Legged", category: "pose", angle: "sitting cross-legged on the ground, three-quarter view to show leg position, full body" },
  { id: "walking", label: "Walking", category: "pose", angle: "walking naturally, shown from the side to show stride, full body" },
  { id: "wonder", label: "Looking Up in Wonder", category: "pose", angle: "standing and looking upward with wonder and awe, head tilted back, shown from a low angle looking up at the character, full body" },
  { id: "arms_raised", label: "Arms Raised", category: "pose", angle: "standing with both arms raised above head in joy or celebration, facing forward, full body" },
  // Resting/emotional (3 right side)
  { id: "sleeping", label: "Lying Down / Sleeping", category: "pose", angle: "lying down on their side, sleeping peacefully, shown from the side to show full horizontal body" },
  { id: "crouching", label: "Crouching", category: "pose", angle: "crouching down examining something on the ground, three-quarter view to show depth of crouch, full body" },
  { id: "hugging", label: "Hugging", category: "pose", angle: "standing with arms wrapped around an object as if hugging it tightly, facing forward to show arm wrap, full body" },
];

export { CHARACTER_REFS };

import { extractFeaturesFromPhotos, buildPhotoDerivedDesign } from "./featureExtractor";

export async function renderCharacterReferences(characterDesign, styleToken, onProgress, referenceImages) {
  const technique = styleToken?.technique || "warm watercolor children's book illustration";
  const lighting = styleToken?.lighting || "soft warm light";
  const edgeSoftness = styleToken?.edge_softness ?? 0.7;
  const contrast = styleToken?.contrast || "low";
  const detailLevel = styleToken?.detail_level || "moderate";
  const palette = styleToken?.palette || "";

  const refImages = Array.isArray(referenceImages) ? referenceImages : referenceImages ? [referenceImages] : [];

  let finalDesign = characterDesign;

  // Extract features from photos locally, override text description
  let photoFeatures = null;
  if (refImages.length > 0) {
    onProgress?.(`Analyzing ${refImages.length} reference photo${refImages.length > 1 ? "s" : ""}...`);
    try {
      photoFeatures = await extractFeaturesFromPhotos(refImages);
      if (photoFeatures?.description) {
        finalDesign = buildPhotoDerivedDesign(photoFeatures, characterDesign);
        onProgress?.(`Detected: ${photoFeatures.description}`);
      }
    } catch {
      onProgress?.(`Photo analysis failed, using text description only`);
    }
  }

  const prompt = [
    `Character turnaround reference sheet for a children's book character.`,
    `Art style: ${technique}.`,
    `Lighting: ${lighting}.`,
    edgeSoftness > 0.5 ? "Soft blended edges, painterly style." : "Clean defined edges with consistent line weight.",
    `Contrast: ${contrast}. Detail level: ${detailLevel}.`,
    palette ? `Color palette: ${palette}.` : "",
    photoFeatures ? `IMPORTANT: Match this child's EXACT appearance — ${photoFeatures.description}. These are the REAL features extracted from reference photos — use them precisely.` : "",
    finalDesign,
    "Show the SAME character from multiple angles in a grid layout on ONE image:",
    "Top row: front view, 3/4 left view, side view, back view.",
    "Bottom row: sitting cross-legged, walking, running, arms raised in joy.",
    "Each view shows the full body from head to toes.",
    "Clean light grey background (NOT pure white, NOT pure black).",
    "Consistent character design across ALL views — same child, same clothes, same features.",
    "The character MUST match the art style exactly — same rendering technique, same color temperature, same line quality.",
    photoFeatures ? `The hair MUST be ${photoFeatures.hair_color || "as described"}, skin MUST be ${photoFeatures.skin_tone || "as described"}, eyes MUST be ${photoFeatures.eye_color || "as described"} — these are non-negotiable from the reference photos.` : "",
    "NO text, NO labels, NO watermarks, NO speech bubbles, NO borders between views.",
  ].filter(Boolean).join(" ");

  onProgress?.("Generating character reference sheet...");
  try {
    // Try photo-guided edit first (may be blocked by safety filter)
    if (refImages.length > 0) {
      onProgress?.("Attempting photo-guided generation...");
      try {
        const imageUrl = await azureImageEdit(
          refImages,
          prompt,
          "1024x1024",
          "medium",
          0.9
        );
        onProgress?.("Character reference sheet ready (photo-guided).");
        return imageUrl;
      } catch (editErr) {
        onProgress?.(`Edit endpoint blocked (${editErr.message.substring(0, 60)}...), using feature-enriched text generation...`);
      }
    }
    // Text-to-image with photo-derived features baked in
    const imageUrl = await generateImage(prompt, "1024x1024", "medium");
    onProgress?.("Character reference sheet ready.");
    return imageUrl;
  } catch (err) {
    onProgress?.(`Character sheet failed: ${err.message}`);
    return makePlaceholder("Character Reference Sheet");
  }
}

// ── Style Sample Generator ───────────────────────────────────────────────────

export async function renderStyleSample(styleToken, setting, onProgress) {
  const prompt = [
    "A sample illustration showing the art style for a children's book.",
    styleToken?.technique || "warm watercolor illustration",
    `Setting: ${setting || "a cozy scene with warm colors"}`,
    `Lighting: ${styleToken?.lighting || "soft warm light"}`,
    "Show a simple scene that demonstrates the color palette, line style, and mood.",
    "NO text, NO watermarks.",
  ].join(". ");

  onProgress?.("Generating style sample...");
  try {
    return await generateImage(prompt, "1024x1024", "medium");
  } catch (err) {
    onProgress?.(`Style sample failed: ${err.message}`);
    return makePlaceholder("Style Sample");
  }
}
