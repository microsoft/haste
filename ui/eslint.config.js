// ESLint flat configuration.
//
// Replaces `.eslintrc.cjs`. ESLint 9 no longer reads the `.eslintrc.*` format
// and stops with "couldn't find an eslint.config.(js|mjs|cjs) file", so
// `npm run lint` fails before examining a single source file -- the lint
// script has been reporting a configuration error rather than passing.
//
// A direct translation of the previous configuration: same extends, same
// rules, same ignores, same React version. Nothing here is an opinion about
// how this project should be linted; it is the old file expressed in the
// format the installed ESLint understands.
import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2020,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: "18.2" } },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...react.configs.recommended.rules,
      // The JSX transform means React need not be in scope.
      ...react.configs["jsx-runtime"].rules,
      ...reactHooks.configs.recommended.rules,
      "react/jsx-no-target-blank": "off",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  {
    // Node runs the test files and the build tooling, so they see Node
    // globals rather than browser ones.
    files: [
      "**/*.test.js",
      "vite.config.js",
      "*.config.js",
      "scripts/**/*.js",
    ],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
];
