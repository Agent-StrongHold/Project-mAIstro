import { describe, it, expect } from "vitest";

async function importEngine() {
  return await import("../src/lib/templateEngine");
}

describe("POSES", () => {
  it("has 14 poses defined", async () => {
    const { POSES } = await importEngine();
    expect(Object.keys(POSES).length).toBe(14);
  });

  it("each pose has required fields", async () => {
    const { POSES } = await importEngine();
    for (const [key, pose] of Object.entries(POSES)) {
      expect(pose.id, `${key} missing id`).toBe(key);
      expect(pose.label, `${key} missing label`).toBeTruthy();
      expect(pose.body, `${key} missing body`).toBeTruthy();
      expect(pose.geo, `${key} missing geo`).toBeDefined();
      expect(pose.geo.bounds, `${key} missing geo.bounds`).toBeDefined();
      expect(pose.geo.head_center, `${key} missing geo.head_center`).toBeDefined();
    }
  });

  it("all poses have anchor type ground_contact or seat_contact", async () => {
    const { POSES } = await importEngine();
    for (const [, pose] of Object.entries(POSES)) {
      expect(["ground_contact", "seat_contact"]).toContain(pose.anchor);
    }
  });
});

describe("generateScenePlan", () => {
  it("produces a plan with scenes from decomposition", async () => {
    const { generateScenePlan } = await importEngine();
    const decomp = {
      title: "Test Book",
      dedication: "For you",
      scenes: [
        { id: "s1", title: "Opening", page_text: "Once upon a time", type: "opening", pose: "standing_front", composition: "center" },
        { id: "s2", title: "Adventure", page_text: "They went on a journey", type: "action", pose: "running_left", composition: "left_third" },
      ],
    };
    const spec = { art_style: "watercolor", mood: "warm", lighting: "golden" };
    const plan = generateScenePlan(decomp, spec);

    expect(plan.title).toBe("Test Book");
    expect(plan.scenes.length).toBe(2);
    expect(plan.scenes[0].id).toBe("s1");
    expect(plan.style_token).toBeDefined();
    expect(plan.page_dims).toBeDefined();
    expect(plan.page_dims.w).toBeGreaterThan(0);
  });

  it("scene plan includes bg_prompt", async () => {
    const { generateScenePlan } = await importEngine();
    const decomp = {
      title: "Test",
      scenes: [
        { id: "s1", title: "Scene", page_text: "Hello", type: "action", pose: "standing_front", composition: "center" },
      ],
    };
    const plan = generateScenePlan(decomp, {});
    const scene = plan.scenes[0];
    expect(scene.bg_prompt).toBeTruthy();
  });

  it("produces page_dims with width and height", async () => {
    const { generateScenePlan } = await importEngine();
    const decomp = { title: "T", scenes: [{ id: "s1", title: "S", page_text: "x", type: "action" }] };
    const plan = generateScenePlan(decomp, {});
    expect(plan.page_dims.w).toBe(1536);
    expect(plan.page_dims.h).toBe(1024);
  });
});

describe("buildCharacterDesign", () => {
  it("builds description from character fields", async () => {
    const { buildCharacterDesign } = await importEngine();
    const char = {
      name: "Emma",
      age: "5-6",
      hair: "curly brown",
      skin_tone: "warm brown",
      eye_color: "hazel",
      build: "petite",
      signature_features: "dimple on left cheek",
    };
    const design = buildCharacterDesign(char);
    expect(design).toContain("Emma");
    expect(design).toContain("curly brown");
    expect(design).toContain("warm brown");
    expect(design).toContain("hazel");
    expect(design).toContain("dimple");
  });

  it("handles missing optional fields gracefully", async () => {
    const { buildCharacterDesign } = await importEngine();
    const char = { name: "Alex", age: "7-8" };
    const design = buildCharacterDesign(char);
    expect(design).toContain("Alex");
    expect(design.length).toBeGreaterThan(0);
  });

  it("handles completely empty character object", async () => {
    const { buildCharacterDesign } = await importEngine();
    const design = buildCharacterDesign({});
    expect(typeof design).toBe("string");
    expect(design.length).toBeGreaterThan(0);
  });
});

describe("buildAllCharacterDesigns", () => {
  it("returns a combined design string for all characters", async () => {
    const { buildAllCharacterDesigns } = await importEngine();
    const characters = [
      { name: "Emma", role: "main character", age: "5-6" },
      { name: "Max", role: "sidekick", age: "3-4" },
    ];
    const designs = buildAllCharacterDesigns(characters);
    expect(designs.length).toBe(1);
    expect(typeof designs[0]).toBe("string");
  });

  it("returns default design for empty array", async () => {
    const { buildAllCharacterDesigns } = await importEngine();
    const designs = buildAllCharacterDesigns([]);
    expect(designs.length).toBe(1);
  });
});
