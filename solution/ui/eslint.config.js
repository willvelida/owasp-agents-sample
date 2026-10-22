// XSS controls (binding): event data reaches the DOM only through {{ }} interpolation. Vue's runtime writes
// innerHTML for v-html and for innerHTML/outerHTML bindings through a pass-through Trusted Types policy, so the
// CSP alone does not stop those sinks; these rules do.
import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";

const htmlSinks = ["innerHTML", "outerHTML", "insertAdjacentHTML"];
const sinkMessage = "Render data only through {{ }} interpolation; HTML sinks are banned (XSS).";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/", "test-results/", "playwright-report/", "coverage/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    files: ["**/*.vue"],
    languageOptions: { parserOptions: { parser: tseslint.parser, extraFileExtensions: [".vue"] } },
  },
  {
    files: ["**/*.{ts,vue,js}"],
    languageOptions: {
      // Declared so no-implied-eval can see string timers; vue-tsc checks undefined names instead of no-undef.
      globals: {
        window: "readonly",
        document: "readonly",
        setTimeout: "readonly",
        setInterval: "readonly",
        execScript: "readonly",
      },
    },
    rules: {
      // Whitespace inside text elements is visible (white-space: pre-wrap), so do not force line breaks around content.
      "vue/singleline-html-element-content-newline": "off",
      "vue/multiline-html-element-content-newline": "off",
      "no-undef": "off",
      "vue/no-v-html": "error",
      "vue/no-restricted-v-bind": [
        "error",
        { argument: "/^(inner-?html|outer-?html|srcdoc)$/i", message: sinkMessage },
      ],
      "vue/no-restricted-syntax": [
        "error",
        {
          selector: "VAttribute[directive=true][key.name.name='bind'][key.argument=null]",
          message: "Object v-bind is banned: a bound object could set innerHTML (XSS).",
        },
        {
          selector: "VAttribute[directive=true][key.name.name='bind'] > VDirectiveKey > VExpressionContainer",
          message: "Dynamic v-bind arguments are banned: a computed name could be innerHTML (XSS).",
        },
      ],
      "no-restricted-properties": [
        "error",
        ...htmlSinks.map((property) => ({ property, message: sinkMessage })),
        { object: "document", property: "write", message: sinkMessage },
        { object: "document", property: "writeln", message: sinkMessage },
        { object: "window", property: "localStorage", message: "Never use localStorage (tokens stay in MSAL sessionStorage)." },
      ],
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Never use localStorage (tokens stay in MSAL sessionStorage)." },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: `MemberExpression[computed=true][property.value=/^(${htmlSinks.join("|")})$/]`,
          message: sinkMessage,
        },
        { selector: "CallExpression[callee.name='Function'], NewExpression[callee.name='Function']", message: "No dynamic code." },
      ],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
    },
  },
);
