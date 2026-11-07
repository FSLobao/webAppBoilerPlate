/**
 * Provide DOM-free search, sorting, highlighting, and pagination helpers for the users table.
 *
 * Export `SORTABLE_FIELDS`, `PAGE_SIZE_OPTIONS`, `DEFAULT_PAGE_SIZE`, `RESULT_CAP`,
 * `toSearchText`, `normalizeText`, `parseSearchTerms`, `rowMatches`, `findHighlightRanges`,
 * `sortRows`, `cycleSort`, `filterAndCap`, `paginate`, and `counterText`.
 * Import-time side effects are limited to creating module-level `Intl.DateTimeFormat` and
 * `Intl.Collator` instances; no DOM is accessed.
 */

/** List the fields that support searching and sorting. */
export const SORTABLE_FIELDS = Object.freeze(["name", "email", "location"]);

/** List the supported page sizes. */
export const PAGE_SIZE_OPTIONS = Object.freeze([10, 50, 100]);

/** Set the default number of rows per page. */
export const DEFAULT_PAGE_SIZE = 10;

/** Set the maximum number of filtered rows available to pagination. */
export const RESULT_CAP = 500;

const dateTimeFormatter = new Intl.DateTimeFormat("pt-BR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit"
});
const collator = new Intl.Collator("pt-BR", {
  numeric: true,
  sensitivity: "base"
});

/**
 * Convert supported row values to searchable text.
 *
 * @param {unknown} value - The value to convert.
 * @returns {string} Searchable text, or an empty string for unsupported values.
 */
export function toSearchText(value) {
  if (value === null || value === undefined) {
    return "";
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number") {
    return String(value);
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "" : dateTimeFormatter.format(value);
  }

  return "";
}

/**
 * Normalize text for case- and accent-insensitive matching.
 *
 * @param {string} text - The text to normalize.
 * @returns {string} Lowercase text with combining marks removed.
 */
export function normalizeText(text) {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/**
 * Split a search query into unique terms while preserving quoted phrases.
 *
 * @param {string} query - The raw search query.
 * @returns {string[]} Trimmed terms in their original spelling and order.
 */
export function parseSearchTerms(query) {
  const parsedTerms = [];
  let currentTerm = "";
  let insideQuotes = false;

  /** Add the current non-empty term and reset the parser buffer. */
  const addCurrentTerm = () => {
    const trimmedTerm = currentTerm.trim();
    if (trimmedTerm) {
      parsedTerms.push(trimmedTerm);
    }
    currentTerm = "";
  };

  for (const character of query) {
    if (character === '"') {
      insideQuotes = !insideQuotes;
    } else if (!insideQuotes && /\s/u.test(character)) {
      addCurrentTerm();
    } else {
      currentTerm += character;
    }
  }

  addCurrentTerm();

  const uniqueTerms = [];
  const seenTerms = new Set();
  for (const term of parsedTerms) {
    const normalizedTerm = normalizeText(term);
    if (normalizedTerm && !seenTerms.has(normalizedTerm)) {
      seenTerms.add(normalizedTerm);
      uniqueTerms.push(term);
    }
  }

  return uniqueTerms;
}

/**
 * Match a row when any term appears in any supplied field.
 *
 * @param {Record<string, unknown>} row - The row to search.
 * @param {string[]} terms - Terms combined with OR semantics.
 * @param {string[]} fields - The only row fields to search.
 * @returns {boolean} Whether the row matches the search terms.
 */
export function rowMatches(row, terms, fields) {
  const normalizedTerms = terms
    .map(normalizeText)
    .filter((term) => term.length > 0);
  if (normalizedTerms.length === 0) {
    return true;
  }

  return fields.some((field) => {
    const normalizedValue = normalizeText(toSearchText(row[field]));
    return normalizedTerms.some((term) => normalizedValue.includes(term));
  });
}

/**
 * Find merged match ranges using indices from the original text.
 *
 * @param {string} text - The original text to search.
 * @param {string[]} terms - Accent- and case-insensitive search terms.
 * @returns {{start: number, end: number}[]} Sorted, merged ranges with exclusive ends.
 */
export function findHighlightRanges(text, terms) {
  const normalizedCharacters = [];
  const originalStarts = [];
  const originalEnds = [];
  let originalIndex = 0;

  for (const character of text) {
    const normalizedCharacter = normalizeText(character);
    const characterEnd = originalIndex + character.length;
    for (let index = 0; index < normalizedCharacter.length; index += 1) {
      normalizedCharacters.push(normalizedCharacter[index]);
      originalStarts.push(originalIndex);
      originalEnds.push(characterEnd);
    }
    // Extend the source range over combining marks removed from normalized text.
    if (normalizedCharacter.length === 0 && originalStarts.length > 0) {
      const previousStart = originalStarts[originalStarts.length - 1];
      for (
        let index = originalStarts.length - 1;
        index >= 0 && originalStarts[index] === previousStart;
        index -= 1
      ) {
        originalEnds[index] = characterEnd;
      }
    }
    originalIndex = characterEnd;
  }

  const normalizedText = normalizedCharacters.join("");
  const ranges = [];
  for (const term of terms) {
    const normalizedTerm = normalizeText(term);
    if (!normalizedTerm) {
      continue;
    }

    let matchIndex = normalizedText.indexOf(normalizedTerm);
    while (matchIndex !== -1) {
      const lastMatchedIndex = matchIndex + normalizedTerm.length - 1;
      ranges.push({
        start: originalStarts[matchIndex],
        end: originalEnds[lastMatchedIndex]
      });
      matchIndex = normalizedText.indexOf(normalizedTerm, matchIndex + 1);
    }
  }

  ranges.sort((left, right) => left.start - right.start || left.end - right.end);

  const mergedRanges = [];
  for (const range of ranges) {
    const previousRange = mergedRanges[mergedRanges.length - 1];
    if (previousRange && range.start <= previousRange.end) {
      previousRange.end = Math.max(previousRange.end, range.end);
    } else {
      mergedRanges.push({ ...range });
    }
  }

  return mergedRanges;
}

/**
 * Return a sorted copy using the Portuguese collator and a stable ID tie-breaker.
 *
 * @param {Record<string, unknown>[]} rows - Rows to sort without mutating.
 * @param {string | null} field - The primary field, or null to preserve received order.
 * @param {"asc" | "desc"} direction - The primary sort direction.
 * @returns {Record<string, unknown>[]} A sorted copy of the input rows.
 * @throws {TypeError} If field is not null and direction is neither "asc" nor "desc".
 */
export function sortRows(rows, field, direction) {
  if (field === null) {
    return [...rows];
  }

  if (direction !== "asc" && direction !== "desc") {
    throw new TypeError("direction must be asc or desc.");
  }

  const directionMultiplier = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const primaryComparison = collator.compare(
      toSearchText(left[field]),
      toSearchText(right[field])
    );

    if (primaryComparison !== 0) {
      return primaryComparison * directionMultiplier;
    }

    return collator.compare(String(left.id), String(right.id));
  });
}

/**
 * Advance a sortable field through its ascending and descending states.
 *
 * @param {{field: string, direction: "asc" | "desc"} | null} current - Current sort state.
 * @param {string} clickedField - The sortable field that was selected.
 * @returns {{field: string, direction: "asc" | "desc"}} The next sort state.
 * @throws {RangeError} If clickedField is not sortable.
 */
export function cycleSort(current, clickedField) {
  if (!SORTABLE_FIELDS.includes(clickedField)) {
    throw new RangeError("Unsupported sortable field: " + clickedField);
  }

  if (!current || current.field !== clickedField) {
    return { field: clickedField, direction: "asc" };
  }

  return {
    field: clickedField,
    direction: current.direction === "asc" ? "desc" : "asc"
  };
}

/**
 * Filter all rows before limiting the returned result set.
 *
 * @param {Record<string, unknown>[]} rows - The complete input row list.
 * @param {string[]} terms - Search terms combined with OR semantics.
 * @param {string[]} fields - The only row fields to search.
 * @param {number} [cap=RESULT_CAP] - Maximum number of matching rows to return.
 * @returns {{rows: Record<string, unknown>[], totalFiltered: number, isCapped: boolean}} Filter results and cap metadata.
 */
export function filterAndCap(rows, terms, fields, cap = RESULT_CAP) {
  const filteredRows = rows.filter((row) => rowMatches(row, terms, fields));
  return {
    rows: filteredRows.slice(0, cap),
    totalFiltered: filteredRows.length,
    isCapped: filteredRows.length > cap
  };
}

/**
 * Clamp a page and return its items and one-based result bounds.
 *
 * @param {unknown[]} rows - The rows available for pagination.
 * @param {unknown} page - The requested one-based page number; non-finite or non-number values use page 1.
 * @param {number} pageSize - A supported number of rows per page.
 * @returns {{items: unknown[], page: number, totalPages: number, start: number, end: number}} Page data and result bounds.
 * @throws {RangeError} If pageSize is not supported.
 */
export function paginate(rows, page, pageSize) {
  if (!PAGE_SIZE_OPTIONS.includes(pageSize)) {
    throw new RangeError("Unsupported page size: " + pageSize);
  }

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const requestedPage = Number.isFinite(page) ? Math.trunc(page) : 1;
  const currentPage = Math.max(1, Math.min(requestedPage, totalPages));
  const offset = (currentPage - 1) * pageSize;
  const items = rows.slice(offset, offset + pageSize);

  return {
    items,
    page: currentPage,
    totalPages,
    start: rows.length === 0 ? 0 : offset + 1,
    end: rows.length === 0 ? 0 : offset + items.length
  };
}

/**
 * Format the visible result range and filtered total.
 *
 * @param {{start: number, end: number, total: number}} result - Visible bounds and total rows.
 * @returns {string} The Portuguese result counter text.
 */
export function counterText({ start, end, total }) {
  return total === 0 ? "Nenhum item" : start + "-" + end + " de " + total + " itens";
}
