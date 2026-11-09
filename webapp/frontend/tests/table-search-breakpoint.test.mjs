/**
 * Test the height cap of the users table search chips area at each viewport width.
 *
 * At 480 px or less the chips area is capped at 172 px. Above 480 px it keeps the base cap, which the
 * GOV.BR spacing tokens resolve to 120 px. Both caps scroll on the Y axis. The values that apply at each
 * width are resolved from styles.css with the local CSS scanner. The 480 px boundary is inclusive because
 * it comes from `max-width: 480px` in styles.css; the spacing tokens, read from the GOV.BR core
 * stylesheet, only resolve the 120 px base cap.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  customPropertiesOf,
  readStylesheetDeclarations,
  resolveLengthPx,
  targetsSelector,
  valueAtWidth
} from "./helpers/css-cascade.mjs";

const STYLESHEET_URL = new URL("../styles.css", import.meta.url);
const SPACING_TOKENS_URL = new URL("../assets/vendor/govbr-core-3.7.0/core.min.css", import.meta.url);
const BASE_CHIPS_MAX_HEIGHT = "120px";
const NARROW_CHIPS_MAX_HEIGHT = "172px";
const NARROW_QUERY = "@media (max-width: 480px)";
const NARROW_WIDTHS = [375, 480];
const WIDE_WIDTHS = [481, 768, 1024];

/**
 * Read the GOV.BR spacing tokens that the base chips cap is computed from.
 *
 * @returns {Promise<Map<string, string>>} Custom property values by name.
 */
async function readSpacingTokens() {
  return customPropertiesOf(await readStylesheetDeclarations(SPACING_TOKENS_URL));
}

/**
 * Check whether the chips area is the element a selector targets.
 *
 * @param {string} selector - Selector text from a rule prelude.
 * @returns {boolean} True for the base chips rule and for scoped overrides of it.
 */
function isChipsSelector(selector) {
  return targetsSelector(selector, ".table-search-chips");
}

test("base chips rule keeps the token cap and vertical scrolling outside media queries", async () => {
  const declarations = (await readStylesheetDeclarations(STYLESHEET_URL)).filter(
    (declaration) =>
      declaration.selector === ".table-search-chips" && declaration.mediaPreludes.length === 0
  );
  const tokens = await readSpacingTokens();
  const maxHeight = declarations.filter((declaration) => declaration.property === "max-height").at(-1);
  const overflowY = declarations.filter((declaration) => declaration.property === "overflow-y").at(-1);

  assert.equal(
    resolveLengthPx(maxHeight?.value, tokens),
    BASE_CHIPS_MAX_HEIGHT,
    "Base chips max-height must resolve to the 120 px token cap."
  );
  assert.equal(overflowY?.value, "auto", "Base chips overflow-y must be auto.");
});

test("chips area is capped at 172 px with vertical scrolling at 480 px and below", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of NARROW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: isChipsSelector, property: "max-height", width }),
      NARROW_CHIPS_MAX_HEIGHT,
      `Chips max-height at ${width} px must be ${NARROW_CHIPS_MAX_HEIGHT}.`
    );
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: isChipsSelector, property: "overflow-y", width }),
      "auto",
      `Chips overflow-y at ${width} px must be auto.`
    );
  }
});

test("chips area keeps the 120 px token cap with vertical scrolling above 480 px", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);
  const tokens = await readSpacingTokens();

  for (const width of WIDE_WIDTHS) {
    const maxHeight = valueAtWidth(declarations, {
      matchesSelector: isChipsSelector,
      property: "max-height",
      width
    });
    assert.equal(
      resolveLengthPx(maxHeight, tokens),
      BASE_CHIPS_MAX_HEIGHT,
      `Chips max-height at ${width} px must resolve to the 120 px token cap.`
    );
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: isChipsSelector, property: "overflow-y", width }),
      "auto",
      `Chips overflow-y at ${width} px must be auto.`
    );
  }
});

test("172 px chips cap is declared only inside the 480 px media query", async () => {
  const chipsMaxHeights = (await readStylesheetDeclarations(STYLESHEET_URL)).filter(
    (declaration) => declaration.property === "max-height" && isChipsSelector(declaration.selector)
  );
  const narrowCaps = chipsMaxHeights.filter(
    (declaration) => declaration.value === NARROW_CHIPS_MAX_HEIGHT
  );

  assert.ok(narrowCaps.length > 0, "Expected a 172 px max-height for the chips area.");
  for (const declaration of narrowCaps) {
    assert.deepEqual(
      declaration.mediaPreludes,
      [NARROW_QUERY],
      "The 172 px chips cap must sit inside @media (max-width: 480px) only."
    );
  }
  for (const declaration of chipsMaxHeights) {
    if (declaration.value !== NARROW_CHIPS_MAX_HEIGHT) {
      assert.deepEqual(
        declaration.mediaPreludes,
        [],
        `Chips max-height ${declaration.value} must not be overridden inside a media query.`
      );
    }
  }
});
