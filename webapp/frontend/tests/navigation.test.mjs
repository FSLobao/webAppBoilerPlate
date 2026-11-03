/**
 * Test the native navigation dialog's trigger, controls, and restored state.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { initializeNavigation } from "../navigation.mjs";

class Control extends EventTarget {
  attributes = new Map();
  focused = false;

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  focus() {
    this.focused = true;
  }

  click() {
    this.dispatchEvent(new Event("click"));
  }
}

class Dialog extends EventTarget {
  open = false;
  classes = new Set();
  classList = {
    add: (value) => this.classes.add(value),
    remove: (value) => this.classes.delete(value)
  };
  closeButton = new Control();
  scrim = new Control();

  querySelector(selector) {
    return selector === "[data-menu-close]" ? this.closeButton : this.scrim;
  }

  showModal() {
    assert.equal(this.open, false);
    this.open = true;
  }

  close() {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  }
}

test("opens only once and exposes the expanded state", () => {
  const toggle = new Control();
  const dialog = new Dialog();
  initializeNavigation(toggle, dialog);

  toggle.click();
  toggle.click();

  assert.equal(dialog.open, true);
  assert.equal(dialog.classes.has("active"), true);
  assert.equal(toggle.attributes.get("aria-expanded"), "true");
});

for (const control of ["closeButton", "scrim"]) {
  test(`${control} closes the menu and restores trigger focus`, () => {
    const toggle = new Control();
    const dialog = new Dialog();
    initializeNavigation(toggle, dialog);
    toggle.click();

    dialog[control].click();

    assert.equal(dialog.open, false);
    assert.equal(dialog.classes.has("active"), false);
    assert.equal(toggle.attributes.get("aria-expanded"), "false");
    assert.equal(toggle.focused, true);
  });
}

test("a native dialog close restores the trigger state", () => {
  const toggle = new Control();
  const dialog = new Dialog();
  initializeNavigation(toggle, dialog);
  toggle.click();

  dialog.close();

  assert.equal(toggle.attributes.get("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
});

test("Escape closes the menu and restores trigger focus", () => {
  const toggle = new Control();
  const dialog = new Dialog();
  initializeNavigation(toggle, dialog);
  toggle.click();
  const escape = new Event("keydown", { cancelable: true });
  Object.defineProperty(escape, "key", { value: "Escape" });

  dialog.dispatchEvent(escape);

  assert.equal(escape.defaultPrevented, true);
  assert.equal(dialog.open, false);
  assert.equal(toggle.attributes.get("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
});
