---
name: jsTsDevGuide
description: "Use when creating, editing, testing, or reviewing JavaScript, TypeScript, JSX, or TSX code. Covers type safety, async errors, JSDoc/TSDoc, comment scope, separators, testing, and existing tooling."
applyTo: "**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"
---

# JavaScript and TypeScript Development Guide

## Scope and Precedence

- Read the relevant project contract, reference documentation, and neighboring implementation before editing. Contracts govern behavior; this guide governs JavaScript/TypeScript conventions.
- Apply these rules to new or modified code. Do not mass-reformat unrelated code or change public interfaces, runtime targets, module systems, or frameworks without an approved requirement.
- Follow [the documentation guide](./docsDevGuide.instructions.md) for Markdown documentation and [the JSON guide](./jsonDevGuide.instructions.md) for JSON files. Follow [modular-script-development](../skills/modular-script-development/SKILL.md) for project scripting.

## Runtime, Dependencies, and Tooling

- Inspect the owning package manifest, lockfile, runtime version declarations, compiler configuration, and CI before choosing commands or language features.
- Use the package manager and versions selected by the owning package. Preserve its lockfile and use the manager's reproducible install mode in CI. Never edit a generated lockfile manually or create a competing lockfile.
- Use existing package scripts and local tools for linting, formatting, type-checking, building, and testing. Do not assume that ESLint, Prettier, TypeScript, or a particular test runner is installed.
- Prefer the existing formatter and lint configuration over manual formatting preferences. If introducing tooling is part of the approved scope, prefer ESLint for code checks, typescript-eslint for TypeScript-aware rules, and one formatter such as Prettier. Keep formatting ownership unambiguous.
- Search existing implementation and official documentation for integrated capabilities before adding a dependency or custom script. Add dependencies only when existing tools or platform APIs cannot reasonably meet the requirement.
- Add or remove dependencies through the selected package manager. Install or restore dependencies only after manifest changes or a missing-dependency validation failure.
- Preserve the existing ESM/CommonJS boundary. Prefer ESM for new modules where the runtime and package configuration support it; do not migrate unrelated modules.

## Code Structure and Style

- Use `camelCase` for variables and functions, `PascalCase` for classes, types, and components, and `UPPER_SNAKE_CASE` for module-level constants that represent fixed configuration or domain values. Preserve established public names.
- Prefer `const`; use `let` only for reassignment. Do not introduce `var`.
- Keep functions cohesive, entry points thin, and dependencies explicit. Avoid mutable module-level state and side effects during import unless required and documented.
- Reuse existing helpers and framework conventions. Do not add wrappers, factories, or classes without a concrete responsibility.
- Use strict equality, explicit handling of absent values, and guards that preserve valid values such as `0`, `false`, and empty strings. Use `??` instead of `||` when only `null` and `undefined` should trigger a default.
- Use supported platform APIs and established event/resource cleanup patterns. Do not introduce browser APIs into server-only code or server dependencies into browser bundles.
- Keep secrets out of client code, source maps, logs, and examples. Treat all browser-delivered configuration as public.
- Validate untrusted input at system boundaries using existing validation helpers. TypeScript types and assertions do not perform runtime validation.
- Avoid unsafe HTML insertion and dynamic code evaluation. Prefer text APIs and framework escaping; use the project's approved sanitization when HTML is required.

## Types and Interfaces

- For new TypeScript configurations, enable `strict`. In existing packages, preserve strictness and fix affected types rather than weakening compiler options.
- Explicitly type exported function parameters and return values, public methods, and stable boundary models. Allow inference for obvious local values and callbacks.
- Prefer `unknown` over `any` for untrusted or unspecified values, then narrow with guards. Avoid double assertions, unnecessary casts, and non-null assertions that conceal missing checks.
- Use discriminated unions for distinct states and `readonly` where mutation is not part of the contract. Handle union variants exhaustively when all cases must be covered.
- Use `import type` for type-only dependencies when supported by the project configuration.
- In JavaScript, use JSDoc types for public contracts and non-obvious values. Reuse named types through supported imports or typedefs rather than duplicating models.
- Use the existing JavaScript type-checking setup where configured. Do not add repository-wide `checkJs` or compiler migrations without approval.
- Prefer correcting code to suppressing diagnostics. If unavoidable, use a narrowly scoped, justified suppression; prefer `@ts-expect-error` to `@ts-ignore` when an expected error must be retained.

## Errors, Async Work, and Resources

- Use `async`/`await` where it clarifies promise-based code. Await or return promises; intentional background work must have explicit error handling and an owner for its lifecycle.
- Catch only failures the current layer can handle. JavaScript catch values may be non-`Error` values; narrow them before accessing properties.
- Never swallow errors or return success-shaped defaults on failure. Follow the repository's logging and user-notification conventions without exposing sensitive data.
- Throw meaningful `Error` instances or existing domain errors. Preserve the original cause when supported by the configured runtime.
- For `fetch`, check HTTP status explicitly; HTTP error responses do not automatically reject the promise.
- Follow existing timeout, cancellation, and cleanup conventions. Release listeners, timers, subscriptions, connections, and other resources on success, failure, and cancellation.
- Preserve required ordering. Run independent operations concurrently only when shared state, resource limits, and failure behavior permit it.

## In-Code Documentation

### Syntax and Placement

- Write documentation comments in English using `/** ... */` immediately before the declaration they document. JavaScript and TypeScript do not use Python-style docstrings inside function bodies.
- Use JSDoc for JavaScript. Use TSDoc-compatible descriptions and tags for TypeScript, subject to the project's documentation tooling.
- Start with one imperative summary sentence ending in a period. Separate additional contract details from the summary with a blank comment line.
- Document purpose, units, constraints, defaults, mutation, side effects, ownership, error conditions, and cancellation where applicable. Do not merely restate identifiers or implementation steps.
- In TypeScript, keep types in signatures; do not repeat `{Type}` annotations in documentation tags. In JavaScript, include types when needed for the contract or type checker.
- Use applicable tags only: `@param`, `@returns`, `@throws`, `@example`, `@deprecated`, and `@see` or `{@link ...}`. In TypeScript, use `@remarks` and `@typeParam` when useful. Do not add empty tags.
- Match parameter names to the signature. Use `@param name - Description.` in TypeScript and `@param {Type} name - Description.` in JavaScript.
- Document meaningful return semantics, not merely the return type. Omit `@returns` for a function with no meaningful return value.
- Document deliberate exceptions and relevant propagated failures at public boundaries. Distinguish synchronous throws from promise rejections; `@throws` documents behavior but does not restrict thrown values.
- Update documentation in the same edit as signature or behavior changes. Re-read it after renaming parameters; do not use blind replacements inside prose.

### Required Scope

- Every authored module needs a file-level documentation comment describing its purpose, principal exports or entry point, and import-time side effects, if any. Place it after any required shebang or license notice and before imports; use module/file tags supported by the configured documentation tool.
- Document exported functions, classes, components, hooks, public methods, interfaces, and type aliases. Describe component props, hook results, and lifecycle behavior at their owning declarations.
- Give private helpers at least a one-line documentation summary. Do not mechanically annotate every inline callback or local variable.
- Document constructor inputs on the constructor declaration when needed for parameter association; keep class-level purpose and invariants on the class. Do not duplicate the same prose in both places.
- Document exported constants, interface members, and class fields directly above their declarations when they define a public contract. Explain units, allowed values, or invariants rather than repeating the type.
- Skip generated and vendored code. Test modules need a brief purpose comment, but test cases and fixtures may use descriptive names instead of repetitive API documentation.

### Examples

JavaScript uses JSDoc type annotations:

```js
/**
 * Convert seconds to milliseconds.
 *
 * @param {number} seconds - A finite, non-negative duration in seconds.
 * @returns {number} The duration in milliseconds.
 * @throws {RangeError} If the input or resulting duration is not finite and non-negative.
 */
```

TypeScript obtains types from the declaration:

```ts
/**
 * Convert seconds to milliseconds.
 *
 * @param seconds - A finite, non-negative duration in seconds.
 * @returns The duration in milliseconds.
 * @throws {@link RangeError}
 * If the input or resulting duration is not finite and non-negative.
 */
```

These are documentation templates, not implementations or evidence of validation behavior.

## Comments and Layout

- Comments explain non-obvious intent, constraints, or tradeoffs, not what the next statement does. Use complete sentences and a space after `//`.
- Prefer standalone `//` comments for implementation notes and `/** ... */` for API documentation. Follow the formatter for indentation, wrapping, and inline spacing; do not copy Python spacing rules.
- Do not introduce separator or banner comments such as `// -----`, `// =====`, or decorative block borders between declarations. Use normal blank lines.
- For files over roughly 300 lines, prefer splitting cohesive modules. If grouping is still useful, use `// #region Name` and `// #endregion` sparingly, with one nesting level only.
- Preserve existing separator comments unless cleanup is explicitly requested. Do not leave dead code or commented-out implementations.
- Use `// TODO(name): ...` for actionable pending work, with enough context or an issue reference to act on it.
- Keep architectural decisions in project documentation rather than long code comments.

## Testing and Verification

- Use the owning package's existing test runner and conventions. Do not add a second runner solely for a change.
- Add regression tests for bug fixes. Cover the changed contract, critical error paths, and relevant boundaries without testing incidental implementation details.
- Keep tests deterministic and isolated. Control clocks, timers, randomness, network calls, and shared state; test both promise resolution and rejection when relevant.
- For UI changes, verify observable behavior, keyboard/accessibility behavior, loading, empty, and error states as applicable. Use existing browser tests for relevant interactions.
- Run the smallest relevant test, lint, formatter check, type-check, and build commands required by the affected package. Apply the existing formatter to changed files only.
- Use type-aware linting when already configured; rules such as `no-floating-promises` complement TypeScript's checks. Introducing it across a package is a separate configuration decision.
- Report exact commands, results, and checks not run. Do not claim validation from an unexecuted example or fix unrelated baseline failures.
- Update affected usage documentation when commands, setup, public behavior, or dependencies change.

## References

These sources inform the guide; repository-specific documentation scope and separator rules above are local conventions.

- [MDN JavaScript code style guidance](https://developer.mozilla.org/en-US/docs/MDN/Writing_guidelines/Code_style_guide/JavaScript)
- [JSDoc syntax and placement](https://jsdoc.app/about-getting-started)
- [JSDoc module documentation](https://jsdoc.app/tags-module)
- [TypeScript-supported JSDoc](https://www.typescriptlang.org/docs/handbook/jsdoc-supported-types.html)
- [TSDoc parameter tags](https://tsdoc.org/pages/tags/param/)
- [TSDoc exception documentation](https://tsdoc.org/pages/tags/throws/)
- [TypeScript strict checking](https://www.typescriptlang.org/tsconfig/strict.html)
- [typescript-eslint typed linting](https://typescript-eslint.io/getting-started/typed-linting/)
