// Identity-Safe Refinement Pass — AI-assisted polish with client-side fallback.
//
// Primary: Azure /images/edits via multipart/form-data (GPT-image-1.5 preferred).
//   - Preserves the composite as input image
//   - Uses input_fidelity to keep face/identity
//   - AI does the heavy lifting for edge blending, palette unification
//
// Fallback: client-side canvas post-processing if AI edit fails.
//   - Edge blending via gaussian blur on seam edges
//   - Palette unification (subtle color shift toward dominant palette)
//   - Contrast/brightness normalization
//   - Face mask protection

import { azureImageEdit } from "./renderingPipeline";

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = url;
  });
}

function buildEdgeMask(renderedScene, pageDims) {
  const { w = 1536, h = 1024 } = pageDims || {};
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, w, h);

  const charLayer = renderedScene.layers?.find((l) => l.type === "character");
  if (!charLayer?.slot || charLayer.slot === "full_page") {
    return canvas.toDataURL("image/png");
  }

  const slot = charLayer.slot;
  const sx = slot.x * w;
  const sy = slot.y * h;
  const sw = slot.w * w;
  const sh = slot.h * h;

  const edgeWidth = Math.max(sw, sh) * 0.12;

  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(sx - edgeWidth / 2, sy - edgeWidth / 2, sw + edgeWidth, sh + edgeWidth);
  ctx.clearRect(sx + edgeWidth / 2, sy + edgeWidth / 2, sw - edgeWidth, sh - edgeWidth);

  return canvas.toDataURL("image/png");
}

function extractDominantColor(imageData) {
  const data = imageData.data;
  let rSum = 0, gSum = 0, bSum = 0, count = 0;
  const step = 16;
  for (let i = 0; i < data.length; i += 4 * step) {
    const a = data[i + 3];
    if (a < 128) continue;
    rSum += data[i];
    gSum += data[i + 1];
    bSum += data[i + 2];
    count++;
  }
  if (count === 0) return { r: 128, g: 128, b: 128 };
  return { r: Math.round(rSum / count), g: Math.round(gSum / count), b: Math.round(bSum / count) };
}

function applyEdgeSoften(ctx, canvas, edgeMaskUrl, strength) {
  return new Promise((resolve) => {
    const maskImg = new Image();
    maskImg.crossOrigin = "anonymous";
    maskImg.onload = () => {
      const w = canvas.width;
      const h = canvas.height;

      const maskCanvas = document.createElement("canvas");
      maskCanvas.width = w;
      maskCanvas.height = h;
      const maskCtx = maskCanvas.getContext("2d");
      maskCtx.drawImage(maskImg, 0, 0, w, h);
      const maskData = maskCtx.getImageData(0, 0, w, h);

      const origData = ctx.getImageData(0, 0, w, h);

      const blurCanvas = document.createElement("canvas");
      blurCanvas.width = w;
      blurCanvas.height = h;
      const blurCtx = blurCanvas.getContext("2d");
      blurCtx.filter = `blur(${Math.round(strength * 6)}px)`;
      blurCtx.drawImage(canvas, 0, 0);
      const blurData = blurCtx.getImageData(0, 0, w, h);

      for (let i = 0; i < origData.data.length; i += 4) {
        const maskVal = maskData.data[i] / 255;
        if (maskVal > 0) {
          const blend = maskVal * strength * 0.4;
          origData.data[i] = Math.round(origData.data[i] * (1 - blend) + blurData.data[i] * blend);
          origData.data[i + 1] = Math.round(origData.data[i + 1] * (1 - blend) + blurData.data[i + 1] * blend);
          origData.data[i + 2] = Math.round(origData.data[i + 2] * (1 - blend) + blurData.data[i + 2] * blend);
        }
      }

      ctx.putImageData(origData, 0, 0);
      resolve();
    };
    maskImg.onerror = () => resolve();
    maskImg.src = edgeMaskUrl;
  });
}

function applyPaletteUnification(ctx, canvas, strength) {
  const w = canvas.width;
  const h = canvas.height;
  const imageData = ctx.getImageData(0, 0, w, h);
  const dominant = extractDominantColor(imageData);
  const data = imageData.data;
  const shift = strength * 0.06;

  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue;
    data[i] = Math.round(data[i] * (1 - shift) + dominant.r * shift);
    data[i + 1] = Math.round(data[i + 1] * (1 - shift) + dominant.g * shift);
    data[i + 2] = Math.round(data[i + 2] * (1 - shift) + dominant.b * shift);
  }

  ctx.putImageData(imageData, 0, 0);
}

function applyFaceProtection(ctx, canvas, faceMaskUrl, originalCompositeUrl) {
  return new Promise((resolve) => {
    let pending = 2;
    const maskImg = new Image();
    const origImg = new Image();

    const tryBlend = () => {
      if (pending > 0) return;
      if (!maskImg.complete || maskImg.naturalWidth === 0 || !origImg.complete || origImg.naturalWidth === 0) {
        resolve();
        return;
      }

      const w = canvas.width;
      const h = canvas.height;

      const origCanvas = document.createElement("canvas");
      origCanvas.width = w;
      origCanvas.height = h;
      const origCtx = origCanvas.getContext("2d");
      origCtx.drawImage(origImg, 0, 0, w, h);
      const origData = origCtx.getImageData(0, 0, w, h);

      const maskCanvas2 = document.createElement("canvas");
      maskCanvas2.width = w;
      maskCanvas2.height = h;
      const maskCtx2 = maskCanvas2.getContext("2d");
      maskCtx2.drawImage(maskImg, 0, 0, w, h);
      const maskData = maskCtx2.getImageData(0, 0, w, h);

      const refinedData = ctx.getImageData(0, 0, w, h);

      for (let i = 0; i < origData.data.length; i += 4) {
        const maskVal = maskData.data[i] / 255;
        if (maskVal > 0.1) {
          const w2 = maskVal;
          refinedData.data[i] = Math.round(origData.data[i] * w2 + refinedData.data[i] * (1 - w2));
          refinedData.data[i + 1] = Math.round(origData.data[i + 1] * w2 + refinedData.data[i + 1] * (1 - w2));
          refinedData.data[i + 2] = Math.round(origData.data[i + 2] * w2 + refinedData.data[i + 2] * (1 - w2));
        }
      }

      ctx.putImageData(refinedData, 0, 0);
      resolve();
    };

    maskImg.crossOrigin = "anonymous";
    origImg.crossOrigin = "anonymous";
    maskImg.onload = () => { pending--; tryBlend(); };
    origImg.onload = () => { pending--; tryBlend(); };
    maskImg.onerror = () => { pending--; tryBlend(); };
    origImg.onerror = () => { pending--; tryBlend(); };
    maskImg.src = faceMaskUrl;
    origImg.src = originalCompositeUrl;
  });
}

function buildRefinementPrompt(styleToken) {
  const technique = styleToken?.technique || "warm watercolor childrens book illustration";
  const edgeSoftness = styleToken?.edge_softness ?? 0.7;
  const contrast = styleToken?.contrast || "low";

  return [
    `Refine this ${technique} children's book illustration.`,
    "Smooth edges between character and background so they feel painted together.",
    "Ensure consistent color palette and line style across the entire image.",
    edgeSoftness > 0.5
      ? "Use soft, blended edges — no harsh cutout borders."
      : "Use clean, defined edges with consistent line weight.",
    contrast === "low"
      ? "Keep contrast soft and gentle."
      : contrast === "high"
        ? "Maintain bold, clear contrast between elements."
        : "Balance contrast naturally.",
    "CRITICAL: Preserve the character's face EXACTLY — do not change facial features, expression, or identity.",
    "Maintain the character's pose and proportions exactly.",
    "Do not add text, watermarks, or signatures.",
    "Subtle, minimal edits only. This is a polish pass, not a redraw.",
  ].join(" ");
}

export async function refineScene(renderedScene, styleToken, onProgress) {
  if (!renderedScene?.composite) {
    throw new Error("No composite to refine");
  }

  onProgress?.("Preparing refinement...");

  const charLayer = renderedScene.layers?.find((l) => l.type === "character");
  const originalComposite = renderedScene.composite;

  const prompt = buildRefinementPrompt(styleToken);

  // Primary: AI-assisted edit via /images/edits (multipart/form-data)
  onProgress?.("Running AI refinement pass...");
  try {
    const refinedUrl = await azureImageEdit(
      originalComposite,
      prompt,
      "1024x1024",
      "medium",
      0.9
    );
    onProgress?.("AI refinement complete.");
    return {
      ...renderedScene,
      composite: refinedUrl,
      composite_original: originalComposite,
      refined: true,
      refined_at: new Date().toISOString(),
      refinement_method: "ai_edit",
    };
  } catch (aiErr) {
    onProgress?.(`AI edit failed (${aiErr.message}), using client-side refinement...`);
  }

  // Fallback: client-side canvas post-processing
  const faceMask = charLayer?.face_mask;
  const edgeSoftness = styleToken?.edge_softness ?? 0.7;

  const img = await loadImage(originalComposite);
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, 0);

  onProgress?.("Softening layer edges...");
  const edgeMask = buildEdgeMask(renderedScene, {
    w: canvas.width,
    h: canvas.height,
  });
  await applyEdgeSoften(ctx, canvas, edgeMask, edgeSoftness);

  onProgress?.("Unifying color palette...");
  applyPaletteUnification(ctx, canvas, edgeSoftness);

  onProgress?.("Normalizing contrast...");
  const contrastVal = styleToken?.contrast === "high" ? 1.1 : styleToken?.contrast === "low" ? 0.9 : 1.0;
  const brightnessVal = 1.02;
  const filterCanvas = document.createElement("canvas");
  filterCanvas.width = canvas.width;
  filterCanvas.height = canvas.height;
  const filterCtx = filterCanvas.getContext("2d");
  filterCtx.filter = `contrast(${contrastVal}) brightness(${brightnessVal})`;
  filterCtx.drawImage(canvas, 0, 0);
  ctx.drawImage(filterCanvas, 0, 0);

  if (faceMask) {
    onProgress?.("Protecting character identity...");
    await applyFaceProtection(ctx, canvas, faceMask, originalComposite);
  }

  onProgress?.("Client-side refinement complete.");

  return {
    ...renderedScene,
    composite: canvas.toDataURL("image/png"),
    composite_original: originalComposite,
    refined: true,
    refined_at: new Date().toISOString(),
    refinement_method: "canvas_fallback",
  };
}

export { buildRefinementPrompt, buildEdgeMask };
