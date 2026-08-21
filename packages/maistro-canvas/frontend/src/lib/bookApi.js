import { chat, generateImage } from "./llmClient";

// Keys are server-side only (see server.js /api/llm/*). Nothing here holds them.

async function llm(messages, model = "gemini-flash") {
  return chat(messages, model, { temperature: 0.5, max_tokens: 4000 });
}

function extractJSON(text) {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)```/) || text.match(/(\{[\s\S]*\})/);
  if (!m) throw new Error("AI did not return valid JSON");
  return JSON.parse(m[1] || m[0]);
}

async function azureGenImage(prompt, opts = {}) {
  // Routed through the server proxy; the server holds the Azure credentials.
  return generateImage({
    prompt,
    model_id: "azure-gpt-image-2",
    size: opts.size || "1024x1024",
    quality: opts.quality || "medium",
  });
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export async function extractCharacterSpec(photoDataUrls) {
  const first3 = photoDataUrls.slice(0, 3);
  const resp = await llm([
    {
      role: "system",
      content: `You are a character analysis engine. Given photos of a child, extract precise physical traits for a character specification. Be specific and factual based on what you see.

Return ONLY valid JSON:
{
  "name_suggestion": "a generic name for the character",
  "hair": "detailed description - color, texture, length, style",
  "skin_tone": "detailed description",
  "eye_color": "specific color",
  "face_shape": "round, oval, heart, etc",
  "age_style": "estimated age range and body proportion style",
  "body_type": "build description for age",
  "signature_features": ["distinctive feature 1", "feature 2"],
  "typical_expression": "default/resting expression description",
  "clothing_note": "general style preference if visible"
}`,
    },
    {
      role: "user",
      content: [
        { type: "text", text: "Analyze these photos and extract the character specification:" },
        ...first3.map((url) => ({ type: "image_url", image_url: { url } })),
      ],
    },
  ]);
  return extractJSON(resp);
}

export async function generateCanonicalSheet(characterSpec, styleContract) {
  const style = styleContract || {};
  const artStyle = style.art_style || "warm watercolor childrens book illustration";
  const palette = style.color_palette?.join(", ") || "warm, soft pastels";
  const lighting = style.lighting || "soft natural light";

  const views = [
    {
      name: "front_view",
      prompt: `Character reference sheet, front view, full body. ${artStyle} style. A child with: ${characterSpec.hair} hair, ${characterSpec.skin_tone} skin, ${characterSpec.eye_color} eyes, ${characterSpec.face_shape} face. ${characterSpec.signature_features.join(", ")}. Neutral standing pose, arms slightly out from sides. Clean white background. Consistent childrens book illustration style. Palette: ${palette}. ${lighting}. High detail, clear linework.`,
    },
    {
      name: "three_quarter_view",
      prompt: `Character reference sheet, 3/4 angle view, full body. Same child as reference: ${characterSpec.hair} hair, ${characterSpec.skin_tone} skin, ${characterSpec.eye_color} eyes, ${characterSpec.face_shape} face. ${characterSpec.signature_features.join(", ")}. Slight turn to show depth. Clean white background. ${artStyle} style. Palette: ${palette}. ${lighting}.`,
    },
    {
      name: "side_profile",
      prompt: `Character reference sheet, side profile view, full body. Same child: ${characterSpec.hair} hair, ${characterSpec.skin_tone} skin, ${characterSpec.eye_color} eyes. ${characterSpec.signature_features.join(", ")}. Clean side profile. Clean white background. ${artStyle} style. Palette: ${palette}. ${lighting}.`,
    },
    {
      name: "expressions",
      prompt: `Character expression sheet, 4 expressions in grid: happy smiling, surprised, thinking/curious, sad. Same child: ${characterSpec.hair} hair, ${characterSpec.skin_tone} skin, ${characterSpec.eye_color} eyes, ${characterSpec.face_shape} face. ${characterSpec.signature_features.join(", ")}. Head and shoulders only. ${artStyle} style. Clean white background. Palette: ${palette}.`,
    },
  ];

  const sheet = {};
  for (const view of views) {
    sheet[view.name] = await azureGenImage(view.prompt, { size: "1024x1024" });
  }
  return sheet;
}

export async function generateBackground(scenePrompt, styleContract) {
  const s = styleContract || {};
  const fullPrompt = [
    s.art_style || "warm watercolor childrens book illustration",
    s.lighting || "soft natural light",
    `palette: ${s.color_palette?.join(", ") || "warm pastels"}`,
    "NO CHARACTERS, NO PEOPLE, NO FIGURES - background only",
    "leave space in the composition for a character to be placed",
    scenePrompt,
    s.negative_prompts || "",
  ]
    .filter(Boolean)
    .join(". ");

  return azureGenImage(fullPrompt, { size: "1024x1024" });
}

export async function generateCharacterPose(
  characterSpec,
  canonicalSheet,
  poseDesc,
  styleContract
) {
  const s = styleContract || {};
  const fullPrompt = [
    s.art_style || "warm watercolor childrens book illustration",
    `A child with: ${characterSpec.hair} hair, ${characterSpec.skin_tone} skin, ${characterSpec.eye_color} eyes, ${characterSpec.face_shape} face`,
    characterSpec.signature_features.join(", "),
    poseDesc,
    "ON PURE WHITE BACKGROUND for compositing",
    "full body visible",
    s.lighting || "soft natural light",
    `palette: ${s.color_palette?.join(", ") || "warm pastels"}`,
  ]
    .filter(Boolean)
    .join(". ");

  return azureGenImage(fullPrompt, { size: "1024x1024" });
}

export async function generateProp(propDesc, styleContract) {
  const s = styleContract || {};
  const fullPrompt = [
    s.art_style || "warm watercolor childrens book illustration",
    propDesc,
    "ON PURE WHITE BACKGROUND for compositing",
    `palette: ${s.color_palette?.join(", ") || "warm pastels"}`,
    s.lighting,
  ]
    .filter(Boolean)
    .join(". ");

  return azureGenImage(fullPrompt, { size: "1024x1024" });
}

export function compositeScene(canvas, bgUrl, characterUrl, characterSpec, propUrls = []) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  const drawImage = (url, x, y, width, height) =>
    new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        ctx.drawImage(img, x, y, width, height);
        resolve();
      };
      img.onerror = resolve;
      img.src = url;
    });

  return (async () => {
    await drawImage(bgUrl, 0, 0, w, h);
    if (characterUrl) {
      const charH = h * 0.75;
      const charW = charH * 0.45;
      const charX = w * 0.3;
      const charY = h - charH;
      await drawImage(characterUrl, charX, charY, charW, charH);
    }
    for (let i = 0; i < propUrls.length; i++) {
      const propSize = h * 0.3;
      await drawImage(propUrls[i], w * 0.6 + i * propSize * 0.5, h - propSize, propSize, propSize);
    }
    return canvas.toDataURL("image/png");
  })();
}

export { azureGenImage, fileToBase64, llm, extractJSON };
