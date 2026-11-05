/**
 * Test responsive navigation states, focus behavior, accessibility, and CRUD dialogs.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { initializeNavigation } from "../navigation.mjs";
import {
  normalizeCssDeclarations,
  parseCssRuleNodes
} from "./helpers/css-scanner.mjs";

class ClassList {
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

class Control extends EventTarget {
  attributes = new Map();
  clickHandlers = [];
  focused = false;
  focusCalls = 0;
  hidden = false;
  disabled = false;
  isConnected = true;
  textContent = "";

  constructor(document, parentElement = null) {
    super();
    this.document = document;
    this.parentElement = parentElement;
  }

  addEventListener(type, listener, options) {
    if (type === "click") {
      this.clickHandlers.push(listener);
    }

    super.addEventListener(type, listener, options);
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  closest(selector) {
    if (selector !== "[hidden], [inert], [aria-hidden='true']") {
      return null;
    }

    for (let element = this; element; element = element.parentElement) {
      if (
        element.hidden ||
        element.inert ||
        element.getAttribute?.("aria-hidden") === "true"
      ) {
        return element;
      }
    }

    return null;
  }

  querySelector(selector) {
    if (selector === "[data-menu-collapse-label]") {
      return this.label;
    }

    return selector === "[data-menu-collapse-icon]" ? this.icon : null;
  }

  focus() {
    if (this.disabled) {
      return;
    }

    this.focused = true;
    this.focusCalls += 1;
    this.document.activeElement = this;
    this.parentElement?.dispatchEvent?.(new Event("focusin"));
  }

  click() {
    this.dispatchEvent(new Event("click"));
  }

  invokeClickHandler() {
    for (const handler of this.clickHandlers) {
      handler.call(this, new Event("click"));
    }
  }
}

class MenuContainer extends EventTarget {
  constructor(document) {
    super();
    this.parentElement = null;
    this.closeButton = new Control(document, this);
    this.scrim = new Control(document, this);
    this.collapseButton = new Control(document, this);
    this.collapseLabel = new Control(document, this.collapseButton);
    this.collapseIcon = new Control(document, this.collapseButton);
    this.navigationLink = new Control(document, this);
    this.collapseButton.label = this.collapseLabel;
    this.collapseButton.icon = this.collapseIcon;
  }

  querySelector(selector) {
    const controls = {
      "[data-menu-close]": this.closeButton,
      "[data-menu-scrim]": this.scrim,
      "[data-menu-collapse]": this.collapseButton,
      "[data-menu-collapse-label]": this.collapseLabel,
      "[data-navigation-link]": this.navigationLink
    };

    return controls[selector];
  }

  contains(element) {
    return [
      this.closeButton,
      this.scrim,
      this.collapseButton,
      this.collapseLabel,
      this.navigationLink
    ].includes(element);
  }
}

class NavigationWrapper extends EventTarget {
  children = [];

  constructor(layout) {
    super();
    this.parentElement = layout;
  }

  append(child) {
    child.parentElement?.removeChild?.(child);
    this.children.push(child);
    child.parentElement = this;
  }

  removeChild(child) {
    this.children = this.children.filter((item) => item !== child);
    child.parentElement = null;
  }

  querySelector(selector) {
    if (selector === ".menu-container") {
      return this.children.find((child) => child instanceof MenuContainer) ?? null;
    }

    return this.children
      .map((child) => child.querySelector?.(selector))
      .find((element) => element) ?? null;
  }

  contains(element) {
    return this.children.some(
      (child) => child === element || child.contains?.(element)
    );
  }
}

class NavigationPanel extends NavigationWrapper {
  hidden = false;
  id = "navigation-panel";
}

class NavigationDialog extends NavigationWrapper {
  attributes = new Map();
  classList = new ClassList();
  open = false;
  modal = false;
  showModalCalls = 0;
  showModalError = null;
  autoFocus = true;
  id = "navigation-dialog";

  constructor(document, layout, menuContainer) {
    super(layout);
    this.ownerDocument = document;
    this.closeButton = menuContainer.closeButton;
    this.scrim = menuContainer.scrim;
    this.collapseButton = menuContainer.collapseButton;
    this.collapseLabel = menuContainer.collapseLabel;
    this.collapseIcon = menuContainer.collapseIcon;
    this.navigationLink = menuContainer.navigationLink;
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
    if (name === "open") {
      this.open = true;
    }
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "open") {
      this.open = false;
      this.modal = false;
    }
  }

  showModal() {
    assert.equal(this.open, false);

    if (this.showModalError) {
      throw this.showModalError;
    }

    this.returnFocusTarget = this.ownerDocument.activeElement;
    this.open = true;
    this.modal = true;
    this.showModalCalls += 1;

    if (this.autoFocus) {
      this.closeButton.focus();
    }
  }

  close() {
    this.open = false;
    this.modal = false;
    this.attributes.delete("open");

    if (this.returnFocusTarget && !this.returnFocusTarget.disabled) {
      this.ownerDocument.activeElement = this.returnFocusTarget;
    }

    this.returnFocusTarget = null;
    setTimeout(() => this.dispatchEvent(new Event("close")), 0);
  }
}

class MediaQuery extends EventTarget {
  constructor(matches) {
    super();
    this.matches = matches;
  }

  setMatches(matches) {
    this.matches = matches;
    const event = new Event("change");
    Object.defineProperty(event, "matches", { value: matches });
    this.dispatchEvent(event);
  }
}

class AppElement extends EventTarget {
  attributes = new Map();
  children = [];
  dataset = {};
  disabled = false;
  checked = false;
  files = [];
  hidden = false;
  isConnected = true;
  textContent = "";
  value = "";

  constructor(document, tagName) {
    super();
    this.ownerDocument = document;
    this.tagName = tagName.toUpperCase();
    this.parentElement = null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  append(...children) {
    for (const child of children) {
      child.parentElement = this;
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    for (const child of this.children) {
      child.parentElement = null;
    }

    this.children = [];
    this.append(...children);
  }

  contains(element) {
    return (
      this === element ||
      this.children.some((child) => child.contains(element))
    );
  }

  querySelectorAll(selector) {
    if (selector !== "button[data-action]") {
      return [];
    }

    return this.children.flatMap((child) => {
      const matches =
        child.tagName === "BUTTON" && child.dataset.action ? [child] : [];
      return [...matches, ...child.querySelectorAll(selector)];
    });
  }

  closest(selector) {
    if (selector !== "button[data-action]") {
      return null;
    }

    return this.tagName === "BUTTON" && this.dataset.action ? this : null;
  }

  focus() {
    if (!this.disabled) {
      this.ownerDocument.activeElement = this;
    }
  }

  click() {
    this.dispatchEvent(new Event("click"));
  }

  reset() {}

  reportValidity() {
    return true;
  }
}

class AppDialog extends AppElement {
  open = false;
  modal = false;
  showModalCalls = 0;
  returnFocusTarget = null;

  showModal() {
    assert.equal(this.open, false);
    this.returnFocusTarget = this.ownerDocument.activeElement;
    this.open = true;
    this.modal = true;
    this.showModalCalls += 1;

    const autofocusTarget = this.ownerDocument
      .querySelectorAll("[autofocus]")
      .find((element) => this.contains(element));
    autofocusTarget?.focus();
  }

  close() {
    if (!this.open) {
      return;
    }

    this.open = false;
    this.modal = false;

    if (this.returnFocusTarget && !this.returnFocusTarget.disabled) {
      this.ownerDocument.activeElement = this.returnFocusTarget;
    }

    this.returnFocusTarget = null;
    setTimeout(() => this.dispatchEvent(new Event("close")), 0);
  }

  dispatchEvent(event) {
    const dispatched = super.dispatchEvent(event);

    if (event.type === "cancel" && !event.defaultPrevented && this.open) {
      this.close();
    }

    return dispatched;
  }
}

/**
 * Create a navigation fixture whose menu can move between responsive wrappers.
 *
 * @param {boolean} isNarrow - Whether the fixture starts below the breakpoint.
 * @returns {Object} The navigation wrappers, controls, and responsive query.
 */
function createNavigation(isNarrow) {
  const document = {
    activeElement: null,
    dialogs: [],
    querySelectorAll(selector) {
      return selector === "dialog[open]"
        ? this.dialogs.filter((dialog) => dialog.open)
        : [];
    },
    defaultView: {
      getComputedStyle(element) {
        return {
          display: element.computedDisplay ?? (element.hidden ? "none" : "block"),
          visibility: element.computedVisibility ?? "visible",
          opacity: element.computedOpacity ?? "1"
        };
      }
    }
  };
  document.body = new Control(document);
  document.activeElement = document.body;
  const layout = { classList: new ClassList() };
  const menuContainer = new MenuContainer(document);
  const panel = new NavigationPanel(layout);
  panel.append(menuContainer);
  const dialog = new NavigationDialog(document, layout, menuContainer);
  document.dialogs.push(dialog);
  const toggle = new Control(document);
  const mainControl = new Control(document);
  const mediaQuery = new MediaQuery(isNarrow);

  initializeNavigation(toggle, panel, dialog, mediaQuery);

  return {
    dialog,
    document,
    layout,
    mainControl,
    mediaQuery,
    menuContainer,
    panel,
    toggle
  };
}

/**
 * Wait for queued native dialog close events in the DOM test doubles.
 */
function flushCloseEvents() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Create the minimal DOM surface used by the real application entry point.
 *
 * @param {Array<Object>} users - The initial API records rendered by the app.
 * @param {{includeNavigationPanel?: boolean}} [options] - Whether to include the desktop navigation panel.
 * @returns {Object} The fake document, controls, and table body.
 */
function createAppFixture(users, { includeNavigationPanel = true } = {}) {
  const elements = new Map();
  const document = {
    activeElement: null,
    body: null,
    dialogs: [],
    querySelector(selector) {
      return elements.get(selector) ?? null;
    },
    querySelectorAll(selector) {
      if (selector === "dialog[open]") {
        return this.dialogs.filter((dialog) => dialog.open);
      }

      if (selector === "[autofocus]") {
        return [...elements.values()].filter((element) =>
          element.hasAttribute?.("autofocus")
        );
      }

      return [
        ...[...elements.values()].filter((element) => element.tagName === "BUTTON"),
        ...elements.get("#users-table-body").querySelectorAll("button[data-action]")
      ];
    },
    createElement(tagName) {
      return new AppElement(document, tagName);
    },
    createTextNode(text) {
      const textNode = new AppElement(document, "#text");
      textNode.textContent = text;
      return textNode;
    }
  };
  document.body = new AppElement(document, "body");
  document.activeElement = document.body;
  const addElement = (selector, tagName, ElementType = AppElement) => {
    const element = new ElementType(document, tagName);
    elements.set(selector, element);
    return element;
  };
  const controls = {
    newUserButton: addElement("#new-user-button", "button"),
    statusRegion: addElement("#status-region", "p"),
    tableBody: addElement("#users-table-body", "tbody"),
    userDialog: addElement("#user-dialog", "dialog", AppDialog),
    userForm: addElement("#user-form", "form"),
    userDialogTitle: addElement("#user-dialog-title", "h2"),
    userDialogError: addElement("#user-dialog-error", "p"),
    userDialogClose: addElement("#user-dialog-close", "button"),
    userDialogCancel: addElement("#user-dialog-cancel", "button"),
    nameInput: addElement("#user-name", "input"),
    emailInput: addElement("#user-email", "input"),
    locationInput: addElement("#user-location", "input"),
    imageInput: addElement("#user-image", "input"),
    imagePreview: addElement("#image-preview", "div"),
    removeImageOption: addElement("#remove-image-option", "label"),
    removeImageInput: addElement("#remove-image", "input"),
    userSaveButton: addElement("#user-save-button", "button"),
    deleteDialog: addElement("#delete-dialog", "dialog", AppDialog),
    deleteDialogContent: addElement("#delete-dialog-content", "div"),
    deleteDialogMessage: addElement("#delete-dialog-message", "p"),
    deleteDialogError: addElement("#delete-dialog-error", "p"),
    deleteDialogCancel: addElement("#delete-dialog-cancel", "button"),
    deleteConfirmButton: addElement("#delete-confirm-button", "button")
  };
  controls.nameInput.setAttribute("autofocus", "");
  controls.deleteDialogCancel.setAttribute("autofocus", "");
  controls.userDialog.append(controls.userForm);
  controls.userForm.append(
    controls.userDialogClose,
    controls.userDialogCancel,
    controls.nameInput,
    controls.emailInput,
    controls.locationInput,
    controls.imageInput,
    controls.imagePreview,
    controls.removeImageInput,
    controls.userSaveButton
  );
  controls.deleteDialog.append(controls.deleteDialogContent);
  controls.deleteDialogContent.append(
    controls.deleteDialogCancel,
    controls.deleteConfirmButton
  );
  const layout = { classList: new ClassList() };
  const menuContainer = new MenuContainer(document);
  const navigationPanel = new NavigationPanel(layout);
  navigationPanel.append(menuContainer);
  const navigationDialog = new NavigationDialog(document, layout, menuContainer);
  const navigationToggle = new AppElement(document, "button");
  const mediaQuery = new MediaQuery(false);
  elements.set("#navigation-toggle", navigationToggle);
  if (includeNavigationPanel) {
    elements.set("#navigation-panel", navigationPanel);
  }
  elements.set("#navigation-dialog", navigationDialog);
  document.dialogs.push(
    controls.userDialog,
    controls.deleteDialog,
    navigationDialog
  );

  return {
    controls,
    document,
    layout,
    mediaQuery,
    menuContainer,
    navigationDialog,
    navigationPanel,
    navigationToggle,
    users
  };
}

/**
 * Run the real application entry point with a controlled DOM and API mock.
 *
 * @param {Object} fixture - The application DOM fixture.
 * @param {(...args: Array<unknown>) => Promise<Object>} fetchImplementation - The API mock.
 * @param {string} importKey - A unique module query string for this test.
 * @param {(fixture: Object) => Promise<void>} exercise - The modal behavior to verify.
 */
async function withInitializedApp(
  fixture,
  fetchImplementation,
  importKey,
  exercise
) {
  const previousGlobals = {
    document: globalThis.document,
    window: globalThis.window,
    fetch: globalThis.fetch,
    Element: globalThis.Element,
    HTMLDialogElement: globalThis.HTMLDialogElement
  };

  globalThis.document = fixture.document;
  globalThis.window = { matchMedia: () => fixture.mediaQuery };
  globalThis.Element = AppElement;
  globalThis.HTMLDialogElement = AppDialog;
  globalThis.fetch = fetchImplementation;

  try {
    await import(`../app.js?${importKey}`);
    await new Promise((resolve) => setImmediate(resolve));
    await exercise(fixture);
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
 * Extract the first CSS rule containing the requested selector list.
 *
 * @param {string} source - The CSS source text.
 * @param {string} marker - A selector or complete selector list to find.
 * @returns {{selectors: Array<string>, content: string}|null} The parsed rule.
 * @throws {SyntaxError} If rule structure is malformed or nesting is
 * unsupported.
 */
function extractCssRule(source, marker) {
  const expectedSelectors = marker
    .replace(/\s*\{\s*$/, "")
    .split(",")
    .map((selector) => selector.trim().replace(/\s+/g, " "));

  return extractCssRules(source).find((rule) =>
    expectedSelectors.every((selector) => rule.selectors.includes(selector))
  ) ?? null;
}

/**
 * Extract CSS rules, recursively entering at-rule blocks.
 *
 * This parser handles the app's at-rule structure; it does not parse native CSS
 * rule nesting.
 *
 * @param {string} source - The CSS rule text.
 * @returns {Array<{selectors: Array<string>, content: string}>} The parsed rules.
 * @throws {SyntaxError} If rule structure is malformed or nesting is
 * unsupported.
 */
function extractCssRules(source) {
  const rules = [];

  /** Flatten qualified rules from recursively parsed at-rule blocks. */
  function collectRules(nodes) {
    for (const node of nodes) {
      if (node.prelude.startsWith("@")) {
        collectRules(node.children);
      } else {
        const selectors = node.prelude
          .split(",")
          .map((selector) => selector.trim().replace(/\s+/g, " "));

        rules.push({ selectors, content: node.content });
        collectRules(node.children);
      }
    }
  }

  collectRules(parseCssRuleNodes(source));
  return rules;
}

/**
 * Extract at-rule block contents containing the requested marker.
 *
 * @param {string} source - The CSS source text.
 * @param {string} marker - The at-rule text to find.
 * @returns {Array<string>} The extracted block bodies.
 * @throws {SyntaxError} If rule structure is malformed or nesting is
 * unsupported.
 */
function extractCssBlocks(source, marker) {
  const blocks = [];

  /** Collect block contents from matching at-rules and their descendants. */
  function collectBlocks(nodes) {
    for (const node of nodes) {
      if (node.prelude.startsWith("@") && node.prelude.includes(marker)) {
        blocks.push(node.content);
      }

      collectBlocks(node.children);
    }
  }

  collectBlocks(parseCssRuleNodes(source));
  return blocks;
}

/**
 * Find sizing declarations that can change the footer logos or their containers.
 *
 * @param {string} source - The stylesheet to inspect.
 * @returns {Array<{selectors: Array<string>, declarations: Array<string>}>}
 * Matching image and footer-tree rules.
 */
function extractFooterLogoSizingRules(source) {
  const footerElementSelector =
    /(?:^|[\s>+~])footer(?=$|[\s.#:[>+~])/i;
  const footerContainerSelector =
    /(?:^|[\s>+~])\.(?:br-footer|footer-layout|footer-content|footer-brand|footer-anatel|footer-govbr)(?=$|[\s.#:[>+~])/;
  const imageOrSvgSelector =
    /(?:^|[\s>+~])(?:img|svg)(?=$|[\s.#:[>+~])/i;
  const footerLogoSelector = /\.footer-logo(?![\w-])/;
  const dimensionProperties = new Set([
    "width",
    "height",
    "min-width",
    "max-width",
    "min-height",
    "max-height",
    "inline-size",
    "block-size",
    "min-inline-size",
    "max-inline-size",
    "min-block-size",
    "max-block-size",
    "aspect-ratio",
    "font",
    "font-size",
    "zoom",
    "transform",
    "scale",
    "flex",
    "flex-basis",
    "flex-grow",
    "flex-shrink",
    "box-sizing",
    "object-fit",
    "padding",
    "border"
  ]);

  return extractCssRules(source).flatMap((rule) => {
    const matchesFooterLogoSelector = rule.selectors.some((selector) => {
      const subject = selector
        .trim()
        .split(/\s*[>+~]\s*|\s+/)
        .at(-1) ?? "";
      const targetsFooterContainer =
        footerContainerSelector.test(subject) ||
        footerElementSelector.test(subject);

      if (
        footerLogoSelector.test(selector) ||
        targetsFooterContainer
      ) {
        return true;
      }

      return (
        imageOrSvgSelector.test(subject) &&
        (footerElementSelector.test(selector) ||
          footerContainerSelector.test(selector))
      );
    });

    if (!matchesFooterLogoSelector) {
      return [];
    }

    const declarations = normalizeCssDeclarations(rule.content).filter(
      (declaration) => {
        const colonIndex = declaration.indexOf(":");
        const property =
          colonIndex < 0
            ? ""
            : declaration.slice(0, colonIndex).trim().toLowerCase();

        return (
          dimensionProperties.has(property) ||
          property.startsWith("padding-") ||
          property.startsWith("border-")
        );
      }
    );

    return declarations.length > 0
      ? [{ selectors: rule.selectors, declarations }]
      : [];
  });
}

test("users page header omits eyebrow and keeps title and description", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const pageHeader = html.match(
    /<div class="page-header">([\s\S]*?)<\/div>\s*<p class="status-region"/
  )?.[1];

  assert.ok(pageHeader);
  assert.doesNotMatch(pageHeader, /class="eyebrow"/);
  assert.match(pageHeader, /<h1>Usuários<\/h1>/);
  assert.match(
    pageHeader,
    /<p class="page-description">Consulte e gerencie os usuários cadastrados\.<\/p>/
  );
});

test("compact GOV.BR header keeps Core density, responsive title, and hamburger size", async () => {
  const [html, styles, coreStyles] = await Promise.all([
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../styles.css", import.meta.url), "utf8"),
    readFile(
      new URL("../assets/vendor/govbr-core-3.7.0/core.min.css", import.meta.url),
      "utf8"
    )
  ]);
  const header = html.match(/<header\b[^>]*>[\s\S]*?<\/header>/)?.[0];
  const headerClassAttribute = header?.match(
    /<header\b[^>]*\bclass="([^"]*)"/
  )?.[1];
  const headerClassNames = headerClassAttribute?.split(/\s+/) ?? [];
  const hamburger = header?.match(
    /<button[^>]*id="navigation-toggle"[\s\S]*?<\/button>/
  )?.[0];
  const baseHeaderRule = extractCssRule(coreStyles, ".br-header{");
  const compactHeaderRule = extractCssRule(coreStyles, ".br-header.compact{");
  const headerTitleRule = extractCssRule(
    coreStyles,
    ".br-header .header-menu .header-title{"
  );
  const tabletCompactTitleRule = extractCssBlocks(
    coreStyles,
    "@media (min-width:576px)"
  )
    .map((block) =>
      extractCssRule(block, ".br-header.compact .header-menu{")
    )
    .find((rule) => rule);
  const desktopCompactTitleRule = extractCssBlocks(
    coreStyles,
    "@media (min-width:1280px)"
  )
    .map((block) =>
      extractCssRule(block, ".br-header.compact .header-menu{")
    )
    .find((rule) => rule);
  const coreButtonRule = extractCssRule(coreStyles, ".br-button{");
  const coreCircleButtonRule = extractCssRule(
    coreStyles,
    ".br-button.circle,.br-button.is-circle,.br-button[circle]{"
  );
  const coreStylesheetLink =
    '<link rel="stylesheet" href="assets/vendor/govbr-core-3.7.0/core.min.css">';
  const appStylesheetLink = '<link rel="stylesheet" href="styles.css">';
  const stylesheetMarkup = html.replace(/<!--[\s\S]*?-->/g, "");

  assert.ok(header);
  assert.ok(headerClassNames.includes("br-header"));
  assert.ok(headerClassNames.includes("compact"));
  assert.ok(stylesheetMarkup.includes(coreStylesheetLink));
  assert.ok(stylesheetMarkup.includes(appStylesheetLink));
  assert.ok(
    stylesheetMarkup.indexOf(coreStylesheetLink) <
      stylesheetMarkup.indexOf(appStylesheetLink)
  );
  assert.ok(hamburger);
  assert.match(hamburger, /class="br-button circle menu-trigger"/);
  assert.match(hamburger, /aria-label="Navegação"/);
  assert.match(hamburger, /bars\.svg[^>]*alt=""/);
  assert.ok(baseHeaderRule);
  assert.deepEqual(baseHeaderRule.selectors, [".br-header"]);
  assert.match(baseHeaderRule.content, /--header-padding-small:var\(--spacing-scale-base\)/);
  assert.match(baseHeaderRule.content, /--header-title-size:var\(--font-size-scale-base\)/);
  assert.match(baseHeaderRule.content, /padding:var\(--header-padding\) 0/);
  assert.ok(compactHeaderRule);
  assert.deepEqual(compactHeaderRule.selectors, [".br-header.compact"]);
  assert.match(compactHeaderRule.content, /--header-padding:var\(--header-padding-small\)/);
  assert.ok(headerTitleRule);
  assert.deepEqual(headerTitleRule.selectors, [".br-header .header-menu .header-title"]);
  assert.match(headerTitleRule.content, /font-size:var\(--header-title-size\)/);
  assert.match(coreStyles, /--spacing-scale-base:8px/);
  assert.match(coreStyles, /--font-size-scale-base:14px/);
  assert.match(coreStyles, /--font-size-scale-up-01:16\.8px/);
  assert.match(coreStyles, /--font-size-scale-up-02:20\.16px/);
  assert.ok(tabletCompactTitleRule);
  assert.deepEqual(tabletCompactTitleRule.selectors, [
    ".br-header.compact .header-menu"
  ]);
  assert.deepEqual(normalizeCssDeclarations(tabletCompactTitleRule.content), [
    "--header-title-size:var(--font-size-scale-up-01)"
  ]);
  assert.ok(desktopCompactTitleRule);
  assert.deepEqual(desktopCompactTitleRule.selectors, [
    ".br-header.compact .header-menu"
  ]);
  assert.deepEqual(normalizeCssDeclarations(desktopCompactTitleRule.content), [
    "--header-title-size:var(--font-size-scale-up-02)"
  ]);
  assert.doesNotMatch(styles, /--header-(?:padding|title-size)\s*:/);
  assert.ok(coreButtonRule);
  assert.match(coreButtonRule.content, /--button-medium:40px/);
  assert.match(coreButtonRule.content, /--button-size:var\(--button-medium\)/);
  assert.match(coreButtonRule.content, /height:var\(--button-size\)/);
  assert.ok(coreCircleButtonRule);
  assert.deepEqual(coreCircleButtonRule.selectors, [
    ".br-button.circle",
    ".br-button.is-circle",
    ".br-button[circle]"
  ]);
  assert.match(coreCircleButtonRule.content, /width:var\(--button-size\)/);
});

test("desktop starts closed and hamburger opens a non-modal aside", () => {
  const { dialog, layout, mainControl, menuContainer, panel, toggle } =
    createNavigation(false);

  assert.equal(dialog.open, false);
  assert.equal(panel.hidden, false);
  assert.equal(menuContainer.parentElement, panel);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.getAttribute("aria-label"), "Navegação");
  assert.equal(toggle.getAttribute("aria-controls"), panel.id);

  toggle.click();

  assert.equal(dialog.open, false);
  assert.equal(dialog.modal, false);
  assert.equal(dialog.showModalCalls, 0);
  assert.equal(menuContainer.parentElement, panel);
  assert.equal(layout.classList.contains("navigation-open"), true);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "Navegação");
  assert.equal(toggle.getAttribute("aria-controls"), panel.id);
  assert.equal(dialog.classList.contains("active"), false);
  assert.equal(dialog.attributes.has("aria-modal"), false);

  mainControl.focus();
  assert.equal(mainControl.document.activeElement, mainControl);
});

test("hamburger opens idempotently, expands a collapsed desktop panel, and X closes", () => {
  const { dialog, layout, toggle } = createNavigation(false);

  toggle.click();
  assert.equal(layout.classList.contains("navigation-open"), true);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(dialog.collapseButton.getAttribute("aria-pressed"), "false");
  assert.equal(dialog.collapseButton.getAttribute("title"), "Ativar modo compacto");
  assert.equal(dialog.collapseButton.getAttribute("aria-label"), "Modo compacto");
  assert.equal(dialog.collapseLabel.textContent, "Modo compacto");
  assert.equal(
    dialog.collapseIcon.src,
    "assets/vendor/fontawesome-5.11.2/solid/chevron-left.svg"
  );
  dialog.collapseButton.click();

  assert.equal(dialog.open, false);
  assert.equal(layout.classList.contains("navigation-collapsed"), true);
  assert.equal(dialog.collapseButton.getAttribute("aria-pressed"), "true");
  assert.equal(dialog.collapseLabel.textContent, "Modo compacto");
  assert.equal(dialog.collapseButton.getAttribute("title"), "Desativar modo compacto");
  assert.equal(dialog.collapseButton.getAttribute("aria-label"), "Modo compacto");
  assert.equal(
    dialog.collapseIcon.src,
    "assets/vendor/fontawesome-5.11.2/solid/chevron-right.svg"
  );
  assert.equal(toggle.getAttribute("aria-label"), "Navegação");
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  toggle.click();

  assert.equal(dialog.open, false);
  assert.equal(layout.classList.contains("navigation-open"), true);
  assert.equal(layout.classList.contains("navigation-collapsed"), false);
  assert.equal(dialog.collapseButton.getAttribute("aria-pressed"), "false");
  assert.equal(dialog.collapseButton.getAttribute("title"), "Ativar modo compacto");
  assert.equal(
    dialog.collapseIcon.src,
    "assets/vendor/fontawesome-5.11.2/solid/chevron-left.svg"
  );
  assert.equal(toggle.getAttribute("aria-label"), "Navegação");
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  toggle.click();
  assert.equal(dialog.open, false);
  assert.equal(layout.classList.contains("navigation-open"), true);
  assert.equal(layout.classList.contains("navigation-collapsed"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  dialog.collapseButton.click();
  dialog.closeButton.click();

  assert.equal(dialog.open, false);
  assert.equal(layout.classList.contains("navigation-open"), false);
  assert.equal(layout.classList.contains("navigation-collapsed"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
});

test("desktop close control restores trigger focus without opening a dialog", () => {
  const { dialog, layout, toggle } = createNavigation(false);
  toggle.click();
  dialog.closeButton.click();

  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(dialog.open, false);
  assert.equal(layout.classList.contains("navigation-open"), false);
  assert.equal(toggle.focused, true);
});

test("desktop Escape closes only from the panel and restores trigger focus", () => {
  const { document, layout, panel, toggle } = createNavigation(false);
  toggle.click();
  toggle.focus();

  const outsideEscape = new Event("keydown", { cancelable: true });
  Object.defineProperty(outsideEscape, "key", { value: "Escape" });
  toggle.dispatchEvent(outsideEscape);

  assert.equal(outsideEscape.defaultPrevented, false);
  assert.equal(layout.classList.contains("navigation-open"), true);

  const panelEscape = new Event("keydown", { cancelable: true });
  Object.defineProperty(panelEscape, "key", { value: "Escape" });
  panel.dispatchEvent(panelEscape);

  assert.equal(panelEscape.defaultPrevented, true);
  assert.equal(layout.classList.contains("navigation-open"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(document.activeElement, toggle);
});

test("narrow hamburger opens modal navigation and Escape restores trigger focus", () => {
  const { dialog, layout, mediaQuery, menuContainer, panel, toggle } =
    createNavigation(true);

  assert.equal(dialog.open, false);
  assert.equal(panel.hidden, true);
  assert.equal(menuContainer.parentElement, dialog);
  toggle.click();

  assert.equal(dialog.open, true);
  assert.equal(dialog.modal, true);
  assert.equal(dialog.classList.contains("active"), false);
  assert.equal(dialog.classList.contains("is-modal"), true);
  assert.equal(dialog.showModalCalls, 1);
  assert.equal(layout.classList.contains("navigation-collapsed"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-controls"), dialog.id);
  assert.equal(dialog.closeButton.document.activeElement, dialog.closeButton);

  const escape = new Event("cancel", { cancelable: true });
  dialog.dispatchEvent(escape);

  assert.equal(escape.defaultPrevented, true);
  assert.equal(dialog.open, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
  assert.equal(mediaQuery.matches, true);
});

test("narrow scrim closes modal navigation and restores trigger focus", () => {
  const { dialog, toggle } = createNavigation(true);
  toggle.click();

  dialog.scrim.click();

  assert.equal(dialog.open, false);
  assert.equal(toggle.focused, true);
});

test("narrow X closes modal navigation and restores trigger focus", () => {
  const { dialog, toggle } = createNavigation(true);
  toggle.click();

  dialog.closeButton.click();

  assert.equal(dialog.open, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
});

test("resize switches open navigation between non-modal and modal states", () => {
  const { dialog, document, layout, mediaQuery, menuContainer, panel, toggle } =
    createNavigation(false);
  toggle.click();
  dialog.collapseButton.focus();
  dialog.collapseButton.computedDisplay = "none";
  dialog.autoFocus = false;

  mediaQuery.setMatches(true);

  assert.equal(panel.hidden, true);
  assert.equal(menuContainer.parentElement, dialog);
  assert.equal(dialog.open, true);
  assert.equal(dialog.modal, true);
  assert.equal(dialog.showModalCalls, 1);
  assert.equal(layout.classList.contains("navigation-collapsed"), false);
  assert.equal(dialog.closeButton.document.activeElement, dialog.closeButton);
  assert.equal(dialog.collapseButton.getAttribute("aria-pressed"), "false");

  mediaQuery.setMatches(false);

  assert.equal(panel.hidden, false);
  assert.equal(menuContainer.parentElement, panel);
  assert.equal(dialog.open, false);
  assert.equal(dialog.modal, false);
  assert.equal(dialog.classList.contains("active"), false);
  assert.equal(dialog.attributes.has("open"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-controls"), panel.id);
  assert.equal(document.activeElement, dialog.closeButton);
  assert.equal(toggle.focused, false);
});

test("desktop-to-narrow resize closes open navigation silently when focus is outside", () => {
  for (const targetName of ["mainControl", "toggle"]) {
    const fixture = createNavigation(false);
    const target = fixture[targetName];
    fixture.toggle.click();
    target.focus();

    fixture.mediaQuery.setMatches(true);

    assert.equal(fixture.dialog.open, false);
    assert.equal(fixture.dialog.modal, false);
    assert.equal(fixture.menuContainer.parentElement, fixture.dialog);
    assert.equal(fixture.panel.hidden, true);
    assert.equal(fixture.layout.classList.contains("navigation-open"), false);
    assert.equal(fixture.toggle.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.document.activeElement, target);
  }
});

test("desktop-to-narrow resize moves the same menu and preserves link focus", () => {
  const { dialog, document, mediaQuery, menuContainer, panel, toggle } =
    createNavigation(false);
  toggle.click();
  dialog.navigationLink.focus();

  mediaQuery.setMatches(true);

  assert.equal(menuContainer.parentElement, dialog);
  assert.equal(dialog.open, true);
  assert.equal(dialog.modal, true);
  assert.equal(document.activeElement, dialog.navigationLink);
  assert.equal(toggle.getAttribute("aria-controls"), dialog.id);
  assert.equal(panel.hidden, true);
});

test("narrow-to-desktop ignores the queued close event and preserves link focus", async () => {
  const { dialog, document, mediaQuery, menuContainer, panel, toggle } =
    createNavigation(true);
  toggle.click();
  dialog.navigationLink.focus();
  let closeEventDelivered = false;
  dialog.addEventListener("close", () => {
    closeEventDelivered = true;
  });

  mediaQuery.setMatches(false);

  assert.equal(dialog.open, false);
  assert.equal(menuContainer.parentElement, panel);
  assert.equal(closeEventDelivered, false);

  await flushCloseEvents();

  assert.equal(closeEventDelivered, true);
  assert.equal(document.activeElement, dialog.navigationLink);
  assert.equal(toggle.focused, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
});

for (const previousFocus of ["body", null]) {
  test(`narrow-to-desktop falls back to hamburger when prior focus is ${previousFocus ?? "null"}`, () => {
    const { document, mediaQuery, toggle } = createNavigation(true);
    toggle.click();
    document.activeElement = previousFocus === "body" ? document.body : null;

    mediaQuery.setMatches(false);

    assert.equal(document.activeElement, toggle);
    assert.equal(document.body.focusCalls, 0);
    assert.equal(toggle.focused, true);
  });
}

test("narrow-to-desktop restores an available focus target outside the menu", () => {
  const { document, mainControl, mediaQuery, toggle } = createNavigation(true);
  toggle.click();
  mainControl.focus();

  mediaQuery.setMatches(false);

  assert.equal(document.activeElement, mainControl);
  assert.equal(document.body.focusCalls, 0);
  assert.equal(mainControl.focusCalls, 2);
  assert.equal(toggle.focused, false);
});

const unavailableFocusStates = [
  {
    name: "hidden property",
    apply(element) {
      element.hidden = true;
    }
  },
  {
    name: "hidden attribute",
    apply(element) {
      element.setAttribute("hidden", "");
    }
  },
  {
    name: "inert property",
    apply(element) {
      element.inert = true;
    }
  },
  {
    name: "inert attribute",
    apply(element) {
      element.setAttribute("inert", "");
    }
  },
  {
    name: "aria-hidden",
    apply(element) {
      element.setAttribute("aria-hidden", "true");
    }
  },
  {
    name: "display none",
    apply(element) {
      element.computedDisplay = "none";
    }
  },
  {
    name: "visibility hidden",
    apply(element) {
      element.computedVisibility = "hidden";
    }
  },
  {
    name: "visibility collapse",
    apply(element) {
      element.computedVisibility = "collapse";
    }
  },
  {
    name: "opacity zero",
    apply(element) {
      element.computedOpacity = "0";
    }
  }
];

for (const state of unavailableFocusStates) {
  for (const scope of ["focused element", "ancestor"]) {
    test(`narrow-to-desktop rejects focus when ${state.name} applies to ${scope}`, () => {
      const { dialog, document, mediaQuery, menuContainer, panel, toggle } =
        createNavigation(true);
      toggle.click();
      dialog.navigationLink.focus();

      let stateElement = dialog.navigationLink;
      if (scope === "ancestor") {
        stateElement = new Control(document, menuContainer);
        dialog.navigationLink.parentElement = stateElement;
      }

      state.apply(stateElement);
      mediaQuery.setMatches(false);

      assert.equal(dialog.open, false);
      assert.equal(menuContainer.parentElement, panel);
      assert.equal(document.activeElement, toggle);
      assert.equal(toggle.focused, true);
    });
  }
}

test("failed showModal resets navigation state and rethrows the original error", () => {
  const { dialog, layout, toggle } = createNavigation(true);
  const showModalError = new Error("showModal failed");
  dialog.showModalError = showModalError;

  assert.throws(
    () => toggle.invokeClickHandler(),
    (error) => error === showModalError
  );

  assert.equal(dialog.open, false);
  assert.equal(dialog.modal, false);
  assert.equal(dialog.classList.contains("active"), false);
  assert.equal(dialog.classList.contains("is-modal"), false);
  assert.equal(layout.classList.contains("navigation-open"), false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
});

test("closed narrow-to-desktop resize leaves page focus unchanged", () => {
  const { dialog, document, mainControl, mediaQuery, toggle } =
    createNavigation(true);
  mainControl.focus();

  mediaQuery.setMatches(false);

  assert.equal(dialog.open, false);
  assert.equal(document.activeElement, mainControl);
  assert.equal(toggle.focused, false);
});

test("resize while closed does not open navigation; next narrow open is modal", () => {
  const { dialog, mediaQuery, menuContainer, panel, toggle } =
    createNavigation(false);

  mediaQuery.setMatches(true);

  assert.equal(dialog.open, false);
  assert.equal(panel.hidden, true);
  assert.equal(menuContainer.parentElement, dialog);
  toggle.click();

  assert.equal(dialog.open, true);
  assert.equal(dialog.modal, true);
});

test("app starts CRUD before propagating missing navigation markup", async () => {
  const fixture = createAppFixture(
    [
      {
        id: 17,
        name: "Ada Lovelace",
        email: "ada@example.com",
        location: "Londres",
        image_url: null
      }
    ],
    { includeNavigationPanel: false }
  );
  const previousGlobals = {
    document: globalThis.document,
    window: globalThis.window,
    fetch: globalThis.fetch,
    Element: globalThis.Element,
    HTMLDialogElement: globalThis.HTMLDialogElement
  };
  const fetchCalls = [];

  globalThis.document = fixture.document;
  globalThis.window = { matchMedia: () => fixture.mediaQuery };
  globalThis.Element = AppElement;
  globalThis.HTMLDialogElement = AppDialog;
  globalThis.fetch = async (...fetchArguments) => {
    fetchCalls.push(fetchArguments);
    return {
      ok: true,
      status: 200,
      json: async () => fixture.users
    };
  };

  try {
    await assert.rejects(import("../app.js?missing-navigation-panel-test"), {
      name: "TypeError"
    });
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(fetchCalls.length, 1);
    assert.equal(fixture.controls.newUserButton.disabled, false);
    assert.equal(
      fixture.controls.tableBody.querySelectorAll("button[data-action]").length,
      2
    );
  } finally {
    for (const [name, value] of Object.entries(previousGlobals)) {
      if (value === undefined) {
        delete globalThis[name];
      } else {
        globalThis[name] = value;
      }
    }
  }
});

test("real app.js opens and closes desktop CRUD dialogs with focus return", async () => {
  const fixture = createAppFixture([
    {
      id: 17,
      name: "Ada Lovelace",
      email: "ada@example.com",
      location: "Londres",
      image_url: null
    }
  ]);
  const previousGlobals = {
    document: globalThis.document,
    window: globalThis.window,
    fetch: globalThis.fetch,
    Element: globalThis.Element,
    HTMLDialogElement: globalThis.HTMLDialogElement
  };
  const fetchCalls = [];

  globalThis.document = fixture.document;
  globalThis.window = { matchMedia: () => fixture.mediaQuery };
  globalThis.Element = AppElement;
  globalThis.HTMLDialogElement = AppDialog;
  globalThis.fetch = async (...fetchArguments) => {
    fetchCalls.push(fetchArguments);
    return {
      ok: true,
      status: 200,
      json: async () => fixture.users
    };
  };

  try {
    await import("../app.js?crud-integration-test");
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0][0], "api/users");
    assert.deepEqual(fetchCalls[0][1], {});
    assert.equal(fixture.controls.newUserButton.disabled, false);
    assert.equal(
      fixture.controls.tableBody.querySelectorAll("button[data-action]").length,
      2
    );

    fixture.navigationToggle.focus();
    fixture.navigationToggle.click();

    assert.equal(fixture.navigationDialog.open, false);
    assert.equal(fixture.navigationDialog.modal, false);
    assert.equal(fixture.menuContainer.parentElement, fixture.navigationPanel);
    assert.equal(fixture.layout.classList.contains("navigation-open"), true);
    assert.equal(fixture.navigationToggle.getAttribute("aria-expanded"), "true");

    fixture.controls.newUserButton.focus();
    fixture.controls.newUserButton.click();

    assert.equal(fixture.controls.userDialog.open, true);
    assert.equal(fixture.controls.userDialog.modal, true);
    assert.equal(fixture.controls.userDialog.showModalCalls, 1);
    assert.equal(fixture.document.activeElement, fixture.controls.nameInput);
    assert.equal(fixture.layout.classList.contains("navigation-open"), true);

    fixture.controls.userDialogCancel.click();
    assert.equal(fixture.controls.userDialog.open, false);
    assert.equal(fixture.document.activeElement, fixture.controls.newUserButton);
    await flushCloseEvents();

    fixture.navigationDialog.collapseButton.click();
    assert.equal(fixture.layout.classList.contains("navigation-collapsed"), true);

    const editButton = fixture.controls.tableBody
      .querySelectorAll("button[data-action]")
      .find((button) => button.dataset.action === "edit");
    editButton.focus();
    const editClick = new Event("click");
    Object.defineProperty(editClick, "target", { configurable: true, value: editButton });
    fixture.controls.tableBody.dispatchEvent(editClick);

    assert.equal(fixture.controls.userDialog.open, true);
    assert.equal(fixture.controls.userDialogTitle.textContent, "Editar usuário");
    assert.equal(fixture.controls.nameInput.value, "Ada Lovelace");
    assert.equal(fixture.document.activeElement, fixture.controls.nameInput);
    fixture.controls.userDialogClose.click();
    assert.equal(fixture.controls.userDialog.open, false);
    assert.equal(fixture.document.activeElement, editButton);
    assert.equal(fixture.layout.classList.contains("navigation-collapsed"), true);
    await flushCloseEvents();

    fixture.navigationToggle.click();
    fixture.navigationDialog.closeButton.click();
    assert.equal(fixture.layout.classList.contains("navigation-open"), false);

    const deleteButton = fixture.controls.tableBody
      .querySelectorAll("button[data-action]")
      .find((button) => button.dataset.action === "delete");
    deleteButton.focus();
    const click = new Event("click");
    Object.defineProperty(click, "target", { configurable: true, value: deleteButton });
    fixture.controls.tableBody.dispatchEvent(click);

    assert.equal(fixture.controls.deleteDialog.open, true);
    assert.equal(fixture.controls.deleteDialog.modal, true);
    assert.equal(fixture.controls.deleteDialog.showModalCalls, 1);
    assert.equal(
      fixture.document.activeElement,
      fixture.controls.deleteDialogCancel
    );
    assert.equal(
      fixture.controls.deleteDialogMessage.textContent,
      "Excluir Ada Lovelace? Esta ação não pode ser desfeita."
    );
    fixture.controls.deleteDialogCancel.click();
    assert.equal(fixture.controls.deleteDialog.open, false);
    assert.equal(fixture.document.activeElement, deleteButton);
    assert.equal(fixture.layout.classList.contains("navigation-open"), false);
    await flushCloseEvents();

    fixture.navigationToggle.click();
    fixture.controls.newUserButton.focus();
    fixture.controls.newUserButton.click();
    fixture.controls.userForm.focus();
    fixture.mediaQuery.setMatches(true);

    assert.equal(fixture.controls.userDialog.open, true);
    assert.equal(fixture.controls.userDialog.modal, true);
    assert.equal(fixture.document.activeElement, fixture.controls.userForm);
    assert.equal(fixture.navigationDialog.open, false);
    assert.equal(fixture.navigationPanel.hidden, true);
    assert.equal(fixture.menuContainer.parentElement, fixture.navigationDialog);
    assert.equal(fixture.layout.classList.contains("navigation-open"), false);
    assert.equal(fixture.navigationToggle.getAttribute("aria-expanded"), "false");
    assert.equal(fixture.controls.userDialog.open, true);
    assert.equal(fixture.document.activeElement, fixture.controls.userForm);
    assert.equal(fetchCalls.length, 1);

    fixture.mediaQuery.setMatches(false);

    assert.equal(fixture.controls.userDialog.open, true);
    assert.equal(fixture.navigationDialog.open, false);
    assert.equal(fixture.layout.classList.contains("navigation-open"), false);
    assert.equal(fixture.document.activeElement, fixture.controls.userForm);
    assert.equal(fetchCalls.length, 1);

    fixture.controls.userDialogCancel.click();
    assert.equal(fixture.controls.userDialog.open, false);
    assert.equal(fixture.document.activeElement, fixture.controls.newUserButton);
    await flushCloseEvents();
  } finally {
    for (const [name, value] of Object.entries(previousGlobals)) {
      if (value === undefined) {
        delete globalThis[name];
      } else {
        globalThis[name] = value;
      }
    }
  }
});

test("idle CRUD dialogs close on Escape and cancel and restore trigger focus", async () => {
  const users = [
    {
      id: 17,
      name: "Ada Lovelace",
      email: "ada@example.com",
      location: "Londres",
      image_url: null
    }
  ];
  const fixture = createAppFixture(users);

  await withInitializedApp(
    fixture,
    async () => ({
      ok: true,
      status: 200,
      json: async () => users
    }),
    "crud-idle-dialog-focus-test",
    async () => {
      const userTrigger = fixture.controls.newUserButton;
      userTrigger.focus();
      userTrigger.click();

      const userEscape = new Event("keydown", { cancelable: true });
      Object.defineProperty(userEscape, "key", { value: "Escape" });
      fixture.controls.userDialog.dispatchEvent(userEscape);

      assert.equal(userEscape.defaultPrevented, true);
      assert.equal(fixture.controls.userDialog.open, false);
      await flushCloseEvents();
      assert.equal(fixture.document.activeElement, userTrigger);

      userTrigger.click();
      const userCancel = new Event("cancel", { cancelable: true });
      fixture.controls.userDialog.dispatchEvent(userCancel);

      assert.equal(userCancel.defaultPrevented, false);
      assert.equal(fixture.controls.userDialog.open, false);
      await flushCloseEvents();
      assert.equal(fixture.document.activeElement, userTrigger);

      const deleteTrigger = fixture.controls.tableBody
        .querySelectorAll("button[data-action]")
        .find((button) => button.dataset.action === "delete");
      deleteTrigger.focus();
      const deleteClick = new Event("click");
      Object.defineProperty(deleteClick, "target", {
        configurable: true,
        value: deleteTrigger
      });
      fixture.controls.tableBody.dispatchEvent(deleteClick);

      const deleteEscape = new Event("keydown", { cancelable: true });
      Object.defineProperty(deleteEscape, "key", { value: "Escape" });
      fixture.controls.deleteDialog.dispatchEvent(deleteEscape);

      assert.equal(deleteEscape.defaultPrevented, true);
      assert.equal(fixture.controls.deleteDialog.open, false);
      await flushCloseEvents();
      assert.equal(fixture.document.activeElement, deleteTrigger);

      deleteTrigger.focus();
      const secondDeleteClick = new Event("click");
      Object.defineProperty(secondDeleteClick, "target", {
        configurable: true,
        value: deleteTrigger
      });
      fixture.controls.tableBody.dispatchEvent(secondDeleteClick);
      const deleteCancel = new Event("cancel", { cancelable: true });
      fixture.controls.deleteDialog.dispatchEvent(deleteCancel);

      assert.equal(deleteCancel.defaultPrevented, false);
      assert.equal(fixture.controls.deleteDialog.open, false);
      await flushCloseEvents();
      assert.equal(fixture.document.activeElement, deleteTrigger);
    }
  );
});

test("busy user dialog prevents Escape and cancel from closing", async () => {
  const users = [];
  const fixture = createAppFixture(users);
  const pendingRequest = new Promise(() => {});

  await withInitializedApp(
    fixture,
    async (_url, options) => {
      if (options?.method) {
        return pendingRequest;
      }

      return {
        ok: true,
        status: 200,
        json: async () => users
      };
    },
    "crud-user-busy-dialog-test",
    async () => {
      fixture.controls.newUserButton.focus();
      fixture.controls.newUserButton.click();
      fixture.controls.userForm.dispatchEvent(
        new Event("submit", { cancelable: true })
      );

      assert.equal(fixture.controls.userDialog.open, true);
      assert.equal(fixture.controls.userDialogCancel.disabled, true);
      fixture.controls.userDialogCancel.focus();
      assert.equal(fixture.document.activeElement, fixture.controls.userForm);

      const escape = new Event("keydown", { cancelable: true });
      Object.defineProperty(escape, "key", { value: "Escape" });
      fixture.controls.userDialog.dispatchEvent(escape);

      assert.equal(escape.defaultPrevented, true);
      assert.equal(fixture.controls.userDialog.open, true);

      const cancel = new Event("cancel", { cancelable: true });
      fixture.controls.userDialog.dispatchEvent(cancel);

      assert.equal(cancel.defaultPrevented, true);
      assert.equal(fixture.controls.userDialog.open, true);
    }
  );
});

test("busy delete dialog prevents Escape and cancel from closing", async () => {
  const users = [
    {
      id: 17,
      name: "Ada Lovelace",
      email: "ada@example.com",
      location: "Londres",
      image_url: null
    }
  ];
  const fixture = createAppFixture(users);
  const pendingRequest = new Promise(() => {});

  await withInitializedApp(
    fixture,
    async (_url, options) => {
      if (options?.method) {
        return pendingRequest;
      }

      return {
        ok: true,
        status: 200,
        json: async () => users
      };
    },
    "crud-delete-busy-dialog-test",
    async () => {
      const deleteTrigger = fixture.controls.tableBody
        .querySelectorAll("button[data-action]")
        .find((button) => button.dataset.action === "delete");
      deleteTrigger.focus();
      const click = new Event("click");
      Object.defineProperty(click, "target", {
        configurable: true,
        value: deleteTrigger
      });
      fixture.controls.tableBody.dispatchEvent(click);
      fixture.controls.deleteConfirmButton.click();

      assert.equal(fixture.controls.deleteDialog.open, true);
      assert.equal(fixture.controls.deleteDialogCancel.disabled, true);
      fixture.controls.deleteDialogCancel.focus();
      assert.equal(
        fixture.document.activeElement,
        fixture.controls.deleteDialogContent
      );

      const escape = new Event("keydown", { cancelable: true });
      Object.defineProperty(escape, "key", { value: "Escape" });
      fixture.controls.deleteDialog.dispatchEvent(escape);

      assert.equal(escape.defaultPrevented, true);
      assert.equal(fixture.controls.deleteDialog.open, true);

      const cancel = new Event("cancel", { cancelable: true });
      fixture.controls.deleteDialog.dispatchEvent(cancel);

      assert.equal(cancel.defaultPrevented, true);
      assert.equal(fixture.controls.deleteDialog.open, true);
    }
  );
});

test("markup and local CSS preserve one accessible menu across responsive wrappers", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const navigationScript = await readFile(
    new URL("../navigation.mjs", import.meta.url),
    "utf8"
  );
  const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
  const coreStyles = await readFile(
    new URL("../assets/vendor/govbr-core-3.7.0/core.min.css", import.meta.url),
    "utf8"
  );
  const panel = html.match(
    /<aside class="br-menu navigation-surface navigation-panel"[\s\S]*?<\/aside>/
  )?.[0];
  const dialog = html.match(
    /<dialog class="br-menu navigation-surface navigation-dialog"[^>]*>[\s\S]*?<\/dialog>/
  )?.[0];
  const toggleButton = html.match(/<button[^>]*id="navigation-toggle"[\s\S]*?<\/button>/)?.[0];
  const closeButton = panel?.match(/<button[^>]*data-menu-close[\s\S]*?<\/button>/)?.[0];
  const collapseButton = panel?.match(/<button[^>]*data-menu-collapse[\s\S]*?<\/button>/)?.[0];
  const links = [...(panel?.matchAll(/<a class="menu-item[^>]*>([\s\S]*?)<\/a>/g) ?? [])];

  assert.ok(panel);
  assert.ok(dialog);
  assert.ok(toggleButton);
  assert.match(panel, /aria-labelledby="navigation-title"/);
  assert.match(dialog, /aria-labelledby="navigation-title"/);
  assert.match(panel, /id="navigation-panel"/);
  assert.match(toggleButton, /aria-controls="navigation-panel"/);
  assert.match(panel, /<nav class="menu-body" aria-label="Navegação principal">/);
  assert.match(panel, /<nav class="menu-links" aria-label="Links do menu">/);
  assert.match(panel, /aria-current="page"/);
  assert.equal([...html.matchAll(/class="menu-container"/g)].length, 1);
  assert.doesNotMatch(dialog, /class="menu-container"/);
  assert.doesNotMatch(dialog, /\brole\s*=/);
  assert.doesNotMatch(dialog, /aria-modal|(?:^|\s)inert(?:\s|=|>)/);
  assert.match(toggleButton, /aria-label="Navegação"/);
  assert.match(toggleButton, /aria-expanded="false"/);
  assert.match(toggleButton, /bars\.svg[^>]*alt=""/);
  assert.doesNotMatch(
    navigationScript,
    /classList\.(?:add|remove)\("active"(?:,|\))/
  );
  assert.ok(closeButton);
  assert.match(closeButton, /aria-label="Fechar"/);
  assert.match(closeButton, /title="Fechar"/);
  assert.match(closeButton, /times\.svg[^>]*alt=""/);
  assert.doesNotMatch(closeButton, /<span[^>]*>\s*Fechar\s*<\/span>/);
  assert.ok(collapseButton);
  assert.match(collapseButton, /aria-pressed="false"/);
  assert.match(collapseButton, /aria-controls="navigation-panel"/);
  assert.match(collapseButton, /aria-label="Modo compacto"/);
  assert.match(collapseButton, /title="Ativar modo compacto"/);
  assert.match(collapseButton, /chevron-left\.svg"[^>]*data-menu-collapse-icon alt=""/);
  assert.doesNotMatch(collapseButton, /bars\.svg/);
  assert.match(collapseButton, /<span data-menu-collapse-label>Modo compacto<\/span>/);
  assert.equal(links.length, 4);

  for (const [, linkContent] of links) {
    assert.match(linkContent, /<img[^>]*class="icon menu-icon"[^>]*alt=""/);
    assert.match(linkContent, /<span class="content">[^<]+<\/span>/);
  }

  const mobileNavigationStyles = extractCssBlocks(
    styles,
    "@media (max-width: 767.98px)"
  ).find((block) => block.includes(".navigation-dialog .menu-collapse"));
  const mobileTableStyles = extractCssBlocks(
    styles,
    "@media (max-width: 767.98px)"
  ).find((block) => block.includes(".table-scroll thead.table-head-hidden-in-cards"));
  const compactScreenReaderRule = extractCssRule(
    styles,
    ".app-layout.navigation-collapsed .navigation-panel .menu-title span"
  );
  const mobileScreenReaderRule = extractCssRule(
    mobileTableStyles ?? "",
    ".table-scroll thead.table-head-hidden-in-cards"
  );
  const localMenuContainerRule = extractCssRule(
    styles,
    ".navigation-surface .menu-container"
  );
  const localMenuPanelRule = extractCssRule(
    styles,
    ".navigation-surface .menu-panel"
  );
  const menuBodyRule = extractCssRule(styles, ".navigation-surface .menu-body");
  const focusVisibleRule = extractCssRule(styles, ":focus-visible");
  const vendorMenuContainerRule = extractCssRule(
    coreStyles,
    ".br-menu .menu-container"
  );
  const vendorActiveMenuContainerRule = extractCssRule(
    coreStyles,
    ".br-menu.active .menu-container"
  );
  const vendorActiveMenuPanelRule = extractCssRule(
    coreStyles,
    ".br-menu.active .menu-panel"
  );
  const vendorActiveMenuScrimRule = extractCssRule(
    coreStyles,
    ".br-menu.active .menu-scrim"
  );
  const desktopPanelRule = extractCssRule(
    styles,
    ".app-layout.navigation-open .navigation-panel"
  );
  const closedPanelRule = extractCssRule(styles, ".navigation-panel");
  const narrowHiddenPanelRule = extractCssRule(
    styles,
    ".app-layout.navigation-open .navigation-panel[hidden]"
  );
  const expandedLayoutRule = extractCssRule(
    styles,
    ".app-layout.navigation-open"
  );
  const compactLayoutRule = extractCssRule(
    styles,
    ".app-layout.navigation-open.navigation-collapsed"
  );
  const mobileDialogRule = extractCssRule(
    mobileNavigationStyles ?? "",
    ".navigation-dialog.is-modal"
  );
  const mobileMenuPanelRule = extractCssRule(
    mobileNavigationStyles ?? "",
    ".navigation-dialog.is-modal .menu-panel"
  );
  const mobileMenuContainerRule = extractCssRule(
    mobileNavigationStyles ?? "",
    ".navigation-dialog.is-modal .menu-container"
  );
  const mobileBackdropRule = extractCssRule(
    mobileNavigationStyles ?? "",
    ".navigation-dialog.is-modal::backdrop"
  );
  const mobileScrimRule = extractCssRule(
    mobileNavigationStyles ?? "",
    ".navigation-dialog.is-modal .menu-scrim"
  );
  const desktopScrimRule = extractCssRule(
    styles,
    ".navigation-surface .menu-scrim"
  );

  assert.ok(mobileNavigationStyles);
  assert.ok(localMenuContainerRule);
  assert.deepEqual(localMenuContainerRule.selectors, [
    ".navigation-surface .menu-container"
  ]);
  assert.match(localMenuContainerRule.content, /display:\s*flex;/);
  assert.match(localMenuContainerRule.content, /height:\s*100%;/);
  assert.ok(vendorMenuContainerRule);
  assert.deepEqual(vendorMenuContainerRule.selectors, [".br-menu .menu-container"]);
  assert.match(vendorMenuContainerRule.content, /display:none/);
  assert.ok(vendorActiveMenuContainerRule);
  assert.match(vendorActiveMenuContainerRule.content, /position:fixed/);
  assert.ok(vendorActiveMenuPanelRule);
  assert.match(vendorActiveMenuPanelRule.content, /overflow:auto/);
  assert.ok(vendorActiveMenuScrimRule);
  assert.match(vendorActiveMenuScrimRule.content, /position:absolute/);
  assert.ok(localMenuPanelRule);
  assert.match(localMenuPanelRule.content, /display:\s*flex;/);
  assert.match(localMenuPanelRule.content, /height:\s*auto;/);
  assert.match(localMenuPanelRule.content, /min-height:\s*100%;/);
  assert.match(localMenuPanelRule.content, /overflow-y:\s*auto;/);
  assert.match(localMenuPanelRule.content, /background:\s*var\(--pure-0\);/);
  assert.ok(menuBodyRule);
  assert.match(menuBodyRule.content, /padding:\s*var\(--spacing-scale-base\);/);
  assert.ok(focusVisibleRule);
  assert.match(focusVisibleRule.content, /outline:\s*3px solid/);
  assert.match(focusVisibleRule.content, /outline-offset:\s*3px;/);
  assert.doesNotMatch(styles, /\.navigation-collapsed[^{}]*\.menu-body/);
  assert.doesNotMatch(styles, /\.navigation-(?:panel|dialog)\.active/);
  assert.ok(desktopPanelRule);
  assert.match(desktopPanelRule.content, /display:\s*block;/);
  assert.ok(closedPanelRule);
  assert.match(closedPanelRule.content, /display:\s*none;/);
  assert.ok(narrowHiddenPanelRule);
  assert.match(narrowHiddenPanelRule.content, /display:\s*none;/);
  assert.ok(expandedLayoutRule);
  assert.match(expandedLayoutRule.content, /minmax\(0,\s*320px\)/);
  assert.ok(compactLayoutRule);
  assert.match(compactLayoutRule.content, /var\(--spacing-scale-10x\)/);
  assert.ok(mobileDialogRule);
  assert.match(mobileDialogRule.content, /position:\s*fixed;/);
  assert.match(mobileDialogRule.content, /inset:\s*0;/);
  assert.ok(mobileMenuContainerRule);
  assert.match(mobileMenuContainerRule.content, /position:\s*fixed;/);
  assert.match(mobileMenuContainerRule.content, /display:\s*flex;/);
  assert.match(mobileMenuContainerRule.content, /inset:\s*0;/);
  assert.ok(mobileMenuPanelRule);
  assert.match(mobileMenuPanelRule.content, /width:\s*min\(320px,\s*85vw\);/);
  assert.match(mobileMenuPanelRule.content, /height:\s*100%;/);
  assert.ok(mobileBackdropRule);
  assert.match(mobileBackdropRule.content, /background:\s*var\(--surface-overlay-scrim\);/);
  assert.ok(mobileScrimRule);
  assert.match(mobileScrimRule.content, /display:\s*block;/);
  assert.match(mobileScrimRule.content, /flex:\s*1;/);
  assert.match(mobileScrimRule.content, /position:\s*relative;/);
  assert.match(mobileScrimRule.content, /background:\s*transparent;/);
  assert.ok(desktopScrimRule);
  assert.match(desktopScrimRule.content, /display:\s*none;/);
  assert.match(
    mobileNavigationStyles,
    /\.navigation-dialog \.menu-collapse\s*\{\s*display:\s*none;\s*\}/
  );
  assert.match(
    mobileNavigationStyles,
    /\.navigation-dialog \.menu-footer\s*\{\s*display:\s*none;\s*\}/
  );
  assert.ok(compactScreenReaderRule);
  assert.deepEqual(compactScreenReaderRule.selectors, [
    ".app-layout.navigation-collapsed .navigation-panel .menu-title span",
    ".app-layout.navigation-collapsed .navigation-panel .menu-collapse [data-menu-collapse-label]",
    ".app-layout.navigation-collapsed .navigation-panel .menu-item .content"
  ]);
  assert.deepEqual(normalizeCssDeclarations(compactScreenReaderRule.content), [
    "position: absolute",
    "width: 1px",
    "height: 1px",
    "overflow: hidden",
    "clip: rect(0, 0, 0, 0)",
    "clip-path: inset(50%)",
    "white-space: nowrap"
  ]);
  assert.doesNotMatch(compactScreenReaderRule.content, /display:\s*none/);
  assert.doesNotMatch(styles, /navigation-collapsed[^{}]*\.content\s*\{\s*display:\s*none/);
  assert.ok(mobileScreenReaderRule);
  assert.deepEqual(mobileScreenReaderRule.selectors, [
    ".table-scroll thead.table-head-hidden-in-cards"
  ]);
  assert.deepEqual(normalizeCssDeclarations(mobileScreenReaderRule.content), [
    "position: absolute",
    "width: 1px",
    "height: 1px",
    "margin: -1px",
    "overflow: hidden",
    "clip: rect(0, 0, 0, 0)",
    "border: 0"
  ]);
  assert.match(html, /<dialog[^>]*id="user-dialog"/);
  assert.match(html, /<dialog[^>]*id="delete-dialog"/);
});

test("footer logo CSS extraction ignores comments and captures later rules", () => {
  assert.deepEqual(normalizeCssDeclarations("/* note */ width: 40px;"), [
    "width: 40px"
  ]);

  const commentedWidth = extractFooterLogoSizingRules(`
    /* .footer-logo { width: 999px; } */
    /* Comment before selector. */
    .br-footer .footer-logo /* Ignore this brace: } */ {
      /* Keep this declaration visible to the sizing check. */
      width: 40px;
    }
  `);
  const duplicateTopLevelRules = extractFooterLogoSizingRules(`
    .br-footer .footer-logo { width: auto; }
    .br-footer .footer-logo { height: 42px; }
  `);
  const nestedMediaRules = extractFooterLogoSizingRules(`
    @media (max-width: 767px) {
      @supports (min-width: 320px) {
        .br-footer .footer-logo {
          width: 80px;
          min-width: 40px;
          max-width: 120px;
          font-size: 14px;
          zoom: 1;
          transform: scale(1);
          scale: 1.2;
          flex: 1;
          flex-basis: auto;
        }
      }
    }
  `);
  const ruleAfterAtRule = extractFooterLogoSizingRules(`
    @media (max-width: 767px) {
      .br-footer .footer-logo { width: 80px; }
    }
    .br-footer .footer-logo { height: 42px; }
  `);
  const containerSizing = extractFooterLogoSizingRules(`
    .br-footer { font-size: 14px; }
    footer img { transform: scale(1.1); }
    .footer-brand { zoom: 1.2; }
    .footer-layout { width: 100%; }
    footer { height: 100%; }
    .br-footer .footer-links ul { padding: 0; }
    .footer { width: 999px; }
    .menu-footer { width: 999px; }
    .footer-logo-x { width: 999px; }
    .unrelated { width: 999px; }
    .unrelated img { height: 999px; }
  `);

  assert.deepEqual(commentedWidth, [
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["width: 40px"]
    }
  ]);
  assert.deepEqual(duplicateTopLevelRules, [
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["width: auto"]
    },
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["height: 42px"]
    }
  ]);
  assert.deepEqual(nestedMediaRules, [
    {
      selectors: [".br-footer .footer-logo"],
      declarations: [
        "width: 80px",
        "min-width: 40px",
        "max-width: 120px",
        "font-size: 14px",
        "zoom: 1",
        "transform: scale(1)",
        "scale: 1.2",
        "flex: 1",
        "flex-basis: auto"
      ]
    }
  ]);
  assert.deepEqual(ruleAfterAtRule, [
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["width: 80px"]
    },
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["height: 42px"]
    }
  ]);
  assert.deepEqual(containerSizing, [
    {
      selectors: [".br-footer"],
      declarations: ["font-size: 14px"]
    },
    {
      selectors: ["footer img"],
      declarations: ["transform: scale(1.1)"]
    },
    {
      selectors: [".footer-brand"],
      declarations: ["zoom: 1.2"]
    },
    {
      selectors: [".footer-layout"],
      declarations: ["width: 100%"]
    },
    {
      selectors: ["footer"],
      declarations: ["height: 100%"]
    }
  ]);
});

test("footer logo sizing extraction detects image and SVG selectors and sizing properties", () => {
  const sizingFixtures = [
    ["footer img", "width", "40px"],
    [".footer-layout img", "height", "40px"],
    [".footer-content img", "min-width", "10px"],
    [".footer-brand img", "max-width", "100%"],
    [".footer-anatel img", "min-height", "10px"],
    [".footer-govbr img", "max-height", "50px"],
    [".br-footer img", "inline-size", "40px"],
    [".footer-logo", "block-size", "40px"],
    ["footer svg", "min-inline-size", "10px"],
    [".footer-layout svg", "max-inline-size", "40px"],
    [".footer-content svg", "min-block-size", "10px"],
    [".footer-brand svg", "max-block-size", "50px"],
    [".footer-anatel svg", "aspect-ratio", "1 / 1"],
    [".footer-govbr img", "font-size", "14px"],
    [".footer-govbr img", "font", "14px Arial"],
    [".footer-anatel img", "zoom", "1"],
    [".footer-govbr img", "transform", "scale(1)"],
    [".footer-anatel img", "scale", "1.2"],
    [".footer-govbr img", "flex", "1"],
    [".footer-anatel img", "flex-basis", "auto"],
    [".footer-govbr img", "flex-grow", "1"],
    [".footer-anatel img", "flex-shrink", "0"],
    [".footer-govbr img", "padding", "0 4px"],
    [".footer-govbr img", "padding-inline", "4px"],
    [".footer-anatel img", "border", "1px solid"],
    [".footer-anatel img", "border-block-width", "1px"],
    [".footer-govbr img", "box-sizing", "border-box"],
    [".footer-govbr svg", "width", "40px"],
    [".br-footer svg", "height", "40px"],
    [".footer-logo svg", "max-width", "100%"],
    [".br-footer", "font-size", "14px"],
    ["footer img", "transform", "scale(1.1)"],
    [".footer-brand", "zoom", "1.2"],
    [".footer-layout", "width", "100%"]
  ];
  const styles = [
    "/* .footer-logo { width: 999px; } */",
    ...sizingFixtures.map(
      ([selector, property, value]) =>
        `/* Comment before selector. */ ${selector} /* Ignore { } here. */ { ${property}: ${value}; }`
    ),
    ".footer { width: 999px; }",
    ".menu-footer { width: 999px; }",
    ".footer-logo-x { width: 999px; }",
    ".unrelated { width: 999px; }",
    ".unrelated img { height: 999px; }"
  ].join("\n");
  const extracted = extractFooterLogoSizingRules(styles);

  assert.deepEqual(
    extracted,
    sizingFixtures.map(([selector, property, value]) => ({
      selectors: [selector],
      declarations: [`${property}: ${value}`]
    }))
  );
});

test("footer markup and CSS preserve responsive layout and logo sizing", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
  const footer = html.match(/<footer class="br-footer">[\s\S]*?<\/footer>/)?.[0];
  const footerImages = footer?.match(/<img\b[^>]*>/g) ?? [];
  const anatelWrapper = footer?.match(
    /<div class="footer-brand footer-anatel">([\s\S]*?)<\/div>/
  )?.[1];
  const govbrWrapper = footer?.match(
    /<div class="footer-brand footer-govbr">([\s\S]*?)<\/div>/
  )?.[1];
  const mobileFooterRule = extractCssRule(styles, ".br-footer .footer-layout");
  const footerBrandRule = extractCssRule(styles, ".br-footer .footer-brand");
  const footerLogoRule = extractCssRule(styles, ".br-footer .footer-logo");
  const footerAnatelLogoRule = extractCssRule(
    styles,
    ".br-footer .footer-anatel .footer-logo"
  );
  const footerRule = extractCssRule(styles, ".br-footer {");
  const footerGovbrLogoRule = extractCssRule(
    styles,
    ".br-footer .footer-govbr .footer-logo"
  );
  const footerContentRule = extractCssRule(
    styles,
    ".br-footer .footer-content"
  );
  const desktopFooterStyles = extractCssBlocks(
    styles,
    "@media (min-width: 576px)"
  ).find((block) => block.includes(".br-footer .footer-layout"));
  const desktopFooterRule = extractCssRule(
    desktopFooterStyles ?? "",
    ".br-footer .footer-layout"
  );
  const footerLogoSizingRules = extractFooterLogoSizingRules(styles);

  assert.ok(footer);
  assert.ok(anatelWrapper);
  assert.equal(
    anatelWrapper.trim(),
    '<img class="footer-logo" src="assets/brand/Anatel_Logo.svg" alt="Logotipo da Anatel">'
  );
  assert.ok(govbrWrapper);
  assert.equal(
    govbrWrapper.trim(),
    '<img class="footer-logo" src="assets/brand/Gov.br_logo.svg" alt="Logotipo gov.br">'
  );
  assert.equal(
    [...(footer?.matchAll(/<div class="footer-brand footer-anatel">/g) ?? [])]
      .length,
    1
  );
  assert.equal(
    [...(footer?.matchAll(/<div class="footer-brand footer-govbr">/g) ?? [])]
      .length,
    1
  );
  assert.match(
    footer,
    /<div class="footer-layout">\s*<div class="footer-brand footer-anatel">\s*<img class="footer-logo" src="assets\/brand\/Anatel_Logo\.svg" alt="Logotipo da Anatel">\s*<\/div>\s*<div class="footer-brand footer-govbr">\s*<img class="footer-logo" src="assets\/brand\/Gov\.br_logo\.svg" alt="Logotipo gov\.br">\s*<\/div>\s*<div class="footer-content">/
  );
  assert.equal(footerImages.length, 2);
  assert.match(footer, /class="footer-content"/);
  assert.ok(mobileFooterRule);
  assert.deepEqual(mobileFooterRule.selectors, [".br-footer .footer-layout"]);
  assert.deepEqual(normalizeCssDeclarations(mobileFooterRule.content), [
    "display: grid",
    'grid-template-areas: "anatel" "govbr" "content"',
    "grid-template-columns: minmax(0, 1fr)",
    "align-items: center",
    "justify-items: center",
    "gap: var(--spacing-scale-2x)"
  ]);
  assert.ok(footerBrandRule);
  assert.deepEqual(footerBrandRule.selectors, [".br-footer .footer-brand"]);
  assert.deepEqual(normalizeCssDeclarations(footerBrandRule.content), [
    "display: grid",
    "min-width: 0",
    "align-self: stretch",
    "place-items: end center",
    "padding: 0 var(--spacing-scale-half)"
  ]);
  assert.ok(footerLogoRule);
  assert.deepEqual(footerLogoRule.selectors, [".br-footer .footer-logo"]);
  assert.deepEqual(normalizeCssDeclarations(footerLogoRule.content), [
    "display: block",
    "width: auto",
    "max-width: 100%",
    "object-fit: contain"
  ]);

  assert.ok(footerRule);
  assert.deepEqual(footerRule.selectors, [".br-footer"]);
  assert.deepEqual(normalizeCssDeclarations(footerRule.content), [
    "padding: var(--spacing-scale-base) 0",
    "color: var(--gray-80)",
    "background: var(--pure-0)"
  ]);
  assert.ok(footerContentRule);
  assert.deepEqual(footerContentRule.selectors, [".br-footer .footer-content"]);
  assert.deepEqual(normalizeCssDeclarations(footerContentRule.content), [
    "grid-area: content",
    "min-width: 0",
    "line-height: 3",
    "text-align: center"
  ]);
  assert.ok(footerAnatelLogoRule);
  assert.deepEqual(footerAnatelLogoRule.selectors, [
    ".br-footer .footer-anatel .footer-logo"
  ]);
  assert.deepEqual(normalizeCssDeclarations(footerAnatelLogoRule.content), [
    "height: 3em"
  ]);
  assert.ok(footerGovbrLogoRule);
  assert.deepEqual(footerGovbrLogoRule.selectors, [
    ".br-footer .footer-govbr .footer-logo"
  ]);
  assert.deepEqual(normalizeCssDeclarations(footerGovbrLogoRule.content), [
    "height: 3em"
  ]);
  assert.deepEqual(footerLogoSizingRules, [
    {
      selectors: [".br-footer"],
      declarations: ["padding: var(--spacing-scale-base) 0"]
    },
    {
      selectors: [".br-footer .footer-brand"],
      declarations: ["min-width: 0", "padding: 0 var(--spacing-scale-half)"]
    },
    {
      selectors: [".br-footer .footer-logo"],
      declarations: ["width: auto", "max-width: 100%", "object-fit: contain"]
    },
    {
      selectors: [".br-footer .footer-anatel .footer-logo"],
      declarations: ["height: 3em"]
    },
    {
      selectors: [".br-footer .footer-govbr .footer-logo"],
      declarations: ["height: 3em"]
    },
    {
      selectors: [".br-footer .footer-content"],
      declarations: ["min-width: 0"]
    }
  ]);
  assert.ok(desktopFooterRule);
  assert.deepEqual(desktopFooterRule.selectors, [".br-footer .footer-layout"]);
  assert.deepEqual(normalizeCssDeclarations(desktopFooterRule.content), [
    'grid-template-areas: "anatel content govbr"',
    "grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) minmax(0, 1fr)",
    "column-gap: 0"
  ]);
});
