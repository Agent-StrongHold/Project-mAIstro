import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const interactiveTag = /<(div|span|td|li|g)\b(?:(?:[^>]|=>))*?(?<![=])>/gs;
const allowed = /(?:aria-hidden\s*=\s*["']true["']|className\s*=\s*["'][^"']*(?:modal-overlay|modal-content|drawer-backdrop|drawer-overlay)|onClick\s*=\s*\{\s*\(?\s*e\s*\)?\s*=>\s*e\.stopPropagation\(\))/;

function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return files(path);
    return /\.(tsx|jsx)$/.test(entry.name) ? [path] : [];
  });
}

const violations = [];
for (const file of files(root)) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(interactiveTag)) {
    const tag = match[0];
    if (!/\bonClick\s*=/.test(tag) || allowed.test(tag)) continue;
    if (match[1] === "g" && /role\s*=\s*["']button["']/.test(tag) && /tabIndex\s*=\s*\{?0/.test(tag) && /onKeyDown\s*=/.test(tag)) continue;
    const line = source.slice(0, match.index).split("\n").length;
    violations.push(`${file}:${line} <${match[1]}> has a click handler without a keyboard equivalent`);
  }
}

if (violations.length) {
  console.error(violations.join("\n"));
  process.exitCode = 1;
} else {
  console.log("keyboard control check passed: no click-only generic controls found");
}
