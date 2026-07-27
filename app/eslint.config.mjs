import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

/**
 * Module boundaries, enforced.
 *
 * The same rules the API enforces in tests/test_module_boundaries.py, applied here by
 * lint. A modular monolith is only modular while something checks — an editor's
 * auto-import will happily reach into another module's internals.
 *
 *   1. A module imports another module through its root (`@/modules/units`), never a
 *      file inside it. Its own files it reaches relatively (`./geometry`).
 *   2. `core` is the shared kernel: modules depend on it, never the reverse.
 *   3. Routes under `src/app` wire modules together and go through the same front door.
 */
const crossModuleReach = {
  group: ["@/modules/*/*"],
  message:
    "Import the module root (@/modules/<name>) and use what its index.ts exports. Within a module, use a relative import.",
};

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/modules/**/*.{ts,tsx}", "src/app/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", { patterns: [crossModuleReach] }],
    },
  },
  {
    files: ["src/core/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/modules/*", "@/modules/*/*"],
              message:
                "core is the shared kernel: modules depend on it, not the other way round.",
            },
          ],
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
