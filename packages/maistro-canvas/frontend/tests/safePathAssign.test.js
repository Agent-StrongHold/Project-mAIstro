import { describe, expect, it } from "vitest";
import { safePathAssign } from "../src/lib/safePathAssign.js";

describe("safePathAssign", () => {
  it("assigns a nested dotted path", () => {
    const prev = { style_token: { technique: "ink" } };
    const next = safePathAssign(prev, "style_token.technique", "watercolor");
    expect(next.style_token.technique).toBe("watercolor");
    expect(prev.style_token.technique).toBe("ink");
  });

  it.each(["__proto__", "constructor", "prototype"])(
    "refuses a polluted path segment %s",
    (segment) => {
      const prev = { style_token: { technique: "ink" } };
      const polluted = Object.prototype.polluted;
      const next = safePathAssign(prev, `style_token.${segment}.x`, "boom");
      expect(next).toBe(prev);
      expect(Object.prototype.polluted).toBe(polluted);
      expect(Object.prototype).not.toHaveProperty("x");
    },
  );

  it("refuses when the final segment is __proto__", () => {
    const prev = { a: 1 };
    expect(safePathAssign(prev, "__proto__", { polluted: true })).toBe(prev);
    expect(Object.prototype).not.toHaveProperty("polluted");
  });
});
