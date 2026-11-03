/**
 * Manage focus and visible errors for the native CRUD dialogs.
 *
 * Importing this module has no DOM side effects.
 */

/**
 * Show and focus an error inside its still-open dialog.
 *
 * @param {HTMLElement} region - Focusable alert region in the dialog.
 * @param {string} message - Error text to display.
 */
export function showDialogError(region, message) {
  region.textContent = message;
  region.hidden = false;
  region.focus();
}

/**
 * Clear a dialog error before opening, retrying, or closing.
 *
 * @param {HTMLElement} region - Alert region in the dialog.
 */
export function clearDialogError(region) {
  region.textContent = "";
  region.hidden = true;
}

/**
 * Keep focus inside an open dialog before disabling its action buttons.
 *
 * @param {Array<{dialog: HTMLDialogElement, focusTarget: HTMLElement}>} dialogs - Dialogs and their focusable content.
 */
export function focusOpenDialog(dialogs) {
  const active = dialogs.find(({ dialog }) => dialog.open);

  if (active) {
    active.focusTarget.focus();
  }
}

/**
 * Restore focus to a rerendered action or a stable fallback.
 *
 * @param {HTMLTableSectionElement} tableBody - Current user table rows.
 * @param {HTMLButtonElement} fallback - Button to focus if the action disappeared.
 * @param {"edit"|"delete"} action - The action that opened the dialog.
 * @param {number|null} userId - The initiating user's identifier, if any.
 */
export function restoreDialogFocus(tableBody, fallback, action, userId) {
  const buttons = tableBody.querySelectorAll("button[data-action]");
  const previousAction = Array.from(buttons).find(
    (button) => button.dataset.action === action && button.dataset.userId === String(userId)
  );

  (previousAction ?? fallback).focus();
}
