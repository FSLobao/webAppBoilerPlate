/** Test the DOM-free users-table model helpers. */

import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  RESULT_CAP,
  SORTABLE_FIELDS,
  counterText,
  cycleSort,
  filterAndCap,
  findHighlightRanges,
  normalizeText,
  paginate,
  parseSearchTerms,
  rowMatches,
  sortRows,
  toSearchText
} from "../table-model.mjs";

test("sortable fields exclude id", () => {
  assert.deepEqual(SORTABLE_FIELDS, ["name", "email", "location"]);
  assert.equal(Object.isFrozen(SORTABLE_FIELDS), true);
});

test("page-size defaults and options match the table contract", () => {
  assert.deepEqual(PAGE_SIZE_OPTIONS, [10, 50, 100]);
  assert.equal(Object.isFrozen(PAGE_SIZE_OPTIONS), true);
  assert.equal(DEFAULT_PAGE_SIZE, 10);
});

test("result cap is 500 rows", () => {
  assert.equal(RESULT_CAP, 500);
});

test("parseSearchTerms separates independent words", () => {
  assert.deepEqual(parseSearchTerms("ana silva"), ["ana", "silva"]);
});

test("parseSearchTerms keeps a quoted phrase as one term", () => {
  assert.deepEqual(parseSearchTerms("ana \"Rio de Janeiro\" silva"), [
    "ana",
    "Rio de Janeiro",
    "silva"
  ]);
});

test("parseSearchTerms keeps the rest of an unclosed quote as one term", () => {
  assert.deepEqual(parseSearchTerms("ana \"Rio de Janeiro silva"), [
    "ana",
    "Rio de Janeiro silva"
  ]);
});

test("parseSearchTerms ignores repeated whitespace", () => {
  assert.deepEqual(parseSearchTerms("  ana   silva  "), ["ana", "silva"]);
});

test("parseSearchTerms returns no terms for empty input", () => {
  assert.deepEqual(parseSearchTerms(""), []);
  assert.deepEqual(parseSearchTerms("   "), []);
});

test("parseSearchTerms removes accent-insensitive duplicates and keeps the first spelling", () => {
  assert.deepEqual(parseSearchTerms("José jose JOSÉ"), ["José"]);
});

test("parseSearchTerms drops terms that normalize to empty", () => {
  assert.deepEqual(parseSearchTerms("\u0301"), []);
});

test("normalizeText removes accents and lowercases text", () => {
  assert.equal(normalizeText("São Paulo"), "sao paulo");
});

test("toSearchText converts null and undefined to empty text", () => {
  assert.equal(toSearchText(null), "");
  assert.equal(toSearchText(undefined), "");
});

test("toSearchText converts numbers to strings", () => {
  assert.equal(toSearchText(42), "42");
});

test("toSearchText converts an invalid Date to empty text", () => {
  assert.equal(toSearchText(new Date(Number.NaN)), "");
});

test("toSearchText formats a valid Date as visible pt-BR date and time", () => {
  const date = new Date(2024, 0, 2, 10, 30);

  assert.equal(toSearchText(date), "02/01/2024, 10:30");
});

test("toSearchText rejects unsupported value types", () => {
  assert.equal(toSearchText(true), "");
  assert.equal(toSearchText({ value: "text" }), "");
});

test("rowMatches ignores case and accents", () => {
  assert.equal(
    rowMatches({ name: "São Paulo" }, ["sao"], ["name"]),
    true
  );
});

test("rowMatches searches email and location but ignores id", () => {
  const row = {
    id: "target",
    name: "Other",
    email: "ana@example.com",
    location: "Rio de Janeiro"
  };
  const fields = ["name", "email", "location"];

  assert.equal(rowMatches(row, ["example"], fields), true);
  assert.equal(rowMatches(row, ["rio"], fields), true);
  assert.equal(rowMatches(row, ["target"], fields), false);
});

test("rowMatches matches every row when terms are empty", () => {
  assert.equal(rowMatches({ name: "Ana" }, [], ["name"]), true);
});

test("rowMatches ignores terms that normalize to empty text", () => {
  assert.equal(rowMatches({ name: "Ana" }, ["\u0301"], ["name"]), true);
});

test("rowMatches combines terms with OR semantics", () => {
  assert.equal(
    rowMatches({ name: "Ana Silva" }, ["missing", "silva"], ["name"]),
    true
  );
});

test("findHighlightRanges maps an accented match to original text indices", () => {
  assert.deepEqual(findHighlightRanges("José Silva", ["jose"]), [
    { start: 0, end: 4 }
  ]);
});

test("findHighlightRanges includes a trailing combining mark", () => {
  assert.deepEqual(findHighlightRanges("Jose\u0301 Silva", ["jose"]), [
    { start: 0, end: 5 }
  ]);
});

test("findHighlightRanges matches uppercase terms against lowercase text", () => {
  assert.deepEqual(findHighlightRanges("Rio de Janeiro", ["RIO"]), [
    { start: 0, end: 3 }
  ]);
});

test("findHighlightRanges returns separate ranges for repeated occurrences", () => {
  assert.deepEqual(findHighlightRanges("Rio, rio.", ["rio"]), [
    { start: 0, end: 3 },
    { start: 5, end: 8 }
  ]);
});

test("findHighlightRanges maps indices after an accent to original text", () => {
  assert.deepEqual(findHighlightRanges("São Paulo", ["paulo"]), [
    { start: 4, end: 9 }
  ]);
});

test("findHighlightRanges merges overlapping matches", () => {
  assert.deepEqual(findHighlightRanges("banana", ["ana", "nan"]), [
    { start: 1, end: 6 }
  ]);
});

test("findHighlightRanges merges adjacent matches", () => {
  assert.deepEqual(findHighlightRanges("bluegreen", ["blue", "green"]), [
    { start: 0, end: 9 }
  ]);
});

test("findHighlightRanges returns no ranges when nothing matches", () => {
  assert.deepEqual(findHighlightRanges("São Paulo", ["rio"]), []);
});

test("sortRows orders accented Portuguese names before later names", () => {
  const rows = [
    { id: 2, name: "Bruno" },
    { id: 1, name: "Álvaro" }
  ];

  assert.deepEqual(
    sortRows(rows, "name", "asc").map((row) => row.name),
    ["Álvaro", "Bruno"]
  );
});

test("sortRows uses base sensitivity and sorts by name before id", () => {
  const rows = [
    { id: 2, name: "Sao" },
    { id: 1, name: "São" }
  ];

  assert.deepEqual(
    sortRows(rows, "name", "asc").map((row) => row.id),
    [1, 2]
  );

  const rowsWithDistinctNames = [
    { id: 1, name: "Bruno" },
    { id: 2, name: "Álvaro" }
  ];
  assert.deepEqual(
    sortRows(rowsWithDistinctNames, "name", "asc").map((row) => row.id),
    [2, 1]
  );
});

test("sortRows compares numeric text by numeric value", () => {
  const rows = [
    { id: 2, name: "Item 10" },
    { id: 1, name: "Item 2" }
  ];

  assert.deepEqual(
    sortRows(rows, "name", "asc").map((row) => row.name),
    ["Item 2", "Item 10"]
  );
});

test("sortRows reverses primary order for descending direction", () => {
  const rows = [
    { id: 1, name: "Ana" },
    { id: 2, name: "Bruno" }
  ];

  assert.deepEqual(
    sortRows(rows, "name", "desc").map((row) => row.name),
    ["Bruno", "Ana"]
  );
});

test("sortRows returns a sorted copy without mutating input", () => {
  const rows = [
    { id: 2, name: "Bruno" },
    { id: 1, name: "Ana" }
  ];

  const sortedRows = sortRows(rows, "name", "asc");

  assert.notStrictEqual(sortedRows, rows);
  assert.deepEqual(rows.map((row) => row.name), ["Bruno", "Ana"]);
});

test("sortRows returns a copy in received order when field is null", () => {
  const rows = [
    { id: 2, name: "Bruno" },
    { id: 1, name: "Ana" }
  ];

  const sortedRows = sortRows(rows, null, "sideways");

  assert.notStrictEqual(sortedRows, rows);
  assert.deepEqual(sortedRows, rows);
});

test("sortRows breaks primary ties by ascending id in either direction", () => {
  const rows = [
    { id: 10, name: "Ana" },
    { id: 2, name: "Ana" }
  ];

  assert.deepEqual(
    sortRows(rows, "name", "asc").map((row) => row.id),
    [2, 10]
  );
  assert.deepEqual(
    sortRows(rows, "name", "desc").map((row) => row.id),
    [2, 10]
  );
});

test("sortRows rejects an invalid direction", () => {
  assert.throws(
    () => sortRows([], "name", "sideways"),
    { name: "TypeError" }
  );
});

test("cycleSort starts at ascending when no sort is active", () => {
  assert.deepEqual(cycleSort(null, "name"), {
    field: "name",
    direction: "asc"
  });
});

test("cycleSort starts a new field at ascending", () => {
  assert.deepEqual(cycleSort({ field: "name", direction: "desc" }, "email"), {
    field: "email",
    direction: "asc"
  });
});

test("cycleSort changes the same ascending field to descending", () => {
  assert.deepEqual(cycleSort({ field: "name", direction: "asc" }, "name"), {
    field: "name",
    direction: "desc"
  });
});

test("cycleSort changes the same descending field back to ascending", () => {
  const secondClick = cycleSort({ field: "name", direction: "asc" }, "name");
  assert.deepEqual(cycleSort(secondClick, "name"), {
    field: "name",
    direction: "asc"
  });
});

test("cycleSort rejects an unknown field", () => {
  assert.throws(() => cycleSort(null, "id"), { name: "RangeError" });
});

test("filterAndCap searches beyond the result cap before limiting", () => {
  const rows = Array.from({ length: 501 }, (_, index) => ({
    id: index,
    name: index === 500 ? "target" : "row-" + index
  }));

  assert.deepEqual(filterAndCap(rows, ["target"], ["name"]), {
    rows: [{ id: 500, name: "target" }],
    totalFiltered: 1,
    isCapped: false
  });
});

test("filterAndCap reports total matches and whether results were capped", () => {
  const rows = [
    { id: 1, name: "match one" },
    { id: 2, name: "match two" },
    { id: 3, name: "match three" }
  ];

  assert.deepEqual(filterAndCap(rows, ["match"], ["name"], 2), {
    rows: rows.slice(0, 2),
    totalFiltered: 3,
    isCapped: true
  });
});

test("filterAndCap leaves exactly 500 matches uncapped", () => {
  const rows = Array.from({ length: 500 }, (_, index) => ({
    id: index,
    name: "match"
  }));

  const result = filterAndCap(rows, ["match"], ["name"]);

  assert.equal(result.isCapped, false);
  assert.equal(result.rows.length, 500);
});

test("paginate accepts each supported page size", () => {
  const rows = Array.from({ length: 105 }, (_, index) => index);

  assert.equal(paginate(rows, 1, 10).items.length, 10);
  assert.equal(paginate(rows, 1, 10).totalPages, 11);
  assert.equal(paginate(rows, 1, 50).items.length, 50);
  assert.equal(paginate(rows, 1, 50).totalPages, 3);
  assert.equal(paginate(rows, 1, 100).items.length, 100);
  assert.equal(paginate(rows, 1, 100).totalPages, 2);
});

test("paginate returns one-based bounds for visible items", () => {
  const rows = Array.from({ length: 13 }, (_, index) => index);

  assert.deepEqual(paginate(rows, 2, 10), {
    items: [10, 11, 12],
    page: 2,
    totalPages: 2,
    start: 11,
    end: 13
  });
});

test("paginate reports 12 pages for 120 rows at size 10", () => {
  const rows = Array.from({ length: 120 }, (_, index) => index);

  assert.equal(paginate(rows, 1, 10).totalPages, 12);
});

test("paginate clamps requested pages to valid bounds", () => {
  const rows = Array.from({ length: 11 }, (_, index) => index);

  assert.equal(paginate(rows, 0, 10).page, 1);
  assert.equal(paginate(rows, 99, 10).page, 2);
});

test("paginate uses page 1 when the requested page is NaN", () => {
  const rows = Array.from({ length: 12 }, (_, index) => index);
  const page = paginate(rows, Number.NaN, 10);

  assert.equal(page.page, 1);
  assert.equal(page.start, 1);
  assert.equal(page.end, 10);
  assert.equal(
    counterText({ start: page.start, end: page.end, total: rows.length }),
    "1-10 de 12 itens"
  );
});

test("paginate defaults undefined and non-numeric pages to page 1", () => {
  const rows = Array.from({ length: 12 }, (_, index) => index);

  for (const requestedPage of [undefined, "abc"]) {
    const page = paginate(rows, requestedPage, 10);

    assert.equal(page.page, 1);
    assert.equal(page.start, 1);
    assert.equal(
      counterText({ start: page.start, end: page.end, total: rows.length }),
      "1-10 de 12 itens"
    );
  }
});

test("paginate rejects unsupported page sizes", () => {
  assert.throws(() => paginate([], 1, 25), { name: "RangeError" });
});

test("paginate returns zero bounds and one page for an empty list", () => {
  assert.deepEqual(paginate([], 9, 10), {
    items: [],
    page: 1,
    totalPages: 1,
    start: 0,
    end: 0
  });
});

test("counterText formats a visible range and total", () => {
  assert.equal(counterText({ start: 1, end: 10, total: 25 }), "1-10 de 25 itens");
});

test("counterText reports an empty result set", () => {
  assert.equal(counterText({ start: 0, end: 0, total: 0 }), "Nenhum item");
});
