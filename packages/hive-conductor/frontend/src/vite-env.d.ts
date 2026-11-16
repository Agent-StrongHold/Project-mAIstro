/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** #1420: build-time switch for production RUM collection. Off unless "true". */
  readonly VITE_RUM_ENABLED?: string;
  /** #1420: session sampling rate, 0..1 (default 1). */
  readonly VITE_RUM_SAMPLE_RATE?: string;
  /** #1420: collector endpoint; same-origin by default. */
  readonly VITE_RUM_ENDPOINT?: string;
  /** #1420: build identifier stamped on every RUM event. */
  readonly VITE_RUM_BUILD_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
