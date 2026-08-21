// Feature Extractor — analyzes uploaded reference photos locally (canvas-based)
// to extract hair color, skin tone, eye color, and face shape.
// Used when Azure's safety system blocks photo uploads in /images/edits.
// Falls back to rich text descriptions instead of raw image passing.

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = url;
  });
}

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;

  if (max === min) {
    h = s = 0;
  } else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }
  return { h: h * 360, s: s * 100, l: l * 100 };
}

function classifyHairColor(h, s, l) {
  if (l < 15) return "very dark black";
  if (l < 25 && s < 30) return "black";
  if (l < 30 && h > 15 && h < 40) return "very dark brown";
  if (l < 40 && h > 10 && h < 45 && s > 20) return "dark brown";
  if (l < 50 && h > 10 && h < 45) return "brown";
  if (l < 50 && h > 5 && h < 20 && s < 25) return "dark ash brown";
  if (l < 55 && h > 15 && h < 40 && s > 30) return "medium brown";
  if (l >= 40 && l < 55 && h > 20 && h < 50 && s > 40) return "auburn";
  if (l >= 35 && l < 55 && h > 5 && h < 25 && s > 50) return "reddish brown";
  if (l >= 40 && l < 60 && h > 10 && h < 30 && s < 25) return "ash blonde";
  if (l >= 50 && l < 70 && h > 15 && h < 45 && s > 25) return "light brown or dark blonde";
  if (l >= 55 && l < 75 && h > 20 && h < 50) return "dirty blonde";
  if (l >= 60 && l < 80 && s < 25) return "blonde";
  if (l >= 60 && l < 80 && h > 20 && h < 50 && s > 30) return "golden blonde";
  if (l >= 70 && l < 90 && s < 20) return "light blonde";
  if (l >= 75) return "very light blonde or white";
  if (h > 0 && h < 15 && s > 40) return "red";
  if (h > 5 && h < 30 && s > 30 && l < 50) return "ginger";
  if (s < 15 && l > 40) return "grey or silver";
  return "brown";
}

function classifySkinTone(h, s, l) {
  if (l < 30) return "deep dark brown";
  if (l < 40 && h > 15 && h < 35) return "dark brown";
  if (l < 50 && h > 15 && h < 40) return "warm medium brown";
  if (l < 55 && h > 10 && h < 35) return "medium olive or tan";
  if (l < 60 && h > 15 && h < 40 && s > 30) return "warm light brown";
  if (l < 65 && h > 10 && h < 35) return "light tan or olive";
  if (l < 70 && h > 15 && h < 40) return "warm fair with golden undertones";
  if (l < 75 && s > 20) return "fair with warm undertones";
  if (l < 75) return "fair with cool undertones";
  if (l < 80) return "very fair or porcelain";
  return "very fair or pale";
}

function classifyEyeColor(r, g, b) {
  const { h, s, l } = rgbToHsl(r, g, b);
  if (l < 20) return "very dark brown, almost black";
  if (l < 30 && s < 40) return "dark brown";
  if (l < 40 && s < 50) return "brown";
  if (l < 45 && h > 20 && h < 50 && s > 30) return "warm brown with amber flecks";
  if (h > 25 && h < 50 && s > 40 && l > 35 && l < 55) return "hazel";
  if (h > 20 && h < 45 && s > 50 && l > 40) return "amber";
  if (h > 50 && h < 170 && s > 20 && l > 25 && l < 55) return "green";
  if (h > 170 && h < 260 && s > 15 && l > 20 && l < 50) return "blue";
  if (h > 170 && h < 260 && s > 15 && l >= 50) return "light blue";
  if (h > 170 && h < 260 && s < 15) return "grey-blue";
  if (s < 15 && l < 40) return "dark grey";
  if (s < 20 && l >= 40) return "grey";
  return "brown";
}

function sampleRegion(imageData, imgW, cx, cy, radius) {
  const data = imageData.data;
  const samples = [];
  for (let dy = -radius; dy <= radius; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      if (dx * dx + dy * dy > radius * radius) continue;
      const x = Math.round(cx + dx);
      const y = Math.round(cy + dy);
      if (x < 0 || x >= imgW || y < 0 || y >= imageData.height) continue;
      const idx = (y * imgW + x) * 4;
      const a = data[idx + 3];
      if (a < 128) continue;
      samples.push({ r: data[idx], g: data[idx + 1], b: data[idx + 2] });
    }
  }
  if (samples.length === 0) return null;
  const avg = samples.reduce((acc, c) => ({ r: acc.r + c.r, g: acc.g + c.g, b: acc.b + c.b }), { r: 0, g: 0, b: 0 });
  return { r: Math.round(avg.r / samples.length), g: Math.round(avg.g / samples.length), b: Math.round(avg.b / samples.length) };
}

export async function extractFeaturesFromPhotos(photoUrls) {
  if (!photoUrls || photoUrls.length === 0) return null;

  const features = {
    hair_color: null,
    skin_tone: null,
    eye_color: null,
    description: "",
  };

  try {
    const img = await loadImage(photoUrls[0]);
    const canvas = document.createElement("canvas");
    const maxDim = 512;
    const scale = Math.min(maxDim / img.naturalWidth, maxDim / img.naturalHeight, 1);
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const w = canvas.width;
    const h = canvas.height;

    const headTopy = Math.round(h * 0.05);
    const headCy = Math.round(h * 0.18);
    const headCx = Math.round(w * 0.5);
    const headR = Math.round(Math.min(w, h) * 0.06);

    // Hair: sample from top of head
    const hairSample = sampleRegion(imageData, w, headCx, headTopy, headR);
    if (hairSample) {
      const hsl = rgbToHsl(hairSample.r, hairSample.g, hairSample.b);
      features.hair_color = classifyHairColor(hsl.h, hsl.s, hsl.l);
    }

    // Skin: sample from forehead area
    const foreheadSample = sampleRegion(imageData, w, headCx, headCy - headR * 0.3, Math.round(headR * 0.5));
    if (foreheadSample) {
      const hsl = rgbToHsl(foreheadSample.r, foreheadSample.g, foreheadSample.b);
      features.skin_tone = classifySkinTone(hsl.h, hsl.s, hsl.l);
    }

    // Eyes: sample from expected eye region
    const eyeY = Math.round(headCy + headR * 0.15);
    const leftEyeX = Math.round(headCx - headR * 0.5);
    const rightEyeX = Math.round(headCx + headR * 0.5);
    const eyeR = Math.round(headR * 0.2);
    const leftEye = sampleRegion(imageData, w, leftEyeX, eyeY, eyeR);
    const rightEye = sampleRegion(imageData, w, rightEyeX, eyeY, eyeR);
    const eyeColor = leftEye || rightEye;
    if (eyeColor) {
      features.eye_color = classifyEyeColor(eyeColor.r, eyeColor.g, eyeColor.b);
    }

    // Build description
    const parts = [];
    if (features.hair_color) parts.push(`${features.hair_color} hair`);
    if (features.skin_tone) parts.push(`${features.skin_tone} skin`);
    if (features.eye_color) parts.push(`${features.eye_color} eyes`);
    features.description = parts.join(", ");

    return features;
  } catch (err) {
    console.error("Feature extraction failed:", err);
    return null;
  }
}

export function buildPhotoDerivedDesign(features, baseDesign) {
  if (!features || !features.description) return baseDesign || "";

  let design = baseDesign || "a child character";

  if (features.hair_color) {
    design = design.replace(/\b(blonde|brown|black|red|ginger|auburn|white|grey|gray|dark brown|light brown|dirty blonde|strawberry blonde|wavy|curly|straight|shoulder.length|long|short)\b[^,]*(hair)/gi, `${features.hair_color} hair`);
    if (!/hair/i.test(design)) {
      design = `${features.hair_color} hair, ${design}`;
    }
  }

  if (features.skin_tone) {
    design = design.replace(/\b(fair|pale|light|medium|tan|olive|brown|dark|deep)\s*(skin|complexion|tone)\b[^,]*/gi, `${features.skin_tone} skin`);
    design = design.replace(/\b(skin tone|complexion)\s*:\s*[^,)]+/gi, `skin tone: ${features.skin_tone}`);
    if (!/skin/i.test(design)) {
      design = `${features.skin_tone} skin, ${design}`;
    }
  }

  if (features.eye_color) {
    design = design.replace(/\b(hazel|brown|blue|green|grey|gray|amber|dark)\s*(eyes|eye color)\b[^,]*/gi, `${features.eye_color}`);
    design = design.replace(/\b(eye color|eyes)\s*:\s*[^,)]+/gi, `eyes: ${features.eye_color}`);
    if (!/eye/i.test(design)) {
      design = `${features.eye_color} eyes, ${design}`;
    }
  }

  return `Based on reference photos: ${features.description}. ${design}`;
}
