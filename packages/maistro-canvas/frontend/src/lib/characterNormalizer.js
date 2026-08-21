// Character Normalizer — post-generation correction for pose-locking.
// Detects character silhouette in generated image, normalizes scale/position/anchor.

const WHITE_THRESHOLD = 240;
const MIN_PIXEL_RATIO = 0.005;

function isWhiteOrNear(r, g, b, a) {
  if (a < 128) return true;
  return r > WHITE_THRESHOLD && g > WHITE_THRESHOLD && b > WHITE_THRESHOLD;
}

export function detectSilhouette(imageData, width, height) {
  const data = imageData.data;
  let minX = width, minY = height, maxX = 0, maxY = 0;
  let pixelCount = 0;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      if (!isWhiteOrNear(data[i], data[i + 1], data[i + 2], data[i + 3])) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        pixelCount++;
      }
    }
  }

  if (pixelCount < width * height * MIN_PIXEL_RATIO) {
    return null;
  }

  return {
    bounds: {
      x: minX / width,
      y: minY / height,
      w: (maxX - minX) / width,
      h: (maxY - minY) / height,
    },
    center: {
      x: (minX + maxX) / 2 / width,
      y: (minY + maxY) / 2 / height,
    },
    pixel_ratio: pixelCount / (width * height),
    width_px: maxX - minX,
    height_px: maxY - minY,
  };
}

export function detectHeadRegion(imageData, width, height, silhouette) {
  if (!silhouette) return null;
  const data = imageData.data;
  const topY = silhouette.bounds.y * height;
  const centerY = silhouette.center.x * width;
  const searchHeight = silhouette.bounds.h * height * 0.3;
  const searchWidth = silhouette.bounds.w * width * 0.4;

  let minX = width, minY = height, maxX = 0, maxY = 0;
  let count = 0;

  const startY = Math.floor(Math.max(0, topY - 5));
  const endY = Math.floor(Math.min(height, topY + searchHeight));
  const startX = Math.floor(Math.max(0, centerY - searchWidth / 2));
  const endX = Math.floor(Math.min(width, centerY + searchWidth / 2));

  for (let y = startY; y < endY; y++) {
    for (let x = startX; x < endX; x++) {
      const i = (y * width + x) * 4;
      if (!isWhiteOrNear(data[i], data[i + 1], data[i + 2], data[i + 3])) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        count++;
      }
    }
  }

  if (count < 50) return null;

  return {
    bounds: {
      x: minX / width,
      y: minY / height,
      w: (maxX - minX) / width,
      h: (maxY - minY) / height,
    },
    center: {
      x: (minX + maxX) / 2 / width,
      y: (minY + maxY) / 2 / height,
    },
    radius: Math.max(maxX - minX, maxY - minY) / 2 / width,
  };
}

export function computeNormalization(silhouette, headRegion, poseGeo, canvasSize = 1024) {
  if (!silhouette || !poseGeo) return null;

  const expectedBounds = poseGeo.bounds;
  const expectedH = expectedBounds.h * canvasSize;
  const expectedW = expectedBounds.w * canvasSize;

  const actualH = silhouette.height_px;
  const actualW = silhouette.width_px;

  const scaleY = expectedH / actualH;
  const scaleX = expectedW / actualW;
  const scale = Math.min(scaleX, scaleY);

  const expectedAnchorX = expectedBounds.x * canvasSize + expectedW / 2;
  const expectedAnchorY = (poseGeo.ground_y || expectedBounds.y + expectedBounds.h) * canvasSize;

  const actualAnchorX = silhouette.bounds.x * canvasSize + actualW * scale / 2;
  const actualAnchorY = (silhouette.bounds.y + silhouette.bounds.h) * canvasSize * scale;

  const offsetX = expectedAnchorX - actualAnchorX;
  const offsetY = expectedAnchorY - actualAnchorY;

  const alignmentScore = headRegion && poseGeo.head_center
    ? 1 - Math.min(1, Math.abs(headRegion.center.x - poseGeo.head_center.x) +
                     Math.abs(headRegion.center.y - poseGeo.head_center.y))
    : null;

  return {
    scale,
    offset: { x: offsetX, y: offsetY },
    alignment_score: alignmentScore,
    expected_bounds: expectedBounds,
    actual_bounds: silhouette.bounds,
    needs_correction: scale < 0.8 || scale > 1.25 || (alignmentScore !== null && alignmentScore < 0.7),
  };
}

export async function normalizeCharacter(imageUrl, poseGeo, targetWidth = 1024, targetHeight = 1024) {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const srcCanvas = document.createElement("canvas");
      srcCanvas.width = img.naturalWidth;
      srcCanvas.height = img.naturalHeight;
      const srcCtx = srcCanvas.getContext("2d");
      srcCtx.drawImage(img, 0, 0);
      const imageData = srcCtx.getImageData(0, 0, srcCanvas.width, srcCanvas.height);

      const silhouette = detectSilhouette(imageData, srcCanvas.width, srcCanvas.height);
      if (!silhouette) {
        resolve({ normalized_url: imageUrl, normalization: null, silhouette: null });
        return;
      }

      const headRegion = detectHeadRegion(imageData, srcCanvas.width, srcCanvas.height, silhouette);
      const norm = computeNormalization(silhouette, headRegion, poseGeo, targetWidth);

      const outCanvas = document.createElement("canvas");
      outCanvas.width = targetWidth;
      outCanvas.height = targetHeight;
      const outCtx = outCanvas.getContext("2d");
      outCtx.fillStyle = "#FFFFFF";
      outCtx.fillRect(0, 0, targetWidth, targetHeight);

      if (norm) {
        const sw = silhouette.width_px;
        const sh = silhouette.height_px;
        const sx = silhouette.bounds.x * srcCanvas.width;
        const sy = silhouette.bounds.y * srcCanvas.height;
        const dw = sw * norm.scale;
        const dh = sh * norm.scale;
        const dx = norm.offset.x + (silhouette.bounds.x * targetWidth * norm.scale);
        const dy = norm.offset.y + (silhouette.bounds.y * targetHeight * norm.scale);

        outCtx.drawImage(srcCanvas, sx, sy, sw, sh, dx, dy, dw, dh);
      } else {
        const scale = Math.min(targetWidth * 0.6 / silhouette.width_px, targetHeight * 0.9 / silhouette.height_px);
        const dw = silhouette.width_px * scale;
        const dh = silhouette.height_px * scale;
        const dx = (targetWidth - dw) / 2;
        const dy = targetHeight * 0.95 - dh;
        // `sx`/`sy` are declared here, not assigned inline. The previous form
        // wrote `sx = ...` as an argument, but `sx` is `const`-scoped to the
        // `if` branch above and does not exist here — and ESM is always strict
        // mode, so that assignment raised `ReferenceError: sx is not defined`.
        // This is the *fallback* path, taken exactly when `computeNormalization`
        // returns nothing, so the branch that existed to degrade gracefully
        // threw instead. eslint could not see it because a duplicate export in
        // `api.js` made the whole file unparseable.
        const sx = silhouette.bounds.x * srcCanvas.width;
        const sy = silhouette.bounds.y * srcCanvas.height;
        outCtx.drawImage(srcCanvas, sx, sy, silhouette.width_px, silhouette.height_px, dx, dy, dw, dh);
      }

      resolve({
        normalized_url: outCanvas.toDataURL("image/png"),
        normalization: norm,
        silhouette,
        head_region: headRegion,
      });
    };
    img.onerror = () => resolve({ normalized_url: imageUrl, normalization: null, silhouette: null });
    img.src = imageUrl;
  });
}

export function buildFaceMask(headRegion, canvasSize = 1024) {
  if (!headRegion) return null;
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = canvasSize;
  maskCanvas.height = canvasSize;
  const ctx = maskCanvas.getContext("2d");
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, canvasSize, canvasSize);

  const cx = headRegion.center.x * canvasSize;
  const cy = headRegion.center.y * canvasSize;
  const rx = (headRegion.bounds.w * canvasSize) / 2 * 1.2;
  const ry = (headRegion.bounds.h * canvasSize) / 2 * 1.1;

  ctx.fillStyle = "#FFFFFF";
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();

  return maskCanvas.toDataURL("image/png");
}
