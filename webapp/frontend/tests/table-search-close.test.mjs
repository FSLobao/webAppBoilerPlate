/**
 * Test the users table search close button, chip container and search input layout.
 *
 * Checks that the close button keeps its size, the chips wrap and shrink, the search input keeps
 * a minimum width, the search field grows to fit wrapped chips, the chips area keeps padding and
 * scrolls, an empty chips area takes no layout space, the search field keeps its items centered, the
 * search input has no bottom margin, and the chips follow the close button in the markup.
 * Rules are read from styles.css with simple regular expressions over top-level rules; markup is
 * read from index.html.
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

test("search field grows to fit wrapped chips", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-field");

  assert.notEqual(
    declarations.get("inset"),
    "0",
    "Search field must not be pinned top and bottom with inset: 0."
  );
  assert.ok(
    declarations.get("height") === "auto" || declarations.has("min-height"),
    "Search field must declare height: auto or min-height so wrapped chips can grow it."
  );
  assert.equal(
    declarations.has("bottom"),
    false,
    "Search field must not declare bottom, so its height is not pinned at both edges."
  );
});

test("search input has no bottom margin so it stays centered on the close button", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-input");
  const marginBottom = declarations.get("margin-bottom");

  assert.ok(marginBottom !== undefined, "Search input must declare margin-bottom.");
  assert.match(
    marginBottom,
    /^0(px)?$/,
    "Search input must declare margin-bottom: 0 to override the GOV.BR .input bottom margin."
  );
});

test("search field keeps its items centered", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-field");

  assert.equal(
    declarations.get("align-items"),
    "center",
    "Search field must declare align-items: center so the input and close button share a vertical center."
  );
});

test("chips area scrolls after about three lines", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chips");

  assert.ok(
    declarations.get("overflow-y") === "auto" || declarations.get("overflow") === "auto",
    "Chips container must declare overflow-y: auto."
  );
  assert.equal(
    declarations.get("max-height"),
    "calc(var(--spacing-scale-4x) * 3 + var(--spacing-scale-half) * 2 + var(--spacing-scale-base) * 2)",
    "Chips container max-height must cap three lines of small chips, two row gaps, and top and bottom padding."
  );
});

test("chips container keeps padding so focus outlines are not clipped", async () => {
  const declarations = declarationsFor(await readStylesheet(), ".table-search-chips");

  assert.equal(
    declarations.get("padding"),
    "var(--spacing-scale-base)",
    "Chips container padding must be var(--spacing-scale-base) (8 px) on all sides so the 6 px focus outline is not clipped."
  );
});

test("empty chips container takes no layout space", async () => {
  const stylesheet = await readStylesheet();
  const hidesEmptyChips = [...stylesheet.matchAll(/([^{}]*)\{([^{}]*)\}/g)].some(
    ([, selector, body]) =>
      selector.includes(".table-search-chips") &&
      selector.includes(":not(:has(") &&
      /(?:^|;)\s*display\s*:\s*none\s*(?:;|$)/.test(body)
  );

  assert.ok(
    hidesEmptyChips,
    "Expected a rule for .table-search-chips:not(:has(...)) that declares display: none."
  );
});

test("chips take a full-width line so the close button stays on the first line", async () => {
  const stylesheet = await readStylesheet();
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const fieldDeclarations = declarationsFor(stylesheet, ".table-search-field");
  const chipsDeclarations = declarationsFor(stylesheet, ".table-search-chips");
  const fieldStart = html.indexOf('<div class="table-search-field"');
  const fieldMarkup = html.slice(fieldStart, html.indexOf("<template", fieldStart));
  const closeIndex = fieldMarkup.indexOf("table-search-close");
  const chipsIndex = fieldMarkup.indexOf("table-search-chips");

  assert.equal(fieldDeclarations.get("flex-wrap"), "wrap");
  assert.equal(chipsDeclarations.get("width"), "100%");
  assert.ok(
    closeIndex !== -1 && chipsIndex !== -1,
    "Search field markup must contain the close button and the chips container."
  );
  assert.ok(
    closeIndex < chipsIndex,
    "Chips container must follow the close button in the search field markup."
  );
});
