import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

// `eslint-config-next` 15.x ships legacy eslintrc configs, not flat ones, so
// they are bridged rather than imported directly. (create-next-app generated
// the flat-import form, which only resolves against the 16.x package.)
const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      "node_modules/**",
      // Monaco, copied out of node_modules by scripts/vendor-monaco.mjs. Vendored
      // third-party code, and 24MB of it — linting it produced 22 errors about a
      // bundle nobody here wrote or can fix.
      "public/monaco/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // The Playwright specs are not React. A fixture is declared as
    // `async ({ page }, use) => { … await use(value) }`, and the react-hooks plugin
    // reads that `use(...)` as React's `use` hook called outside a component — one
    // error, in a directory with no React in it at all.
    files: ["e2e/**/*.ts", "playwright.config.ts"],
    rules: { "react-hooks/rules-of-hooks": "off" },
  },
];

export default eslintConfig;
