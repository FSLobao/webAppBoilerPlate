/**
 * Test the limited CSS scanner used by frontend stylesheet contract tests.
 *
 * This is not a complete CSS parser; it covers the documented local subset.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeCssDeclarations,
  parseCssRuleNodes
} from "./helpers/css-scanner.mjs";

test("scanner parses normal rules and nested at-rules with comments and strings", () => {
  const rules = parseCssRuleNodes(`
    /* Outside comment: ; { } */
    @media (max-width: calc(100% - 1px)) {
      @supports (display: grid) {
        .footer-logo[data-label="text; } /* not a comment */"] {
          content: "value; } /* literal */";
          alternate: 'value; { /* literal */';
        }
      }
    }
    .after { value: ready; }
  `);

  assert.deepEqual(
    rules.map((rule) => rule.prelude),
    ["@media (max-width: calc(100% - 1px))", ".after"]
  );
  assert.equal(rules[0].children[0].prelude, "@supports (display: grid)");

  const logoRule = rules[0].children[0].children[0];
  assert.equal(
    logoRule.prelude,
    '.footer-logo[data-label="text; } /* not a comment */"]'
  );
  assert.deepEqual(normalizeCssDeclarations(logoRule.content), [
    'content: "value; } /* literal */"',
    "alternate: 'value; { /* literal */'"
  ]);
});

test("scanner ignores braces and semicolons in strings and comments", () => {
  const rules = parseCssRuleNodes(`
    /* .hidden { value: ";"; } */
    .visible {
      content: "/* still inside string; } {";
      /* Ignore this: ; } { */
      value: '/* not a comment; } { */';
    }
    /* } { ; */
    .also-visible { value: ready; }
  `);

  assert.deepEqual(
    rules.map((rule) => rule.prelude),
    [".visible", ".also-visible"]
  );
  assert.deepEqual(normalizeCssDeclarations(rules[0].content), [
    'content: "/* still inside string; } {"',
    "value: '/* not a comment; } { */'"
  ]);
});

test("scanner accepts escaped string newlines without parsing escape grammar", () => {
  const rules = parseCssRuleNodes('.sample { content: "line\\\ncontinued"; }');

  assert.match(rules[0].content, /content: "line\\\ncontinued"/);
  assert.deepEqual(normalizeCssDeclarations(rules[0].content), [
    'content: "line\\ continued"'
  ]);
});

test("scanner rejects malformed CSS instead of returning partial rules", () => {
  const malformedStylesheets = [
    [".parent { .child { value: invalid; } }", /Nested CSS rules are unsupported/],
    ['.sample { content: "unfinished; }', /Unclosed CSS string/],
    ['.sample[data-name="unfinished]', /Unclosed CSS string/],
    [".sample[data-name='unfinished]", /Unclosed CSS string/],
    [".sample { content: 'line\nbreak'; }", /Unescaped newline in CSS string/],
    [".sample { value: ready; } /* unfinished", /Unterminated CSS comment/],
    [".sample { value: ready;", /Unclosed CSS block/],
    [".sample { value: ready; } }", /Unexpected closing CSS brace/],
    [".sample", /Dangling CSS prelude/],
    ["@media (min-width: 20em)", /Dangling CSS prelude/],
    [".sample:not(", /Unclosed parentheses in CSS prelude/],
    [".sample)", /Unexpected closing CSS parenthesis/],
    [".valid {} .unfinished", /Dangling CSS prelude/]
  ];

  for (const [source, message] of malformedStylesheets) {
    assert.throws(
      () => parseCssRuleNodes(source),
      (error) => error instanceof SyntaxError && message.test(error.message),
      source
    );
  }
});
