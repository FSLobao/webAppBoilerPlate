/**
 * Bind the page navigation to a native modal dialog.
 *
 * Importing this module does not attach listeners; the page initializes it once.
 */

/**
 * Synchronize the menu trigger and native dialog without global shortcuts.
 *
 * The native dialog contains focus. Escape and closing controls dismiss it,
 * then focus returns to the trigger.
 *
 * @param {HTMLButtonElement} toggle - Button that opens the navigation.
 * @param {HTMLDialogElement} dialog - Dialog containing close and scrim controls.
 */
export function initializeNavigation(toggle, dialog) {
  const closeButton = dialog.querySelector("[data-menu-close]");
  const scrim = dialog.querySelector("[data-menu-scrim]");

  toggle.addEventListener("click", () => {
    if (dialog.open) {
      return;
    }

    dialog.classList.add("active");

    try {
      dialog.showModal();
    } catch (error) {
      dialog.classList.remove("active");
      throw error;
    }

    toggle.setAttribute("aria-expanded", "true");
  });

  closeButton.addEventListener("click", () => dialog.close());
  scrim.addEventListener("click", () => dialog.close());
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      dialog.close();
    }
  });
  dialog.addEventListener("close", () => {
    dialog.classList.remove("active");
    toggle.setAttribute("aria-expanded", "false");
    toggle.focus();
  });
}
