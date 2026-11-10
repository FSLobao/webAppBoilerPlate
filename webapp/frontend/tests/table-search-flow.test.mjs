/**
 * Test the users table search field reflow, stacking, alignment, and markup at every width.
 *
 * At every width the open search field leaves absolute positioning, takes its own line below the
 * header controls, and the header wraps only while the field is open. The values are resolved from
 * styles.css with the local CSS scanner, and the markup order is read from index.html.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  readStylesheetDeclarations,
  targetsSelector,
  valueAtWidth
} from "./helpers/css-cascade.mjs";

const STYLESHEET_URL = new URL("../styles.css", import.meta.url);
const REFLOW_WIDTHS = [375, 480, 481, 768, 793, 793.98, 794, 1023, 1024, 1280, 1440];
const OPEN_HEADER_SELECTOR = ".top-bar:has(.table-search-field:not([hidden]))";
// The loading rule's exact selector text in styles.css. It sits outside .top-bar (see the placement test), so it never applies to the search field.
const LOADING_RULE_SELECTOR = "#users-table-loading:not(:has(.table-loading-indicator:not([hidden])))";
const matchesSearchField = (selector) => targetsSelector(selector, ".table-search-field");

/**
 * Find the index of the `</div>` that closes the element opened at a given index.
 *
 * @param {string} html - Markup source.
 * @param {number} openIndex - Index of the opening `<div` tag.
 * @returns {number} Index of the matching closing tag, or -1 when it is missing.
 */
function closingDivIndex(html, openIndex) {
  let depth = 0;
  for (const match of html.slice(openIndex).matchAll(/<(\/?)div\b[^>]*>/g)) {
    depth += match[1] ? -1 : 1;
    if (depth === 0) {
      return openIndex + match.index;
    }
  }
  return -1;
}

test("search field joins the normal flow at every width", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, {
        matchesSelector: matchesSearchField,
        property: "position",
        width
      }),
      "static",
      `Search field position at ${width} px must be static so the field joins the normal flow.`
    );
  }
});

test("open search field is never absolutely positioned", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of REFLOW_WIDTHS) {
    assert.notEqual(
      valueAtWidth(declarations, {
        matchesSelector: matchesSearchField,
        property: "position",
        width
      }),
      "absolute",
      `Open search field must not be absolutely positioned at ${width} px.`
    );
  }
});

test("search field takes a full-width flex line at every width", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: matchesSearchField, property: "flex", width }),
      "0 0 100%",
      `Search field flex at ${width} px must take a full-width line.`
    );
  }
});

test("header wraps only while the search field is open at every width", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);
  const matchesHeader = (selector) => selector === ".top-bar";
  const matchesOpenHeader = (selector) => selector === OPEN_HEADER_SELECTOR;

  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: matchesHeader, property: "flex-wrap", width }),
      undefined,
      `Closed header must keep its single row at ${width} px.`
    );
  }
  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: matchesOpenHeader, property: "flex-wrap", width }),
      "wrap",
      `Header must wrap while the search field is open at ${width} px.`
    );
  }
});

test("loading container sits outside the top bar, so its rule cannot apply to the search field", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const topBarStart = html.indexOf('<div class="top-bar">');
  assert.notEqual(topBarStart, -1, "Expected a .top-bar element in index.html.");
  const topBarEnd = closingDivIndex(html, topBarStart);
  assert.notEqual(topBarEnd, -1, "Expected .top-bar to have a closing </div> in index.html.");
  const loadingStart = html.indexOf('id="users-table-loading"');

  assert.notEqual(loadingStart, -1, "Expected #users-table-loading in index.html.");
  assert.ok(
    loadingStart > topBarEnd,
    "The loading container must sit after .top-bar closes, so #users-table-loading cannot match the search field."
  );
});

test("search field drops absolute-only sizing at every width", async () => {
  const declarations = (await readStylesheetDeclarations(STYLESHEET_URL)).filter(
    (declaration) => declaration.selector !== LOADING_RULE_SELECTOR
  );

  for (const width of REFLOW_WIDTHS) {
    const minHeight = valueAtWidth(declarations, {
      matchesSelector: matchesSearchField,
      property: "min-height",
      width
    });
    assert.ok(
      ["auto", "0", "0px"].includes(minHeight),
      `Search field min-height at ${width} px must not be 100%; found ${minHeight}.`
    );
  }
  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, { matchesSelector: matchesSearchField, property: "height", width }),
      "auto",
      `Search field height at ${width} px must stay auto so wrapped chips can grow it.`
    );
  }
});

test("menu anchor stacks above the search field and the sort menu keeps its layer", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of REFLOW_WIDTHS) {
    const anchorZIndex = Number(
      valueAtWidth(declarations, {
        matchesSelector: (selector) => targetsSelector(selector, ".table-menu-anchor"),
        property: "z-index",
        width
      })
    );
    const fieldZIndex = Number(
      valueAtWidth(declarations, {
        matchesSelector: matchesSearchField,
        property: "z-index",
        width
      })
    );
    assert.ok(
      anchorZIndex > fieldZIndex,
      `Menu anchor z-index ${anchorZIndex} must exceed search field z-index ${fieldZIndex} at ${width} px.`
    );
  }

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: (selector) => targetsSelector(selector, ".table-sort-menu"),
      property: "z-index",
      width: 1024
    }),
    "1",
    "Sort menu must keep z-index: 1."
  );
});

test("search input and close button stay aligned with the field at every width", async () => {
  const declarations = await readStylesheetDeclarations(STYLESHEET_URL);

  for (const width of REFLOW_WIDTHS) {
    assert.equal(
      valueAtWidth(declarations, {
        matchesSelector: matchesSearchField,
        property: "align-items",
        width
      }),
      "center",
      `Search field align-items at ${width} px must be center.`
    );
    assert.ok(
      ["0", "0px"].includes(
        valueAtWidth(declarations, {
          matchesSelector: (selector) => targetsSelector(selector, ".table-search-input"),
          property: "margin-bottom",
          width
        })
      ),
      `Search input margin-bottom at ${width} px must be 0.`
    );
    assert.equal(
      valueAtWidth(declarations, {
        matchesSelector: (selector) => targetsSelector(selector, ".table-search-close"),
        property: "flex",
        width
      }),
      "0 0 auto",
      `Close button flex at ${width} px must be 0 0 auto.`
    );
  }
});

test("search field, close button, and chips sit in order inside the top bar after the title, toggle, and menu anchor", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const topBarStart = html.indexOf('<div class="top-bar">');
  assert.notEqual(topBarStart, -1, "Expected a .top-bar element in index.html.");
  const topBarEnd = closingDivIndex(html, topBarStart);
  const positions = {
    title: html.indexOf('id="users-table-title"'),
    toggle: html.indexOf('id="users-table-search-toggle"'),
    menuAnchor: html.indexOf('<div class="table-menu-anchor">'),
    field: html.indexOf('id="users-table-search-field"'),
    close: html.indexOf('id="users-table-search-close"'),
    chips: html.indexOf('id="users-table-chips"')
  };
  const order = ["title", "toggle", "menuAnchor", "field", "close", "chips"];

  for (const name of order) {
    assert.ok(
      positions[name] > topBarStart && positions[name] < topBarEnd,
      `Markup for ${name} must sit inside .top-bar.`
    );
  }
  for (let index = 1; index < order.length; index += 1) {
    assert.ok(
      positions[order[index - 1]] < positions[order[index]],
      `Markup for ${order[index - 1]} must come before ${order[index]}.`
    );
  }
});
