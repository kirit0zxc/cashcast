import js from "@eslint/js";
import tseslint from "typescript-eslint";

// Плоский конфиг ESLint 9. Базовые рекомендованные правила JS + TypeScript.
export default tseslint.config(
  { ignores: ["dist", "src/vendor"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module" },
  },
);
