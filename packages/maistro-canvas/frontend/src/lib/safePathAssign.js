/**
 * Recursively assign ``value`` at a dotted ``path`` under ``root``.
 *
 * Returns the previous root unchanged when any path segment names the
 * prototype chain (__proto__/constructor/prototype), so a crafted path
 * cannot rewrite Object.prototype (js/prototype-pollution-utility).
 */

/** True when ``key`` is a safe own-property name (not a prototype-chain name). */
export function isSafeObjectKey(key) {
  return key !== "__proto__" && key !== "constructor" && key !== "prototype";
}

export function safePathAssign(root, path, value) {
  const keys = String(path).split(".");
  const next = { ...root };
  let obj = next;
  for (let i = 0; i < keys.length - 1; i++) {
    const segment = keys[i];
    if (!isSafeObjectKey(segment)) {
      return root;
    }
    const child = obj[segment];
    const copy = child && typeof child === "object" ? { ...child } : {};
    obj[segment] = copy;
    obj = copy;
  }
  const last = keys[keys.length - 1];
  if (!isSafeObjectKey(last)) {
    return root;
  }
  obj[last] = value;
  return next;
}
