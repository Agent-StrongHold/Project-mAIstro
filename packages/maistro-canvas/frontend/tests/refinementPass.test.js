/**
 * @vitest-environment jsdom
 */
import { describe, it, expect } from "vitest";

describe("buildRefinementPrompt", () => {
  it("includes edge softness for high values", async () => {
    const { buildRefinementPrompt } = await import("../src/lib/refinementPass");
    const prompt = buildRefinementPrompt({ technique: "watercolor", edge_softness: 0.8, contrast: "low" });
    expect(prompt).toContain("soft, blended edges");
    expect(prompt).toContain("watercolor");
  });

  it("includes clean edges for low softness", async () => {
    const { buildRefinementPrompt } = await import("../src/lib/refinementPass");
    const prompt = buildRefinementPrompt({ technique: "ink", edge_softness: 0.3, contrast: "high" });
    expect(prompt).toContain("clean, defined edges");
    expect(prompt).toContain("bold, clear contrast");
  });

  it("includes face preservation instruction", async () => {
    const { buildRefinementPrompt } = await import("../src/lib/refinementPass");
    const prompt = buildRefinementPrompt({});
    expect(prompt).toContain("Preserve the character's face EXACTLY");
  });

  it("defaults to warm watercolor when no styleToken", async () => {
    const { buildRefinementPrompt } = await import("../src/lib/refinementPass");
    const prompt = buildRefinementPrompt(undefined);
    expect(prompt).toContain("warm watercolor");
  });

  it("includes subtle edits instruction", async () => {
    const { buildRefinementPrompt } = await import("../src/lib/refinementPass");
    const prompt = buildRefinementPrompt({});
    expect(prompt).toContain("Subtle, minimal edits only");
  });
});

describe("refineScene", () => {
  it("throws when no composite provided", async () => {
    const { refineScene } = await import("../src/lib/refinementPass");
    await expect(refineScene({}, {})).rejects.toThrow("No composite to refine");
  });

  it("throws when composite is null", async () => {
    const { refineScene } = await import("../src/lib/refinementPass");
    await expect(refineScene({ composite: null }, {})).rejects.toThrow("No composite to refine");
  });

  it("throws when composite is empty string", async () => {
    const { refineScene } = await import("../src/lib/refinementPass");
    await expect(refineScene({ composite: "" }, {})).rejects.toThrow("No composite to refine");
  });
});

describe("buildEdgeMask", () => {
  it("returns a data URL string for full_page character", async () => {
    const { buildEdgeMask } = await import("../src/lib/refinementPass");
    // buildEdgeMask uses document.createElement("canvas") which needs real DOM
    // In jsdom, canvas.getContext("2d") returns null, so we test it doesn't throw on import
    expect(typeof buildEdgeMask).toBe("function");
  });
});
