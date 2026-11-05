/**
 * Scan the local stylesheet subset used by frontend tests.
 *
 * This is not a complete CSS parser. It recognizes comments, quoted strings,
 * balanced parentheses and braces, qualified rules, and nested at-rules. It
 * recognizes escapes only to bound strings and allow escaped newlines; it
 * does not parse CSS escape semantics, escaped identifiers, or selector-
 * function grammar. Local stylesheets and fixtures do not require those rules.
 *
 * @module css-scanner
 */

/**
 * @typedef {object} CssRuleNode
 * @property {string} prelude - The selector or at-rule before its block.
 * @property {string} content - The text inside the rule block.
 * @property {Array<CssRuleNode>} children - Rules nested inside an at-rule.
 */

/**
 * Replace comments outside strings while validating string and comment bounds.
 *
 * @param {string} source - The CSS source text.
 * @returns {string} CSS with comments replaced by whitespace.
 * @throws {SyntaxError} If a comment or string is incomplete or a string has
 * an unescaped newline.
 */
function stripCssComments(source) {
  if (typeof source !== "string") {
    throw new TypeError("CSS source must be a string.");
  }

  let result = "";
  let quote = null;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];

    if (quote) {
      result += character;

      if (character === "\\") {
        const nextCharacter = source[index + 1];

        if (nextCharacter === undefined) {
          throw new SyntaxError("Unclosed CSS string.");
        }

        if (nextCharacter === "\r" && source[index + 2] === "\n") {
          result += "\r\n";
          index += 2;
        } else {
          result += nextCharacter;
          index += 1;
        }
      } else if (character === quote) {
        quote = null;
      } else if (character === "\n" || character === "\r" || character === "\f") {
        throw new SyntaxError("Unescaped newline in CSS string.");
      }

      continue;
    }

    if (character === '"' || character === "'") {
      quote = character;
      result += character;
    } else if (character === "/" && source[index + 1] === "*") {
      const commentEnd = source.indexOf("*/", index + 2);

      if (commentEnd === -1) {
        throw new SyntaxError("Unterminated CSS comment.");
      }

      result += source
        .slice(index, commentEnd + 2)
        .replace(/[^\r\n\f]/g, " ");
      index = commentEnd + 1;
    } else {
      result += character;
    }
  }

  if (quote) {
    throw new SyntaxError("Unclosed CSS string.");
  }

  return result;
}

/**
 * Find the end of a string that was validated by {@link stripCssComments}.
 *
 * @param {string} source - CSS text with comments removed.
 * @param {number} start - Index of the opening quote.
 * @returns {number} Index immediately after the closing quote.
 */
function skipCssString(source, start) {
  const quote = source[start];

  for (let index = start + 1; index < source.length; index += 1) {
    if (source[index] === "\\") {
      if (source[index + 1] === "\r" && source[index + 2] === "\n") {
        index += 2;
      } else {
        index += 1;
      }
    } else if (source[index] === quote) {
      return index + 1;
    }
  }

  throw new SyntaxError("Unclosed CSS string.");
}

/**
 * Parse rules and recursively parse at-rule blocks.
 *
 * @param {string} source - A stylesheet or CSS block.
 * @returns {Array<CssRuleNode>} Parsed rules in source order.
 * @throws {SyntaxError} If strings, comments, parentheses, preludes, or braces
 * are malformed, or if native CSS nesting appears.
 * @throws {TypeError} If the source is not a string.
 */
export function parseCssRuleNodes(source) {
  const commentFreeSource = stripCssComments(source);

  /**
   * Parse one list of sibling rules.
   *
   * @param {string} ruleSource - A stylesheet or at-rule block.
   * @returns {Array<CssRuleNode>} Parsed sibling rules.
   * @throws {SyntaxError} If rule structure is malformed or nesting is
   * unsupported.
   */
  function parseRuleList(ruleSource) {
    const rules = [];
    let index = 0;

    while (index < ruleSource.length) {
      while (index < ruleSource.length && /\s/.test(ruleSource[index])) {
        index += 1;
      }

      if (index === ruleSource.length) {
        break;
      }

      if (ruleSource[index] === "}") {
        throw new SyntaxError(`Unexpected closing CSS brace at index ${index}.`);
      }

      const preludeStart = index;
      let parenthesesDepth = 0;

      while (index < ruleSource.length) {
        const character = ruleSource[index];

        if (character === '"' || character === "'") {
          index = skipCssString(ruleSource, index);
          continue;
        }

        if (character === "(") {
          parenthesesDepth += 1;
        } else if (character === ")") {
          if (parenthesesDepth === 0) {
            throw new SyntaxError(
              `Unexpected closing CSS parenthesis at index ${index}.`
            );
          }

          parenthesesDepth -= 1;
        } else if (parenthesesDepth === 0 && character === ";") {
          break;
        } else if (parenthesesDepth === 0 && character === "}") {
          throw new SyntaxError(
            `Unexpected closing CSS brace at index ${index}.`
          );
        } else if (parenthesesDepth === 0 && character === "{") {
          break;
        }

        index += 1;
      }

      const preludeText = ruleSource.slice(preludeStart, index);

      if (index === ruleSource.length) {
        if (parenthesesDepth > 0) {
          throw new SyntaxError("Unclosed parentheses in CSS prelude.");
        }

        if (preludeText.trim()) {
          throw new SyntaxError("Dangling CSS prelude.");
        }

        break;
      }

      if (ruleSource[index] === ";") {
        index += 1;
        continue;
      }

      const prelude = preludeText.trim().replace(/\s+/g, " ");

      if (!prelude) {
        throw new SyntaxError("Empty CSS prelude.");
      }

      const openingBrace = index;
      let depth = 1;
      let closingBrace = -1;

      for (index += 1; index < ruleSource.length; index += 1) {
        const character = ruleSource[index];

        if (character === '"' || character === "'") {
          index = skipCssString(ruleSource, index) - 1;
        } else if (character === "{") {
          if (depth === 1 && !prelude.startsWith("@")) {
            throw new SyntaxError("Nested CSS rules are unsupported.");
          }

          depth += 1;
        } else if (character === "}") {
          depth -= 1;

          if (depth === 0) {
            closingBrace = index;
            break;
          }
        }
      }

      if (closingBrace === -1) {
        throw new SyntaxError(
          `Unclosed CSS block at index ${openingBrace}.`
        );
      }

      const content = ruleSource.slice(openingBrace + 1, closingBrace);
      const children = prelude.startsWith("@")
        ? parseRuleList(content)
        : [];

      rules.push({ prelude, content, children });
      index = closingBrace + 1;
    }

    return rules;
  }

  return parseRuleList(commentFreeSource);
}

/**
 * Normalize declarations while respecting quoted strings and comments.
 *
 * @param {string} source - Declarations inside one CSS rule.
 * @returns {Array<string>} Ordered, whitespace-normalized declarations.
 * @throws {SyntaxError} If a comment or string is malformed.
 * @throws {TypeError} If the source is not a string.
 */
export function normalizeCssDeclarations(source) {
  const commentFreeSource = stripCssComments(source);
  const declarations = [];
  let declarationStart = 0;
  let quote = null;

  for (let index = 0; index < commentFreeSource.length; index += 1) {
    const character = commentFreeSource[index];

    if (quote) {
      if (character === "\\") {
        index += 1;
      } else if (character === quote) {
        quote = null;
      }
    } else if (character === '"' || character === "'") {
      quote = character;
    } else if (character === ";") {
      declarations.push(commentFreeSource.slice(declarationStart, index));
      declarationStart = index + 1;
    }
  }

  declarations.push(commentFreeSource.slice(declarationStart));

  return declarations
    .map((declaration) => declaration.trim().replace(/\s+/g, " "))
    .filter(Boolean);
}
