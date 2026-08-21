import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // ── Ratcheted, not suppressed ────────────────────────────────────────
      // These are demoted to warnings and held under `--max-warnings 96` in
      // package.json, so the count can shrink and never grow. Every other rule
      // — no-unused-vars, no-empty, prefer-const and the rest of the two
      // recommended sets — stays a hard error at zero.
      //
      // They are demoted because each needs the running app to change safely,
      // not because they are wrong:
      //
      //   no-explicit-any (48)  — 30 are Dashboard's widget-config blobs, whose
      //                           real shape is decided by the backend widget
      //                           schema. Typing them off the current call
      //                           sites would encode a guess as a contract.
      //   set-state-in-effect   — the `useEffect(() => { void load(); }, [load])`
      //     (36)                  data-loading idiom, 36 times over. The fix is
      //                           a real fetch-on-mount refactor per page; a
      //                           mechanical one risks turning a stale value
      //                           into an infinite render loop, and this
      //                           package has no test that would catch that.
      //   purity (2),           — accumulator-in-`.map()` and `Date.now()` in a
      //   immutability (2)        state initializer. Both look correct on
      //                           inspection; the compiler cannot prove it, and
      //                           "looks correct" is not why a rule gets turned
      //                           off, so they stay visible.
      //   exhaustive-deps (3)   — already warnings upstream.
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/immutability": "warn",
    },
  },
);
