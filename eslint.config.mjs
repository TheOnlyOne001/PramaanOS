// ESLint 9 flat config for the plain-JS front ends in web/ (no build step, ES modules in the browser).
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["web/verify/vendor/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["web/**/*.js"],
    languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: { ...globals.browser } },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", caughtErrors: "none" }],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "prefer-const": "error",
      "no-var": "error",
    },
  },
  {
    // Classic (non-module) scripts loaded with <script src>, written in ES5 style with a CommonJS export
    // guard so tests can require them. Owned by the voice and verifier modules.
    files: ["web/shared/voice-client.js", "web/verify/verify.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.browser, module: "readonly" } },
    rules: { "no-var": "off", "no-empty": ["error", { allowEmptyCatch: true }] },
  },
];
