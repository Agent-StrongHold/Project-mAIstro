/**
 * Random ids for messages, sessions and slides, from the CSPRNG in every
 * context the app is served from.
 *
 * #1344 moved these ids off `Math.random` and onto `crypto.randomUUID()`,
 * which exists only in a secure context (`https://`, or `http://localhost`).
 * Agent Conductor's own documented deployment is a homelab box reached over
 * plain HTTP at a LAN hostname, and the browser e2e harness serves it the
 * same way (`http://hive:8101`), so there `crypto.randomUUID` is undefined
 * and the first render of Chat or DeckBuilder threw "crypto.randomUUID is
 * not a function" into the error boundary. `crypto.getRandomValues` is the
 * one Web Crypto entry point available in insecure contexts as well, and it
 * is the same CSPRNG `randomUUID` reads from.
 */

/** Twelve lowercase hex characters (48 bits) from the CSPRNG. */
export function randomId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
