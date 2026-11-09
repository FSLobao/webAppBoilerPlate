/**
 * Test the users table controller in app.js with a small DOM double.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { SORTABLE_FIELDS } from "../table-model.mjs";

const APP_GLOBAL_NAMES = [
  "document",
  "window",
  "fetch",
  "Element",
  "HTMLDialogElement",
  "requestAnimationFrame"
];

const USERS = [
  {
    id: 1,
    name: "Ada Lovelace",
    email: "ada@example.com",
    location: "Londres",
    image_url: null
  },
  {
    id: 2,
    name: "Alan Turing",
    email: "alan@example.com",
    location: "Manchester",
    image_url: null
  },
  {
    id: 3,
    name: "Grace Hopper",
    email: "grace@example.com",
    location: "Nova York",
    image_url: null
  }
];

const FULL_LIST_COUNTER = "1-3 de 3 itens";

const PAGED_USERS = Array.from({ length: 11 }, (_, index) => ({
  id: index + 1,
  name: `Usuário ${index + 1}`,
  email: `usuario${index + 1}@example.com`,
  location: "Recife",
  image_url: null
}));

class FakeClassList {
  values = new Set();

  add(...names) {
    for (const name of names) {
      this.values.add(name);
    }
  }

  remove(...names) {
    for (const name of names) {
      this.values.delete(name);
    }
  }

  toggle(name, force) {
    const shouldAdd = force ?? !this.values.has(name);

    if (shouldAdd) {
      this.values.add(name);
    } else {
      this.values.delete(name);
    }

    return shouldAdd;
  }

  contains(name) {
    return this.values.has(name);
  }
}

/**
 * Supports the simple selectors used by app.js on fixture elements.
 */
class FakeElement extends EventTarget {
  attributes = new Map();
  children = [];
  classList = new FakeClassList();
  dataset = {};
  disabled = false;
  hidden = false;
  id = "";
  parentElement = null;
  textContent = "";
  value = "";

  constructor(document, tagName) {
    super();
    this.ownerDocument = document;
    this.tagName = tagName.toUpperCase();
  }

  get className() {
    return [...this.classList.values].join(" ");
  }

  set className(value) {
    this.classList.values.clear();
    this.classList.add(...String(value).split(/\s+/u).filter(Boolean));
  }

  get isFragment() {
    return this.tagName === "#DOCUMENT-FRAGMENT";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  append(...nodes) {
    for (const node of nodes) {
      if (node.isFragment) {
        const fragmentChildren = node.children;
        node.children = [];
        this.append(...fragmentChildren);
        continue;
      }

      node.parentElement = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    for (const child of this.children) {
      child.parentElement = null;
    }

    this.children = [];
    this.append(...nodes);
  }

  matches(selector) {
    if (selector.startsWith("#")) {
      return this.id === selector.slice(1);
    }

    if (selector.startsWith(".")) {
      return this.classList.contains(selector.slice(1));
    }

    if (/^[a-z]+$/u.test(selector)) {
      return this.tagName === selector.toUpperCase();
    }

    throw new Error(`Unsupported selector in test fixture: ${selector}`);
  }

  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (node.matches(selector)) {
        return node;
      }
    }

    return null;
  }

  contains(node) {
    for (let current = node; current; current = current.parentElement) {
      if (current === this) {
        return true;
      }
    }

    return false;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  querySelectorAll(selector) {
    const matches = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) {
          matches.push(child);
        }
        visit(child);
      }
    };

    visit(this);
    return matches;
  }

  cloneNode(deep = false) {
    const copy = new FakeElement(this.ownerDocument, this.tagName);

    copy.id = this.id;
    copy.textContent = this.textContent;
    copy.className = this.className;
    Object.assign(copy.dataset, this.dataset);
    for (const [name, value] of this.attributes) {
      copy.setAttribute(name, value);
    }
    if (deep) {
      for (const child of this.children) {
        copy.append(child.cloneNode(true));
      }
    }

    return copy;
  }

  focus() {
    if (!this.disabled) {
      this.ownerDocument.activeElement = this;
    }
  }

  click() {
    this.dispatchEvent(new Event("click"));
  }
}

class FakeDialog extends FakeElement {
  open = false;
}

class FakeDocument extends EventTarget {
  activeElement = null;
  body = null;
  elementsById = new Map();
  sortButtons = [];

  constructor() {
    super();
    this.body = this.createElement("body");
    this.activeElement = this.body;
  }

  createElement(tagName) {
    return new FakeElement(this, tagName);
  }

  createTextNode(text) {
    const node = new FakeElement(this, "#text");
    node.textContent = text;
    return node;
  }

  querySelector(selector) {
    if (selector.startsWith("#") && !selector.includes(" ")) {
      return this.elementsById.get(selector.slice(1)) ?? null;
    }

    return null;
  }

  querySelectorAll(selector) {
    return selector === "button[data-sort-field]" ? [...this.sortButtons] : [];
  }
}

/**
 * Create the chip template content that app.js clones for each search term.
 *
 * @param {FakeDocument} document - The fake document that owns the nodes.
 * @returns {FakeElement} A document fragment holding one chip.
 */
function createChipFragment(document) {
  const fragment = new FakeElement(document, "#document-fragment");
  const chip = document.createElement("span");
  const removeButton = document.createElement("button");
  const text = document.createElement("span");

  chip.className = "br-button small table-search-chip";
  removeButton.className = "table-search-chip-remove";
  removeButton.setAttribute("aria-label", "Remover termo");
  text.className = "table-search-chip-text";
  chip.append(removeButton, text);
  fragment.append(chip);
  return fragment;
}

/**
 * Stub navigation markup, whose internals are outside the table search path.
 *
 * @param {FakeElement} element - The navigation element to stub.
 * @returns {FakeElement} The same element, whose nested queries return itself.
 */
function stubNavigationPart(element) {
  element.querySelector = () => element;
  return element;
}

/**
 * Create the DOM double used by the table controller and its search path.
 *
 * @returns {{controls: Object, document: FakeDocument, mediaQuery: Object}} The fixture.
 */
function createAppFixture() {
  const document = new FakeDocument();
  const register = (id, tagName, ElementType = FakeElement) => {
    const element = new ElementType(document, tagName);
    element.id = id;
    document.elementsById.set(id, element);
    return element;
  };
  const controls = {
    newUserButton: register("new-user-button", "button"),
    statusRegion: register("status-region", "p"),
    tableBody: register("users-table-body", "tbody"),
    searchToggle: register("users-table-search-toggle", "button"),
    searchField: register("users-table-search-field", "div"),
    searchInput: register("users-table-search-input", "input"),
    searchClose: register("users-table-search-close", "button"),
    searchChips: register("users-table-chips", "div"),
    chipTemplate: register("users-table-chip-template", "template"),
    menuButton: register("users-table-menu-button", "button"),
    menu: register("users-table-menu", "div"),
    menuAdd: register("users-table-menu-add", "button"),
    pageSize: register("users-table-page-size", "select"),
    page: register("users-table-page", "select"),
    pagePrevious: register("users-table-page-prev", "button"),
    pageNext: register("users-table-page-next", "button"),
    counter: register("users-table-counter", "span"),
    capBanner: register("users-table-cap-banner", "p"),
    emptyState: register("users-table-empty", "p"),
    userDialog: register("user-dialog", "dialog", FakeDialog),
    userForm: register("user-form", "form"),
    imageInput: register("user-image", "input"),
    removeImageInput: register("remove-image", "input"),
    userSaveButton: register("user-save-button", "button"),
    userDialogClose: register("user-dialog-close", "button"),
    userDialogCancel: register("user-dialog-cancel", "button"),
    deleteDialog: register("delete-dialog", "dialog", FakeDialog),
    deleteDialogCancel: register("delete-dialog-cancel", "button"),
    deleteConfirmButton: register("delete-confirm-button", "button")
  };
  const navigationPanel = stubNavigationPart(
    register("navigation-panel", "aside")
  );
  navigationPanel.parentElement = { classList: new FakeClassList() };
  stubNavigationPart(register("navigation-toggle", "button"));
  stubNavigationPart(register("navigation-dialog", "dialog"));

  controls.searchField.hidden = true;
  controls.searchToggle.setAttribute("aria-expanded", "false");
  controls.menu.hidden = true;
  controls.menuButton.setAttribute("aria-expanded", "false");
  controls.pageSize.value = "10";
  controls.page.value = "1";
  controls.counter.textContent = FULL_LIST_COUNTER;
  controls.userDialog.open = false;
  controls.deleteDialog.open = false;
  controls.chipTemplate.content = createChipFragment(document);

  for (const field of SORTABLE_FIELDS) {
    const headerButton = document.createElement("button");
    const menuItem = document.createElement("button");

    headerButton.dataset.sortField = field;
    headerButton.className = "table-sort-button";
    menuItem.dataset.sortField = field;
    menuItem.className = "table-sort-menu-item br-button";
    controls.menu.append(menuItem);
    document.sortButtons.push(headerButton, menuItem);
  }

  return {
    controls,
    document,
    mediaQuery: { matches: false, addEventListener() {} }
  };
}

/**
 * Let queued promise callbacks and the current event-loop turn finish.
 *
 * @returns {Promise<void>} A promise resolved after pending microtasks run.
 */
function settle() {
  return new Promise((resolve) => setImmediate(resolve));
}

/**
 * Create a fetch double that resolves the users list.
 *
 * @param {Array<Object>} users - The API records returned by the double.
 * @returns {() => Promise<Object>} A fetch replacement.
 */
function createUsersFetch(users) {
  return async () => ({
    ok: true,
    status: 200,
    json: async () => users
  });
}

/**
 * Create a keyboard event with a key value.
 *
 * @param {string} type - The event type.
 * @param {string} key - The key value exposed on the event.
 * @returns {Event} The keyboard event.
 */
function createKeyboardEvent(type, key) {
  const event = new Event(type, { cancelable: true });
  Object.defineProperty(event, "key", { value: key });
  return event;
}

/**
 * Create a click event whose target is the given element, as document listeners see it.
 *
 * @param {FakeElement} target - The element reported as the event target.
 * @returns {Event} The click event.
 */
function createClickEvent(target) {
  const event = new Event("click", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "target", { value: target });
  return event;
}

/**
 * Import the real app.js against a fresh fixture and run the exercise.
 *
 * @param {string} importKey - A unique module query string for this test.
 * @param {(...args: Array<unknown>) => Promise<Object>} fetchImplementation - The API double.
 * @param {(context: {appModule: Object, fixture: Object}) => Promise<void>} exercise - The checks to run.
 */
async function withAppFixture(importKey, fetchImplementation, exercise) {
  const fixture = createAppFixture();
  const previousGlobals = Object.fromEntries(
    APP_GLOBAL_NAMES.map((name) => [name, globalThis[name]])
  );

  globalThis.document = fixture.document;
  globalThis.window = { matchMedia: () => fixture.mediaQuery };
  globalThis.Element = FakeElement;
  globalThis.HTMLDialogElement = FakeDialog;
  globalThis.fetch = fetchImplementation;
  delete globalThis.requestAnimationFrame;

  try {
    const appModule = await import(`../app.js?${importKey}`);
    await settle();
    await exercise({ appModule, fixture });
  } finally {
    for (const [name, value] of Object.entries(previousGlobals)) {
      if (value === undefined) {
        delete globalThis[name];
      } else {
        globalThis[name] = value;
      }
    }
  }
}

/**
 * Return the rendered user rows, excluding message rows.
 *
 * @param {{controls: Object}} fixture - The app fixture.
 * @returns {Array<FakeElement>} The rendered user rows.
 */
function renderedUserRows(fixture) {
  return fixture.controls.tableBody.children.filter(
    (row) => row.tagName === "TR" && !row.classList.contains("table-message-row")
  );
}

/**
 * Assert that every user row and the counter show the unfiltered list.
 *
 * @param {{controls: Object}} fixture - The app fixture.
 */
function assertFullList(fixture) {
  assert.equal(renderedUserRows(fixture).length, USERS.length);
  assert.equal(fixture.controls.counter.textContent, FULL_LIST_COUNTER);
}

/**
 * Open the search field and submit one term with Enter.
 *
 * @param {{controls: Object}} fixture - The app fixture.
 * @param {string} term - The term to add as a chip.
 */
async function openSearchWithTerm(fixture, term) {
  const { controls } = fixture;

  controls.searchToggle.click();
  controls.searchInput.value = term;
  controls.searchInput.dispatchEvent(createKeyboardEvent("keydown", "Enter"));
  await settle();
}

/**
 * Move from the first page to the second page of the default 10-row list.
 *
 * @param {{controls: Object}} fixture - The app fixture.
 */
async function showSecondPage(fixture) {
  const { controls } = fixture;

  controls.pageNext.click();
  await settle();
}

/**
 * Click the ellipsis button, then let the click reach document listeners as in a browser.
 *
 * @param {{controls: Object, document: FakeDocument}} fixture - The app fixture.
 */
function clickMenuButtonWithBubble(fixture) {
  fixture.controls.menuButton.click();
  fixture.document.dispatchEvent(createClickEvent(fixture.controls.menuButton));
}

test("waitForRenderFrame returns null when requestAnimationFrame is not a function", async () => {
  await withAppFixture("wait-without-raf", createUsersFetch([]), async ({ appModule }) => {
    assert.equal(typeof globalThis.requestAnimationFrame, "undefined");
    assert.equal(appModule.waitForRenderFrame(), null);
  });
});

test("waitForRenderFrame resolves only after the second animation frame", async () => {
  await withAppFixture("wait-two-frames", createUsersFetch([]), async ({ appModule }) => {
    const frameCallbacks = [];
    let isResolved = false;

    globalThis.requestAnimationFrame = (callback) => {
      frameCallbacks.push(callback);
      return frameCallbacks.length;
    };
    const renderFrame = appModule.waitForRenderFrame().then(() => {
      isResolved = true;
    });

    assert.equal(frameCallbacks.length, 1);
    frameCallbacks[0]();
    await settle();
    assert.equal(frameCallbacks.length, 2);
    assert.equal(isResolved, false);

    frameCallbacks[1]();
    await renderFrame;
    assert.equal(isResolved, true);
  });
});

test("failed users fetch shows the empty counter and the error status", async () => {
  const failingFetch = async () => {
    throw new TypeError("Failed to fetch");
  };

  await withAppFixture("users-fetch-failure", failingFetch, async ({ fixture }) => {
    assert.equal(fixture.controls.counter.textContent, "Nenhum item");
    assert.equal(
      fixture.controls.statusRegion.textContent,
      "Não foi possível conectar à API. Tente novamente."
    );
    assert.equal(fixture.controls.statusRegion.className, "status-region status-error");
  });
});

// Before the fix, the lupa close kept terms, chips, and typed input text.
test("lupa close clears terms, input text, and chips and restores the full list", async () => {
  await withAppFixture("lupa-close", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;
    assertFullList(fixture);

    await openSearchWithTerm(fixture, "Ada");
    assert.equal(renderedUserRows(fixture).length, 1);
    controls.searchInput.value = "Lon";
    controls.searchToggle.click();
    await settle();

    assert.equal(controls.searchInput.value, "");
    assert.equal(controls.searchChips.children.length, 0);
    assertFullList(fixture);
    assert.equal(controls.searchField.hidden, true);
    assert.equal(controls.searchToggle.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.document.activeElement, controls.searchToggle);
  });
});

// Before the fix, the X close already cleared terms; this test guards the shared close path.
test("X close clears terms, input text, and chips and restores the full list", async () => {
  await withAppFixture("x-close", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;

    await openSearchWithTerm(fixture, "Ada");
    assert.equal(renderedUserRows(fixture).length, 1);
    controls.searchInput.value = "Lon";
    controls.searchClose.click();
    await settle();

    assert.equal(controls.searchInput.value, "");
    assert.equal(controls.searchChips.children.length, 0);
    assertFullList(fixture);
    assert.equal(controls.searchField.hidden, true);
    assert.equal(controls.searchToggle.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.document.activeElement, controls.searchToggle);
  });
});

// Before the fix, opening the menu hid the field but kept terms, chips, and typed input text.
test("opening the sort menu while search is open closes search and clears its terms", async () => {
  await withAppFixture("menu-open-closes-search", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;

    await openSearchWithTerm(fixture, "Ada");
    assert.equal(renderedUserRows(fixture).length, 1);
    controls.searchInput.value = "Lon";
    controls.menuButton.focus();
    controls.menuButton.click();
    await settle();

    assert.equal(controls.searchField.hidden, true);
    assert.equal(controls.searchToggle.getAttribute("aria-expanded"), "false");
    assert.equal(controls.searchInput.value, "");
    assert.equal(controls.searchChips.children.length, 0);
    assertFullList(fixture);
    assert.equal(controls.menu.hidden, false);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "true");
    assert.equal(fixture.document.activeElement, controls.menuButton);
  });
});

test("app.js selectors and sort fields exist in index.html", async () => {
  const [appSource, indexHtml] = await Promise.all([
    readFile(new URL("../app.js", import.meta.url), "utf8"),
    readFile(new URL("../index.html", import.meta.url), "utf8")
  ]);
  const htmlIds = new Set(
    [...indexHtml.matchAll(/\sid="([^"]+)"/gu)].map(([, id]) => id)
  );
  const selectorIds = new Set();

  for (const line of appSource.split("\n")) {
    if (/^\s*(\*|\/\/|\/\*)/u.test(line)) {
      continue;
    }

    for (const [, id] of line.matchAll(/#([A-Za-z_][\w-]*)/gu)) {
      selectorIds.add(id);
    }
  }

  assert.ok(selectorIds.size > 0);
  assert.deepEqual([...selectorIds].filter((id) => !htmlIds.has(id)), []);

  const htmlSortFields = [...indexHtml.matchAll(/data-sort-field="([^"]+)"/gu)].map(
    ([, field]) => field
  );
  const appSortFields = new Set([
    ...[...appSource.matchAll(/data-sort-field="([^"]+)"/gu)].map(([, field]) => field),
    ...SORTABLE_FIELDS
  ]);

  assert.deepEqual(
    [...appSortFields].filter((field) => !htmlSortFields.includes(field)),
    []
  );
});

// Guard: Escape only closes the menu. It must not reach closeSearchField, which resets the page.
test("Escape closes the open menu, returns focus to its button, and keeps the current page", async () => {
  await withAppFixture("menu-escape", createUsersFetch(PAGED_USERS), async ({ fixture }) => {
    const { controls } = fixture;
    await showSecondPage(fixture);
    const counterBefore = controls.counter.textContent;
    assert.equal(controls.page.value, "2");

    clickMenuButtonWithBubble(fixture);
    fixture.document.dispatchEvent(createKeyboardEvent("keydown", "Escape"));
    await settle();

    assert.equal(controls.menu.hidden, true);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.document.activeElement, controls.menuButton);
    assert.equal(controls.page.value, "2");
    assert.equal(controls.counter.textContent, counterBefore);
  });
});

// Guard: a click outside the menu uses closeMenu only. Search terms cannot coexist with an open menu,
// so the unchanged page and counter show that closeSearchField did not run.
test("a click outside the open menu closes it and leaves the list unchanged", async () => {
  await withAppFixture("menu-outside-click", createUsersFetch(PAGED_USERS), async ({ fixture }) => {
    const { controls } = fixture;
    await showSecondPage(fixture);
    const counterBefore = controls.counter.textContent;
    assert.equal(controls.page.value, "2");

    clickMenuButtonWithBubble(fixture);
    fixture.document.dispatchEvent(createClickEvent(controls.tableBody));
    await settle();

    assert.equal(controls.menu.hidden, true);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.document.activeElement, controls.menuButton);
    assert.equal(controls.page.value, "2");
    assert.equal(controls.counter.textContent, counterBefore);
  });
});

// Guard: the second click goes through the toggle branch, and the bubbled document click must not reopen or change state.
test("a second click on the ellipsis button closes the open menu", async () => {
  await withAppFixture("menu-toggle-twice", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;

    clickMenuButtonWithBubble(fixture);
    assert.equal(controls.menu.hidden, false);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "true");

    clickMenuButtonWithBubble(fixture);
    await settle();

    assert.equal(controls.menu.hidden, true);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "false");
  });
});

// Before the fix, the rejection from closeSearchField was unhandled and the status region stayed empty.
test("a render failure while closing search from the menu shows the error status", async () => {
  await withAppFixture("menu-close-search-error", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;
    await openSearchWithTerm(fixture, "Ada");
    controls.tableBody.append = () => {
      throw new Error("Falha ao renderizar a tabela.");
    };

    clickMenuButtonWithBubble(fixture);
    await settle();

    assert.equal(controls.menu.hidden, false);
    assert.equal(controls.menuButton.getAttribute("aria-expanded"), "true");
    assert.equal(controls.statusRegion.textContent, "Falha ao renderizar a tabela.");
    assert.equal(controls.statusRegion.className, "status-region status-error");
  });
});

// Before the fix, a failed render during close left the stale chip in the DOM because renderSearchChips ran after renderUsers.
test("a render failure while closing search clears the chips before the table renders", async () => {
  await withAppFixture("close-search-render-failure-chips", createUsersFetch(USERS), async ({ fixture }) => {
    const { controls } = fixture;
    await openSearchWithTerm(fixture, "Ada");
    assert.equal(controls.searchChips.children.length, 1);

    const appendRow = controls.tableBody.append.bind(controls.tableBody);
    let shouldFailNextAppend = true;
    controls.tableBody.append = (...nodes) => {
      if (shouldFailNextAppend) {
        shouldFailNextAppend = false;
        throw new Error("Falha ao renderizar a tabela.");
      }
      appendRow(...nodes);
    };

    clickMenuButtonWithBubble(fixture);
    await settle();

    assert.equal(controls.searchChips.children.length, 0);
    assert.equal(controls.searchInput.value, "");

    controls.pageSize.dispatchEvent(new Event("change"));
    await settle();

    assertFullList(fixture);
  });
});
