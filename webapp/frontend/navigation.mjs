/**
 * Bind the page navigation as a non-modal desktop panel and narrow modal.
 *
 * Importing this module does not attach listeners; the page initializes it once.
 */

/**
 * Bind responsive navigation once for the lifetime of the page.
 *
 * Desktop navigation uses a complementary panel. Narrow navigation moves the
 * same menu container into a native modal dialog and restores focus on close.
 * Repeated initialization attaches duplicate listeners and is unsupported.
 *
 * @param {HTMLButtonElement} toggle - Button that opens or expands navigation.
 * @param {HTMLElement} panel - Non-modal desktop wrapper for the menu container.
 * @param {HTMLDialogElement} dialog - Modal narrow-screen wrapper for the menu container.
 * @param {MediaQueryList} mediaQuery - Query for the narrow-screen breakpoint.
 * @throws {Error} If required markup is missing or native dialog opening fails.
 * Errors from `showModal()` are rethrown after navigation state is reset.
 */
export function initializeNavigation(toggle, panel, dialog, mediaQuery) {
  const menuContainer = panel.querySelector(".menu-container");
  const closeButton = menuContainer.querySelector("[data-menu-close]");
  const scrim = menuContainer.querySelector("[data-menu-scrim]");
  const collapseButton = menuContainer.querySelector("[data-menu-collapse]");
  const collapseLabel = collapseButton.querySelector("[data-menu-collapse-label]");
  const collapseIcon = collapseButton.querySelector("[data-menu-collapse-icon]");
  const layout = panel.parentElement;
  const doc = dialog.ownerDocument;
  let isNarrow = mediaQuery.matches;
  let isOpen = false;
  let isCollapsed = false;
  // Ignore only the queued close event from a narrow-to-desktop transfer.
  let ignoreNextCloseEvent = false;

  /**
   * Move the existing menu container into its active responsive wrapper.
   *
   * @param {HTMLElement} target - The desktop panel or narrow dialog.
   */
  function moveMenuContainer(target) {
    if (menuContainer.parentElement !== target) {
      target.append(menuContainer);
    }
  }

  /**
   * Return whether an element remains available for focus.
   *
   * @param {Element|null} element - The element to inspect.
   * @returns {boolean} Whether the element and its ancestors are visible and focusable.
   */
  function isAvailableFocusTarget(element) {
    if (
      !element ||
      !element.isConnected ||
      element.disabled ||
      typeof element.focus !== "function"
    ) {
      return false;
    }

    for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
      if (
        ancestor.hidden ||
        ancestor.hasAttribute?.("hidden") ||
        ancestor.inert ||
        ancestor.hasAttribute?.("inert") ||
        ancestor.getAttribute?.("aria-hidden") === "true"
      ) {
        return false;
      }

      const computedStyle = doc.defaultView?.getComputedStyle(ancestor);

      if (
        computedStyle?.display === "none" ||
        computedStyle?.visibility === "hidden" ||
        computedStyle?.visibility === "collapse" ||
        Number.parseFloat(computedStyle?.opacity) === 0
      ) {
        return false;
      }
    }

    return true;
  }

  /**
   * Return whether an external element can receive restored focus.
   *
   * @param {Element|null} element - The element to inspect.
   * @returns {boolean} Whether focus can return outside the menu.
   */
  function canRestoreExternalFocus(element) {
    return element !== doc.body && isAvailableFocusTarget(element);
  }

  /**
   * Return whether a focused navigation element remains available after transfer.
   *
   * @param {Element|null} element - The element focused before moving the menu.
   * @returns {boolean} Whether focus can remain on the navigation element.
   */
  function canPreserveFocus(element) {
    return menuContainer.contains(element) && isAvailableFocusTarget(element);
  }

  /**
   * Return whether another dialog is open.
   *
   * @returns {boolean} Whether a non-navigation dialog is open.
   */
  function hasOtherOpenDialog() {
    for (const openDialog of doc.querySelectorAll("dialog[open]")) {
      if (openDialog !== dialog) {
        return true;
      }
    }

    return false;
  }

  /**
   * Synchronize responsive visibility, accessible relationships, and state.
   */
  function updateControls() {
    const compactModeTitle = isCollapsed ? "Desativar modo compacto" : "Ativar modo compacto";

    layout.classList.toggle("navigation-open", isOpen);
    layout.classList.toggle("navigation-collapsed", isOpen && isCollapsed);
    panel.hidden = isNarrow;
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", "Navegação");
    toggle.setAttribute("aria-controls", isNarrow ? dialog.id : panel.id);
    collapseButton.setAttribute("aria-label", "Modo compacto");
    collapseButton.setAttribute("aria-pressed", String(isCollapsed));
    collapseButton.setAttribute("aria-controls", isNarrow ? dialog.id : panel.id);
    collapseButton.setAttribute("title", compactModeTitle);
    collapseIcon.src = isCollapsed
      ? "assets/vendor/fontawesome-5.11.2/solid/chevron-right.svg"
      : "assets/vendor/fontawesome-5.11.2/solid/chevron-left.svg";
    collapseLabel.textContent = "Modo compacto";
  }

  /**
   * Close navigation and return focus only when no other dialog is open.
   *
   * @param {boolean} restoreFocus - Whether to focus the navigation trigger.
   */
  function closeNavigation(restoreFocus = true) {
    if (!isOpen) {
      return;
    }

    isOpen = false;
    isCollapsed = false;
    dialog.classList.remove("is-modal");

    if (dialog.open) {
      dialog.close();
    }

    updateControls();

    if (restoreFocus && !hasOtherOpenDialog()) {
      toggle.focus();
    }
  }

  /**
   * Open or expand the panel without stacking a narrow modal over another dialog.
   */
  function openNavigation() {
    if (isOpen) {
      if (!isNarrow && isCollapsed) {
        isCollapsed = false;
        updateControls();
      }

      return;
    }

    if (isNarrow && hasOtherOpenDialog()) {
      return;
    }

    isOpen = true;
    isCollapsed = false;
    updateControls();

    if (!isNarrow) {
      dialog.classList.remove("is-modal");
      return;
    }

    dialog.classList.add("is-modal");

    try {
      dialog.showModal();
    } catch (error) {
      closeNavigation(false);
      throw error;
    }

    if (!canPreserveFocus(doc.activeElement)) {
      closeButton.focus();
    }
  }

  /**
   * Transfer the menu and its focus behavior when the viewport crosses the breakpoint.
   *
   * @param {MediaQueryListEvent} event - The updated media-query state.
   */
  function handleBreakpointChange(event) {
    if (event.matches === isNarrow) {
      return;
    }

    isNarrow = event.matches;
    const focusedElement = doc.activeElement;
    const focusWasInMenu = menuContainer.contains(focusedElement);

    if (isNarrow) {
      isCollapsed = false;
      moveMenuContainer(dialog);
      dialog.classList.remove("is-modal");
      updateControls();

      if (!isOpen) {
        return;
      }

      if (hasOtherOpenDialog()) {
        closeNavigation(false);
        return;
      }

      if (!focusWasInMenu) {
        closeNavigation(false);
        return;
      }

      dialog.classList.add("is-modal");

      try {
        dialog.showModal();
      } catch (error) {
        dialog.classList.remove("is-modal");
        closeNavigation(false);
        throw error;
      }

      if (canPreserveFocus(focusedElement)) {
        focusedElement.focus();
      } else if (!canPreserveFocus(doc.activeElement)) {
        closeButton.focus();
      }

      updateControls();
      return;
    }

    isCollapsed = false;
    const wasDialogOpen = dialog.open;
    if (wasDialogOpen) {
      ignoreNextCloseEvent = true;
      dialog.close();
    }

    dialog.classList.remove("is-modal");
    moveMenuContainer(panel);
    updateControls();

    if (focusWasInMenu) {
      if (isOpen && canPreserveFocus(focusedElement)) {
        focusedElement.focus();
      } else {
        toggle.focus();
      }
    } else if (wasDialogOpen) {
      if (canRestoreExternalFocus(focusedElement)) {
        if (focusedElement !== doc.activeElement) {
          focusedElement.focus();
        }
      } else {
        toggle.focus();
      }
    }
  }

  toggle.addEventListener("click", openNavigation);
  closeButton.addEventListener("click", () => closeNavigation());
  scrim.addEventListener("click", () => closeNavigation());
  collapseButton.addEventListener("click", () => {
    if (!isOpen || isNarrow) {
      return;
    }

    isCollapsed = !isCollapsed;
    updateControls();
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();

    if (isNarrow) {
      closeNavigation();
    }
  });
  panel.addEventListener("keydown", (event) => {
    if (!isNarrow && event.key === "Escape") {
      event.preventDefault();
      closeNavigation();
    }
  });
  dialog.addEventListener("close", () => {
    if (ignoreNextCloseEvent) {
      ignoreNextCloseEvent = false;
      return;
    }

    if (dialog.open || !isOpen) {
      return;
    }

    isOpen = false;
    isCollapsed = false;
    dialog.classList.remove("is-modal");
    updateControls();

    if (!hasOtherOpenDialog()) {
      toggle.focus();
    }
  });
  mediaQuery.addEventListener("change", handleBreakpointChange);

  if (isNarrow) {
    moveMenuContainer(dialog);
  }

  updateControls();
}
