import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

// `eslint-config-next` 15.x ships legacy eslintrc configs, not flat ones, so
// they are bridged rather than imported directly. (create-next-app generated
// the flat-import form, which only resolves against the 16.x package.)
const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  { ignores: [".next/**", "out/**", "build/**", "next-env.d.ts", "node_modules/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default eslintConfig;
