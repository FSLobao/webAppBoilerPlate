/**
 * Test dialog error visibility and focus restoration across CRUD rerenders.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  clearDialogError,
  focusOpenDialog,
  restoreDialogFocus,
  showDialogError
} from "../dialog-accessibility.mjs";

class FocusTarget {
  focused = false;

  focus() {
    this.focused = true;
  }
}

test("dialog errors become visible and receive focus, then clear", () => {
  const alert = new FocusTarget();
  alert.hidden = true;
  alert.textContent = "";

  showDialogError(alert, "Falha simulada.");

  assert.equal(alert.textContent, "Falha simulada.");
  assert.equal(alert.hidden, false);
  assert.equal(alert.focused, true);

  clearDialogError(alert);
  assert.equal(alert.textContent, "");
  assert.equal(alert.hidden, true);
});

test("busy actions move focus inside the open dialog", () => {
  const closedTarget = new FocusTarget();
  const openTarget = new FocusTarget();

  focusOpenDialog([
    { dialog: { open: false }, focusTarget: closedTarget },
    { dialog: { open: true }, focusTarget: openTarget }
  ]);

  assert.equal(closedTarget.focused, false);
  assert.equal(openTarget.focused, true);
});

test("focus returns to the matching action after a table rerender", () => {
  const previous = new FocusTarget();
  previous.dataset = { action: "edit", userId: "42" };
  const other = new FocusTarget();
  other.dataset = { action: "delete", userId: "42" };
  const fallback = new FocusTarget();
  const tableBody = { querySelectorAll: () => [other, previous] };

  restoreDialogFocus(tableBody, fallback, "edit", 42);

  assert.equal(previous.focused, true);
  assert.equal(other.focused, false);
  assert.equal(fallback.focused, false);
});

test("focus falls back when a user action was deleted", () => {
  const fallback = new FocusTarget();
  const tableBody = { querySelectorAll: () => [] };

  restoreDialogFocus(tableBody, fallback, "delete", 42);

  assert.equal(fallback.focused, true);
});
