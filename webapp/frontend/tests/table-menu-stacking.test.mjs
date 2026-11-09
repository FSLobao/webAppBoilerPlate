/**
 * Test the stacking and reserved space that keep the users table menu button clickable.
 *
 * With the search field open, the ellipsis button must receive pointer events. Rules are
 * read from styles.css with simple regular expressions over top-level rules.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * Read styles.css with CSS comments removed.
 *
 * @returns {Promise<string>} The stylesheet source without comments.
 */
async function readStylesheet() {
  const source = await readFile(new URL("../styles.css", import.meta.url), "utf8");
  return source.replace(/\/\*[\s\S]*?\*\//g, "");
}

/**
 * Return the declarations of the last top-level rule for an exact selector.
 *
 * @param {string} stylesheet - Stylesheet source without comments.
 * @param {string} selector - Exact selector text, such as `.table-menu-anchor`.
 * @returns {Map<string, string>} Property names mapped to their declared values.
 */
function declarationsFor(stylesheet, selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rulePattern = new RegExp(`(?:^|[{}])\\s*${escapedSelector}\\s*\\{([^{}]*)\\}`, "g");
  const bodies = [...stylesheet.matchAll(rulePattern)].map((match) => match[1]);
  assert.ok(bodies.length > 0, `Expected a top-level rule for ${selector}.`);

  const declarations = new Map();
  for (const declaration of bodies.at(-1).split(";")) {
    const colonIndex = declaration.indexOf(":");
    if (colonIndex > 0) {
      declarations.set(
        declaration.slice(0, colonIndex).trim(),
        declaration.slice(colonIndex + 1).trim()
      );
    }
  }
  return declarations;
}

/**
 * Split a CSS value into top-level tokens, keeping parenthesized functions whole.
 *
 * @param {string} value - CSS value, such as `0 calc(a + b) 0 var(--x)`.
 * @returns {string[]} Top-level tokens in source order.
 */
function splitTopLevelTokens(value) {
  const tokens = [];
  let depth = 0;
  let current = "";
  for (const char of value) {
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;
    if (depth === 0 && /\s/.test(char)) {
      if (current !== "") tokens.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  if (current !== "") tokens.push(current);
  return tokens;
}

/**
 * Return the integer z-index declared by a rule.
 *
 * @param {Map<string, string>} declarations - Declarations of one rule.
 * @param {string} selector - Selector named in assertion messages.
 * @returns {number} The declared z-index.
 */
function zIndexFor(declarations, selector) {
  const value = declarations.get("z-index");
  assert.ok(value !== undefined, `${selector} must declare a z-index.`);
  assert.match(value, /^\d+$/, `${selector} z-index must be an integer.`);
  return Number(value);
}

test("menu anchor is positioned and declares a z-index for the ellipsis stacking", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-menu-anchor");

  assert.equal(declarations.get("position"), "relative");
  zIndexFor(declarations, ".table-menu-anchor");
});

test("search field declares a z-index that the menu anchor must exceed", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-field");

  zIndexFor(declarations, ".table-search-field");
});

test("menu anchor stacks above the search field so the ellipsis stays clickable", async () => {
  const stylesheet = await readStylesheet();
  const anchorZIndex = zIndexFor(
    declarationsFor(stylesheet, ".table-menu-anchor"),
    ".table-menu-anchor"
  );
  const fieldZIndex = zIndexFor(
    declarationsFor(stylesheet, ".table-search-field"),
    ".table-search-field"
  );

  assert.ok(
    anchorZIndex > fieldZIndex,
    `Menu anchor z-index ${anchorZIndex} must exceed search field z-index ${fieldZIndex}.`
  );
});

test("search field reserves room for the menu button so the close button stays uncovered", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-field");
  const reservedRight = "calc(var(--spacing-scale-2x) + var(--spacing-scale-6x))";
  const rightPaddings = [];

  if (declarations.has("padding")) {
    const tokens = splitTopLevelTokens(declarations.get("padding"));
    rightPaddings.push(tokens.length === 1 ? tokens[0] : tokens[1]);
  }
  if (declarations.has("padding-right")) {
    rightPaddings.push(declarations.get("padding-right"));
  }

  assert.ok(rightPaddings.length > 0, "Search field must declare padding or padding-right.");
  for (const rightPadding of rightPaddings) {
    assert.equal(rightPadding, reservedRight, "Search field right padding must reserve the menu button room.");
  }
});
