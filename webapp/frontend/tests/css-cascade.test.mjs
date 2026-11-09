/**
 * Test the CSS cascade helper that resolves the layout values read by the frontend layout tests.
 *
 * Each case passes a small stylesheet string to the helper. The cases cover the winning rule, media
 * query boundaries, length resolution, and the inputs the helper must reject with an error instead of
 * skipping them.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  customPropertiesOf,
  parseStylesheetDeclarations,
  resolveLengthPx,
  targetsSelector,
  valueAtWidth
} from "./helpers/css-cascade.mjs";

const TARGET = ".table-search-field";
const SPACING_TOKENS = `
  :root {
    --spacing-scale-half: 4px;
    --spacing-scale-base: 8px;
    --spacing-scale-4x: 32px;
  }
`;

/**
 * Build a matcher that accepts exactly the listed selector texts.
 *
 * @param {...string} selectors - Selector texts to accept.
 * @returns {(selector: string) => boolean} Matcher for {@link valueAtWidth}.
 */
function matchesOneOf(...selectors) {
  return (selector) => selectors.includes(selector);
}

/**
 * Build a matcher that delegates to {@link targetsSelector} for the test target.
 *
 * @param {string} target - Single class selector to resolve.
 * @returns {(selector: string) => boolean} Matcher for {@link valueAtWidth}.
 */
function matchesTarget(target) {
  return (selector) => targetsSelector(selector, target);
}

test("a more specific rule wins over a later, less specific rule", () => {
  const declarations = parseStylesheetDeclarations(`
    .item.active { max-height: 2px; }
    .item { max-height: 1px; }
  `);

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".item", ".item.active"),
      property: "max-height",
      width: 1024
    }),
    "2px"
  );
});

test("a later rule of equal specificity wins over an earlier one", () => {
  const declarations = parseStylesheetDeclarations(`
    .item { max-height: 1px; }
    .item { max-height: 3px; }
  `);

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".item"),
      property: "max-height",
      width: 1024
    }),
    "3px"
  );
});

test("a max-width px query applies up to and including its limit", () => {
  const declarations = parseStylesheetDeclarations(`
    .item { max-height: 120px; }
    @media (max-width: 480px) { .item { max-height: 172px; } }
  `);
  const valueAt = (width) =>
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".item"),
      property: "max-height",
      width
    });

  assert.equal(valueAt(480), "172px");
  assert.equal(valueAt(481), "120px");
});

test("a width condition in em units is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 30em) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /30em/ }
  );
});

test("a width condition in rem units is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 30rem) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /30rem/ }
  );
});

test("a width condition with a space before the closing parenthesis is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 480px ) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /480px \)/ }
  );
});

test("a media query that combines conditions with or is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 480px) or (min-width: 1024px) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query/ }
  );
});

test("a media query whose second width condition is not px is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (min-width: 320px) and (max-width: 30em) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /30em/ }
  );
});

test("a media query that prefixes a media type with not is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media not print and (max-width: 480px) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media not print and \(max-width: 480px\)/ }
  );
});

test("a media query that lists two queries with a comma is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 480px), (min-width: 1024px) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media \(max-width: 480px\), \(min-width: 1024px\)/ }
  );
});

test("a width condition without px units is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (max-width: 480) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media \(max-width: 480\)\./ }
  );
});

test("a min and max px range applies inside its bounds only", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (min-width: 600px) and (max-width: 900px) { .x { max-height: 172px; } }
  `);
  const valueAt = (width) =>
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".x"),
      property: "max-height",
      width
    });

  assert.equal(valueAt(700), "172px");
  assert.equal(valueAt(500), undefined);
});

test("a calc of spacing tokens resolves to 120px", () => {
  const declarations = parseStylesheetDeclarations(`
    ${SPACING_TOKENS}
    .item {
      max-height: calc(var(--spacing-scale-4x) * 3 + var(--spacing-scale-half) * 2 + var(--spacing-scale-base) * 2);
    }
  `);
  const maxHeight = valueAtWidth(declarations, {
    matchesSelector: matchesOneOf(".item"),
    property: "max-height",
    width: 1024
  });

  assert.equal(resolveLengthPx(maxHeight, customPropertiesOf(declarations)), "120px");
});

test("a calc that adds a px length to a unitless number is rejected", () => {
  assert.throws(() => resolveLengthPx("calc(120px + 2)", new Map()), {
    name: "SyntaxError",
    message: /px length and a unitless number/
  });
});

test("a length that mixes px with rem is rejected", () => {
  assert.throws(() => resolveLengthPx("calc(1rem + 2px)", new Map()), {
    name: "SyntaxError",
    message: /Unsupported length expression/
  });
});

test("a var() of an undeclared custom property is rejected", () => {
  assert.throws(() => resolveLengthPx("var(--spacing-scale-missing)", new Map()), {
    name: "ReferenceError",
    message: /--spacing-scale-missing is not declared/
  });
});

test("a selector list that contains the target throws with the exact selector", () => {
  for (const selector of [".table-search-field, .table-menu-anchor", ".table-menu-anchor, .table-search-field"]) {
    assert.throws(() => targetsSelector(selector, TARGET), {
      name: "SyntaxError",
      message: `Selector list contains ${TARGET}, which the helper cannot resolve: ${selector}`
    });
  }
});

test("a selector list without the target does not match it", () => {
  assert.equal(targetsSelector(".table-menu-anchor, .table-sort-menu", TARGET), false);
});

test("a compound that contains the target with extra selectors throws with the exact selector", () => {
  for (const selector of [".table-search-field[hidden]", ".table-search-field:not(.is-open)"]) {
    assert.throws(() => targetsSelector(selector, TARGET), {
      name: "SyntaxError",
      message: `Compound selector contains ${TARGET} without being exactly that target, which the helper cannot resolve: ${selector}`
    });
  }
});

test("a descendant selector that ends with the target matches it", () => {
  assert.equal(targetsSelector(".top-bar .table-search-field", TARGET), true);
});

test("a selector whose subject is another element does not match the target", () => {
  assert.equal(targetsSelector(".table-search-field .table-search-input", TARGET), false);
});

test("a property name written in upper case matches the same property", () => {
  const declarations = parseStylesheetDeclarations(".item { FLEX: 0 0 100%; }");

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".item"),
      property: "flex",
      width: 375
    }),
    "0 0 100%"
  );
});

test("an ambiguous rule that declares the requested property throws from valueAtWidth", () => {
  const declarations = parseStylesheetDeclarations(".table-search-field[hidden] { flex: 0; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesTarget(TARGET),
        property: "flex",
        width: 375
      }),
    { name: "SyntaxError", message: /Compound selector contains \.table-search-field/ }
  );
});

test("an ambiguous rule that declares another property does not affect the lookup", () => {
  const declarations = parseStylesheetDeclarations(`
    .table-search-field[hidden] { display: none; }
    .table-search-field { flex: 1; }
  `);

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesTarget(TARGET),
      property: "flex",
      width: 375
    }),
    "1"
  );
});

test("a media type combined with a width condition is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media print and (max-width: 480px) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media print and \(max-width: 480px\)/ }
  );
});

test("a media feature other than width combined with a width condition is rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (hover: none) and (max-width: 480px) { .item { max-height: 1px; } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media \(hover: none\)/ }
  );
});

test("an unsupported media query after a false width query is still rejected", () => {
  const declarations = parseStylesheetDeclarations(`
    @media (min-width: 1024px) { @media (hover: none) { .item { max-height: 1px; } } }
  `);

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /Unsupported media query: @media \(hover: none\)/ }
  );
});

test("an applicable declaration with !important is rejected with its rule and value", () => {
  const declarations = parseStylesheetDeclarations(".item { max-height: 1px !important; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "SyntaxError", message: /!important.*\.item \{ max-height: 1px !important \}/ }
  );
});

test("a non-matching hash selector that declares the requested property throws with the selector", () => {
  const declarations = parseStylesheetDeclarations("#users-table .item { max-height: 1px; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "Error", message: /: #users-table \.item$/ }
  );
});

test("a non-matching universal selector that declares the requested property throws with the selector", () => {
  const declarations = parseStylesheetDeclarations("* { max-height: 1px; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "Error", message: /: \*$/ }
  );
});

test("a non-matching backslash selector that declares the requested property throws with the selector", () => {
  const declarations = parseStylesheetDeclarations(".grid\\:col { max-height: 1px; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf(".item"),
        property: "max-height",
        width: 375
      }),
    { name: "Error", message: /: \.grid\\:col$/ }
  );
});

test("a matching hash selector that declares the requested property throws with the selector", () => {
  const declarations = parseStylesheetDeclarations("#x .table-search-field { flex: 1; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesTarget(TARGET),
        property: "flex",
        width: 375
      }),
    { name: "Error", message: /: #x \.table-search-field$/ }
  );
});

test("a matching universal selector that declares the requested property throws with the selector", () => {
  const declarations = parseStylesheetDeclarations("* { max-height: 1px; }");

  assert.throws(
    () =>
      valueAtWidth(declarations, {
        matchesSelector: matchesOneOf("*"),
        property: "max-height",
        width: 375
      }),
    { name: "Error", message: /: \*$/ }
  );
});

test("a hash selector that declares another property does not affect the lookup", () => {
  const declarations = parseStylesheetDeclarations(`
    #x .table-search-field { display: none; }
    .table-search-field { flex: 1; }
  `);

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesTarget(TARGET),
      property: "flex",
      width: 375
    }),
    "1"
  );
});

test("a universal selector that declares another property does not affect the lookup", () => {
  const declarations = parseStylesheetDeclarations(`
    * { display: none; }
    .item { max-height: 2px; }
  `);

  assert.equal(
    valueAtWidth(declarations, {
      matchesSelector: matchesOneOf(".item"),
      property: "max-height",
      width: 375
    }),
    "2px"
  );
});
