/**
 * Test the users table search close button, chip container and search input layout.
 *
 * Checks that the close button keeps its size, the chips wrap and shrink, and the search
 * input keeps a minimum width. Rules are read from styles.css with simple regular
 * expressions over top-level rules.
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
 * @param {string} selector - Exact selector text, such as `.table-search-close`.
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

test("close button declares flex 0 0 auto so the search field cannot shrink it", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-close");
  const flex = declarations.get("flex");
  const flexShrink = declarations.get("flex-shrink");

  assert.ok(
    flex === "0 0 auto" || flexShrink === "0",
    `Close button must declare flex: 0 0 auto or flex-shrink: 0; found flex=${flex}, flex-shrink=${flexShrink}.`
  );
});

test("close button keeps a min-width equal to its width token", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-close");

  assert.equal(
    declarations.get("min-width"),
    "var(--button-size)",
    "Close button min-width must equal the width token used by .br-button.circle."
  );
});

test("chips container wraps onto new lines and can shrink below its content width", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chips");

  assert.equal(declarations.get("flex-wrap"), "wrap");
  assert.equal(declarations.get("min-width"), "0", "Chips container must declare min-width: 0.");
});

test("chips container shrinks instead of taking free space", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chips");

  assert.equal(declarations.get("flex"), "0 1 auto");
});

test("search input declares a min-width other than zero", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-input");
  const minWidth = declarations.get("min-width");

  assert.ok(minWidth !== undefined, "Search input must declare min-width.");
  assert.doesNotMatch(minWidth, /^0(px)?$/, "Search input min-width must not be 0.");
});

test("chip text can break inside the chip instead of overflowing it", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chip-text");

  assert.equal(declarations.get("white-space"), "normal");
  assert.equal(declarations.get("overflow-wrap"), "anywhere");
});

test("chip grows with wrapped text and stays within the chips container", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chip.br-button");

  assert.equal(declarations.get("height"), "auto");
  assert.equal(declarations.get("min-height"), "var(--button-size)");
  assert.equal(declarations.get("max-width"), "100%");
});
