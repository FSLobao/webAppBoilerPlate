/**
 * Resolve the declared CSS values that apply to one element at a viewport width.
 *
 * Builds on css-scanner.mjs. Declarations are flattened with the media queries that enclose them, the
 * winning value follows selector specificity and then source order, and `var()` and `calc()` lengths
 * resolve to px. It covers only the selectors and media queries used by the frontend layout tests and
 * never evaluates CSS as code. Constructs outside that subset throw an error instead of being skipped.
 *
 * @module css-cascade
 */

import { readFile } from "node:fs/promises";

import { normalizeCssDeclarations, parseCssRuleNodes } from "./css-scanner.mjs";

const UNSUPPORTED_SELECTOR_CHARACTERS = /[#*\\]/;
const IMPORTANT_VALUE = /!\s*important/i;

/**
 * @typedef {import("./css-scanner.mjs").CssRuleNode} CssRuleNode
 */

/**
 * @typedef {object} CssDeclaration
 * @property {string} selector - Selector text of the rule that declares the property.
 * @property {string} property - Property name, including the leading `--` of custom properties.
 * @property {string} value - Declared value text, trimmed.
 * @property {Array<string>} mediaPreludes - Media queries enclosing the rule, outermost first.
 */

/**
 * @typedef {{kind: "number", amount: number, px: boolean} | {kind: "operator", text: string}} LengthToken
 */

/**
 * @typedef {{amount: number, px: boolean}} LengthValue
 */

/**
 * Read a stylesheet file and flatten its declarations.
 *
 * @param {URL} stylesheetUrl - Location of the stylesheet, read as UTF-8.
 * @returns {Promise<Array<CssDeclaration>>} Declarations in source order.
 * @throws {SyntaxError} If the stylesheet is outside the scanner's supported subset.
 */
export async function readStylesheetDeclarations(stylesheetUrl) {
  return parseStylesheetDeclarations(await readFile(stylesheetUrl, "utf8"));
}

/**
 * Flatten the declarations of a stylesheet source string.
 *
 * @param {string} source - Stylesheet text.
 * @returns {Array<CssDeclaration>} Declarations in source order.
 * @throws {SyntaxError} If the stylesheet is outside the scanner's supported subset.
 */
export function parseStylesheetDeclarations(source) {
  return flattenDeclarations(parseCssRuleNodes(source));
}

/**
 * Flatten declarations with the media queries that enclose them.
 *
 * @param {Array<CssRuleNode>} nodes - Parsed rules.
 * @param {Array<string>} [mediaPreludes] - Media queries enclosing these nodes, outermost first.
 * @returns {Array<CssDeclaration>} Declarations in source order.
 */
function flattenDeclarations(nodes, mediaPreludes = []) {
  return nodes.flatMap((node) => {
    if (node.prelude.startsWith("@")) {
      return flattenDeclarations(node.children, [...mediaPreludes, node.prelude]);
    }
    return normalizeCssDeclarations(node.content).flatMap((declaration) => {
      const colonIndex = declaration.indexOf(":");
      if (colonIndex <= 0) {
        return [];
      }
      return [
        {
          selector: node.prelude,
          property: normalizePropertyName(declaration.slice(0, colonIndex).trim()),
          value: declaration.slice(colonIndex + 1).trim(),
          mediaPreludes
        }
      ];
    });
  });
}

/**
 * Normalize a property name for comparison.
 *
 * Standard property names are case-insensitive and are lowercased. Custom property names (`--name`)
 * are case-sensitive and are kept as written.
 *
 * @param {string} name - Property name as written in the stylesheet or by the caller.
 * @returns {string} The name in the form used for comparison.
 */
function normalizePropertyName(name) {
  return name.startsWith("--") ? name : name.toLowerCase();
}

/**
 * Split a selector into compound selectors, ignoring combinators.
 *
 * Whitespace, `>`, `+`, and `~` separate compounds only outside brackets, parentheses, and strings.
 *
 * @param {string} selector - Selector text from a rule prelude.
 * @returns {Array<string>} Compound selectors in source order.
 * @throws {SyntaxError} If brackets, parentheses, or strings are unbalanced.
 */
function splitCompounds(selector) {
  const compounds = [];
  let current = "";
  let depth = 0;
  let quote = "";
  for (const char of selector) {
    if (quote !== "") {
      if (char === quote) {
        quote = "";
      }
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (char === "(" || char === "[") {
      depth += 1;
    } else if (char === ")" || char === "]") {
      depth -= 1;
      if (depth < 0) {
        throw new SyntaxError(`Unexpected closing bracket in selector: ${selector}`);
      }
    } else if (depth === 0 && /[\s>+~]/.test(char)) {
      if (current !== "") {
        compounds.push(current);
      }
      current = "";
      continue;
    }
    current += char;
  }
  if (depth !== 0 || quote !== "") {
    throw new SyntaxError(`Unbalanced brackets or quotes in selector: ${selector}`);
  }
  if (current !== "") {
    compounds.push(current);
  }
  return compounds;
}

/**
 * Check whether selector text contains a target class selector.
 *
 * @param {string} text - Selector text, a whole selector or one compound.
 * @param {string} target - Single class selector, such as `.table-search-field`.
 * @returns {boolean} True when `target` occurs and is not the prefix of a longer class name.
 */
function containsTarget(text, target) {
  const escapedTarget = target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`${escapedTarget}(?![\\w-])`).test(text);
}

/**
 * Check whether a selector's subject is a target selector, such as `.table-search-field`.
 *
 * Accepted: the target alone, or a selector whose last compound is the target, with ancestors or
 * combinators before it, such as `.top-bar .table-search-field` or `.top-bar > .table-search-field`.
 * A selector whose subject is another element, such as `.table-search-field .table-search-input`,
 * returns false. No pseudo-class, attribute, or pseudo-element on the target is accepted.
 *
 * @param {string} selector - Selector text from a rule prelude.
 * @param {string} target - Single class selector, such as `.table-search-field`.
 * @returns {boolean} True when the subject is exactly `target`; false when the subject is another element.
 * @throws {SyntaxError} If `selector` is a list that contains `target`, or if any compound contains
 * `target` without being exactly `target`.
 */
export function targetsSelector(selector, target) {
  if (selector.includes(",")) {
    if (containsTarget(selector, target)) {
      throw new SyntaxError(`Selector list contains ${target}, which the helper cannot resolve: ${selector}`);
    }
    return false;
  }

  const compounds = splitCompounds(selector);
  for (const compound of compounds) {
    if (compound !== target && containsTarget(compound, target)) {
      throw new SyntaxError(
        `Compound selector contains ${target} without being exactly that target, which the helper cannot resolve: ${selector}`
      );
    }
  }
  return compounds.at(-1) === target;
}

/**
 * Parse the width conditions of a media query prelude.
 *
 * The prelude must be `@media` followed by one or more `(min-width: Npx)` or `(max-width: Npx)`
 * conditions joined by `and`. Keywords are matched case-insensitively. Media types, other features,
 * `or`, `not`, commas, `em`, `rem`, and numbers without `px` are rejected.
 *
 * @param {string} prelude - Media query prelude, such as `@media (max-width: 480px)`.
 * @returns {Array<{bound: "min" | "max", limit: number}>} Width conditions in source order, with limits in px.
 * @throws {SyntaxError} If the prelude is not a supported `@media` query of px width conditions.
 */
function parseMediaWidthConditions(prelude) {
  const body = /^@media\b(.*)$/is.exec(prelude)?.[1];
  const conditions = [];
  for (const part of (body ?? "").trim().split(/\s+and\s+/i)) {
    const condition = /^\((min|max)-width:\s*(\d+(?:\.\d+)?)px\)$/i.exec(part);
    if (condition === null) {
      throw new SyntaxError(
        `Unsupported media query: ${prelude}. Only (min-width: Npx) and (max-width: Npx), joined by and, are supported.`
      );
    }
    conditions.push({ bound: condition[1].toLowerCase(), limit: Number(condition[2]) });
  }
  return conditions;
}

/**
 * Check whether parsed width conditions hold at a viewport width.
 *
 * @param {Array<{bound: "min" | "max", limit: number}>} conditions - Width conditions from {@link parseMediaWidthConditions}.
 * @param {number} width - Viewport width in px.
 * @returns {boolean} True when every condition holds at `width`. An inclusive limit holds at its own width.
 */
function conditionsHold(conditions, width) {
  return conditions.every(({ bound, limit }) => (bound === "min" ? width >= limit : width <= limit));
}

/**
 * Count the classes and attributes in a selector to rank rules during the cascade.
 *
 * @param {string} selector - Selector text from a rule prelude.
 * @returns {number} Number of class and attribute selectors.
 */
function specificityOf(selector) {
  return (selector.match(/\.[\w-]+|\[[^\]]*\]/g) ?? []).length;
}

/**
 * Resolve the value that applies to one property of one element at a viewport width.
 *
 * Only declarations whose selector matches and whose media queries hold at the width are
 * considered. The most specific selector wins, and the later declaration wins a tie. The
 * resolution covers only the selectors and media queries used by these tests.
 *
 * Property names are compared by exact name after case normalization. Shorthand and longhand
 * properties are not expanded: `flex` does not cover `flex-basis`, and `max-block-size` is not
 * normalized to `max-height`. Callers that need a longhand must name it directly.
 *
 * A declaration of `property` whose selector contains `#`, `*`, or `\` is rejected with an error
 * whether or not the selector matches, because the helper does not rank those selectors by
 * specificity (`#` is not counted) and cannot tell whether they apply. Such a declaration is
 * never passed to `matchesSelector`. Declarations of other properties with these characters are
 * ignored. `matchesSelector` runs for the remaining declarations of `property`. Errors it throws,
 * such as the ambiguous-selector errors of {@link targetsSelector}, propagate, so a rule that
 * declares the requested property is never skipped silently. A declaration of `property` that
 * applies at the width and uses `!important` is rejected with a SyntaxError, because the helper
 * does not resolve importance.
 *
 * @param {Array<CssDeclaration>} declarations - Flattened declarations in source order.
 * @param {object} options - Lookup options.
 * @param {(selector: string) => boolean} options.matchesSelector - Selects the rules for the element.
 * @param {string} options.property - CSS property name to resolve, compared case-insensitively.
 * @param {number} options.width - Viewport width in px.
 * @returns {string | undefined} The winning declared value, or undefined when none applies.
 * @throws {SyntaxError} If a media query of a declaration for `property` is unsupported, or if an
 * applicable declaration for `property` uses `!important`.
 * @throws {Error} If a declaration for `property` has a `#`, `*`, or `\` selector, matching or not.
 */
export function valueAtWidth(declarations, { matchesSelector, property, width }) {
  const wanted = normalizePropertyName(property);
  let winner;
  for (const declaration of declarations) {
    if (declaration.property !== wanted) {
      continue;
    }
    if (UNSUPPORTED_SELECTOR_CHARACTERS.test(declaration.selector)) {
      throw new Error(
        `Selector with #, *, or \\ declares ${wanted}, which the helper cannot resolve: ${declaration.selector}`
      );
    }
    if (!matchesSelector(declaration.selector)) {
      continue;
    }
    const widthConditions = declaration.mediaPreludes.map(parseMediaWidthConditions);
    if (!widthConditions.every((conditions) => conditionsHold(conditions, width))) {
      continue;
    }
    if (IMPORTANT_VALUE.test(declaration.value)) {
      throw new SyntaxError(
        `!important is not supported, so the helper cannot resolve ${wanted}: ${declaration.selector} { ${wanted}: ${declaration.value} }`
      );
    }
    const specificity = specificityOf(declaration.selector);
    if (winner === undefined || specificity >= winner.specificity) {
      winner = { specificity, value: declaration.value };
    }
  }
  return winner?.value;
}

/**
 * Collect the custom properties declared on `:root` outside media queries.
 *
 * @param {Array<CssDeclaration>} declarations - Flattened declarations in source order.
 * @returns {Map<string, string>} Custom property values by name. A later declaration replaces an earlier one.
 */
export function customPropertiesOf(declarations) {
  return new Map(
    declarations
      .filter(
        (declaration) =>
          declaration.selector === ":root" &&
          declaration.mediaPreludes.length === 0 &&
          declaration.property.startsWith("--")
      )
      .map((declaration) => [declaration.property, declaration.value])
  );
}

/**
 * Resolve a declared length to px.
 *
 * Each `var(--name)` is replaced by the declared value of that custom property, and the `calc()`
 * body is evaluated. Terms are px lengths and unitless numbers combined with `+`, `-`, `*`, `/`, and
 * parentheses. Mixed units and unsupported syntax are rejected.
 *
 * @param {string | undefined} value - Declared length, such as `172px` or `calc(var(--spacing-scale-4x) * 3)`.
 * @param {Map<string, string>} customProperties - Custom property values by name, from {@link customPropertiesOf}.
 * @returns {string | undefined} The resolved length, such as `120px`, or undefined when `value` is undefined.
 * @throws {ReferenceError} If a referenced custom property is not declared.
 * @throws {SyntaxError} If the expression is not a supported px length.
 */
export function resolveLengthPx(value, customProperties) {
  if (value === undefined) {
    return undefined;
  }

  const substituted = value.trim().replace(/var\((--[\w-]+)\)/g, (_match, name) => {
    if (!customProperties.has(name)) {
      throw new ReferenceError(`Custom property ${name} is not declared.`);
    }
    return `(${customProperties.get(name)})`;
  });
  const body = /^calc\((.*)\)$/s.exec(substituted)?.[1] ?? substituted;
  return `${evaluateLengthExpression(body)}px`;
}

/**
 * Evaluate a `calc()` body that must resolve to a px length.
 *
 * @param {string} text - Expression body without the `calc()` wrapper.
 * @returns {number} The length in px.
 * @throws {SyntaxError} If the expression is malformed, mixes units, or does not resolve to px.
 */
function evaluateLengthExpression(text) {
  const cursor = { tokens: tokenizeLengthExpression(text), index: 0 };
  const result = parseSum(cursor);
  if (cursor.index !== cursor.tokens.length) {
    throw new SyntaxError(`Unexpected trailing token in length expression: ${text}`);
  }
  if (!result.px) {
    throw new SyntaxError(`Length expression does not resolve to px: ${text}`);
  }
  return result.amount;
}

/**
 * Split a `calc()` body into numbers, px lengths, and operators.
 *
 * @param {string} text - Expression body without the `calc()` wrapper.
 * @returns {Array<LengthToken>} Tokens in source order.
 * @throws {SyntaxError} If the text contains an unsupported token.
 */
function tokenizeLengthExpression(text) {
  const source = text.trim();
  const pattern = /\s*(?:(\d+(?:\.\d+)?)(px)?|([()+*/-]))/y;
  const tokens = [];
  let index = 0;

  while (index < source.length) {
    pattern.lastIndex = index;
    const match = pattern.exec(source);
    if (match === null) {
      throw new SyntaxError(`Unsupported length expression: ${source}`);
    }
    tokens.push(
      match[3] === undefined
        ? { kind: "number", amount: Number(match[1]), px: match[2] !== undefined }
        : { kind: "operator", text: match[3] }
    );
    index = pattern.lastIndex;
  }
  return tokens;
}

/**
 * Return the operator at the cursor without consuming it.
 *
 * @param {{tokens: Array<LengthToken>, index: number}} cursor - Token stream and read position.
 * @returns {string | undefined} The operator text, or undefined for a number or the end of input.
 */
function peekOperator(cursor) {
  const token = cursor.tokens[cursor.index];
  return token?.kind === "operator" ? token.text : undefined;
}

/**
 * Parse a sum or difference of products.
 *
 * @param {{tokens: Array<LengthToken>, index: number}} cursor - Token stream and read position.
 * @returns {LengthValue} The parsed value.
 * @throws {SyntaxError} If a sum mixes px lengths and unitless numbers.
 */
function parseSum(cursor) {
  let left = parseProduct(cursor);
  let operator = peekOperator(cursor);
  while (operator === "+" || operator === "-") {
    cursor.index += 1;
    const right = parseProduct(cursor);
    if (left.px !== right.px) {
      throw new SyntaxError("Cannot add or subtract a px length and a unitless number.");
    }
    const amount = operator === "+" ? left.amount + right.amount : left.amount - right.amount;
    left = { amount, px: left.px };
    operator = peekOperator(cursor);
  }
  return left;
}

/**
 * Parse a product or quotient of factors.
 *
 * @param {{tokens: Array<LengthToken>, index: number}} cursor - Token stream and read position.
 * @returns {LengthValue} The parsed value.
 * @throws {SyntaxError} If two px lengths are multiplied or the divisor is a px length or zero.
 */
function parseProduct(cursor) {
  let left = parseFactor(cursor);
  let operator = peekOperator(cursor);
  while (operator === "*" || operator === "/") {
    cursor.index += 1;
    const right = parseFactor(cursor);
    if (operator === "*") {
      if (left.px && right.px) {
        throw new SyntaxError("Cannot multiply two px lengths.");
      }
      left = { amount: left.amount * right.amount, px: left.px || right.px };
    } else {
      if (right.px || right.amount === 0) {
        throw new SyntaxError("Division requires a non-zero unitless divisor.");
      }
      left = { amount: left.amount / right.amount, px: left.px };
    }
    operator = peekOperator(cursor);
  }
  return left;
}

/**
 * Parse one number, px length, or parenthesized sum.
 *
 * @param {{tokens: Array<LengthToken>, index: number}} cursor - Token stream and read position.
 * @returns {LengthValue} The parsed value.
 * @throws {SyntaxError} If the input ends early, contains an unexpected token, or leaves a parenthesis open.
 */
function parseFactor(cursor) {
  const token = cursor.tokens[cursor.index];
  if (token === undefined) {
    throw new SyntaxError("Unexpected end of length expression.");
  }
  cursor.index += 1;

  if (token.kind === "number") {
    return { amount: token.amount, px: token.px };
  }
  if (token.text !== "(") {
    throw new SyntaxError(`Unexpected operator ${token.text} in length expression.`);
  }

  const inner = parseSum(cursor);
  if (peekOperator(cursor) !== ")") {
    throw new SyntaxError("Missing closing parenthesis in length expression.");
  }
  cursor.index += 1;
  return inner;
}
