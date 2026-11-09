/**
 * Manage the user list and CRUD dialogs through the relative webapp API.
 *
 * This browser entry point binds the page controls at module load and updates
 * all rendered data with DOM APIs rather than parsing HTML strings.
 */

import {
  clearDialogError,
  focusOpenDialog,
  restoreDialogFocus,
  showDialogError
} from "./dialog-accessibility.mjs";
import { initializeNavigation } from "./navigation.mjs";
import {
  DEFAULT_PAGE_SIZE,
  RESULT_CAP,
  SORTABLE_FIELDS,
  counterText,
  cycleSort,
  filterAndCap,
  findHighlightRanges,
  normalizeText,
  paginate,
  parseSearchTerms,
  sortRows,
  toSearchText
} from "./table-model.mjs";

const API_USERS_URL = "api/users";
const MAX_IMAGE_SIZE = 5 * 1024 * 1024;
const ICON_PATHS = {
  edit: "assets/vendor/fontawesome-5.11.2/solid/pen.svg",
  trash: "assets/vendor/fontawesome-5.11.2/solid/trash-alt.svg"
};

const elements = {
  newUserButton: document.querySelector("#new-user-button"),
  statusRegion: document.querySelector("#status-region"),
  tableBody: document.querySelector("#users-table-body"),
  tableScroll: document.querySelector(".table-scroll"),
  searchToggle: document.querySelector("#users-table-search-toggle"),
  searchField: document.querySelector("#users-table-search-field"),
  searchInput: document.querySelector("#users-table-search-input"),
  searchClose: document.querySelector("#users-table-search-close"),
  searchChips: document.querySelector("#users-table-chips"),
  chipTemplate: document.querySelector("#users-table-chip-template"),
  menuButton: document.querySelector("#users-table-menu-button"),
  menu: document.querySelector("#users-table-menu"),
  menuAdd: document.querySelector("#users-table-menu-add"),
  pageSize: document.querySelector("#users-table-page-size"),
  page: document.querySelector("#users-table-page"),
  pagePrevious: document.querySelector("#users-table-page-prev"),
  pageNext: document.querySelector("#users-table-page-next"),
  counter: document.querySelector("#users-table-counter"),
  capBanner: document.querySelector("#users-table-cap-banner"),
  emptyState: document.querySelector("#users-table-empty"),
  loadingIndicator: document.querySelector(
    "#users-table-loading .table-loading-indicator"
  ),
  loadingText: document.querySelector(
    "#users-table-loading span:not(.table-loading-indicator)"
  ),
  userDialog: document.querySelector("#user-dialog"),
  userForm: document.querySelector("#user-form"),
  userDialogTitle: document.querySelector("#user-dialog-title"),
  userDialogError: document.querySelector("#user-dialog-error"),
  userDialogClose: document.querySelector("#user-dialog-close"),
  userDialogCancel: document.querySelector("#user-dialog-cancel"),
  nameInput: document.querySelector("#user-name"),
  emailInput: document.querySelector("#user-email"),
  locationInput: document.querySelector("#user-location"),
  imageInput: document.querySelector("#user-image"),
  imagePreview: document.querySelector("#image-preview"),
  removeImageOption: document.querySelector("#remove-image-option"),
  removeImageInput: document.querySelector("#remove-image"),
  userSaveButton: document.querySelector("#user-save-button"),
  deleteDialog: document.querySelector("#delete-dialog"),
  deleteDialogContent: document.querySelector("#delete-dialog-content"),
  deleteDialogMessage: document.querySelector("#delete-dialog-message"),
  deleteDialogError: document.querySelector("#delete-dialog-error"),
  deleteDialogCancel: document.querySelector("#delete-dialog-cancel"),
  deleteConfirmButton: document.querySelector("#delete-confirm-button")
};

const state = {
  allUsers: [],
  terms: [],
  sort: { field: null, direction: "asc" },
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
  totalPages: 1,
  openPanel: null,
  currentUser: null,
  userDialogReturnUserId: null,
  deleteUserId: null,
  isBusy: false,
  previewObjectUrl: null
};

/**
 * Represent an unsuccessful HTTP response with its status and API detail.
 */
class ApiError extends Error {
  /**
   * Initialize an API error from the response status and optional detail.
   *
   * @param {number} status - The HTTP status code returned by the API.
   * @param {unknown} detail - The response detail supplied by the API, if any.
   */
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "A solicitação não foi concluída.");
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Send a request to the relative API and reject non-success responses.
 *
 * @param {string} url - An API path relative to the application prefix.
 * @param {RequestInit} options - Fetch options for the request.
 * @returns {Promise<unknown>} The parsed response body, or null for HTTP 204.
 * @throws {ApiError} When the API returns a non-success status.
 * @throws {Error} When a successful response cannot be parsed as JSON.
 */
async function requestApi(url, options = {}) {
  const response = await fetch(url, options);

  if (!response.ok) {
    let payload = null;

    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    throw new ApiError(response.status, payload?.detail ?? null);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

/**
 * Convert an API or network error into a message suitable for the interface.
 *
 * @param {unknown} error - The rejected request error.
 * @returns {string} A Portuguese message safe to display as text.
 */
function formatError(error) {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "Email já cadastrado.";
    }

    if (error.status === 413) {
      return "Imagem maior que 5 MiB.";
    }

    if (error.status === 415) {
      return "Formato de imagem não suportado.";
    }

    if (error.status === 422) {
      if (Array.isArray(error.detail)) {
        const messages = [];

        for (const item of error.detail) {
          if (item && typeof item.msg === "string") {
            messages.push(item.msg);
          }
        }

        if (messages.length > 0) {
          return messages.join("; ");
        }
      }

      if (typeof error.detail === "string") {
        return error.detail;
      }
    }

    if (error.status === 404) {
      return "Usuário não encontrado.";
    }

    if (typeof error.detail === "string" && error.detail.length > 0) {
      return error.detail;
    }

    return "Não foi possível concluir a solicitação.";
  }

  if (error instanceof Error && error.name !== "TypeError") {
    return error.message;
  }

  return "Não foi possível conectar à API. Tente novamente.";
}

/**
 * Show a message in the page status region.
 *
 * @param {string} message - The status text to announce.
 * @param {string} tone - The visual status tone, such as success or error.
 */
function showStatus(message, tone = "neutral") {
  elements.statusRegion.textContent = message;
  elements.statusRegion.className = `status-region status-${tone}`;
}

/**
 * Disable CRUD actions while an API operation is in flight.
 *
 * @param {boolean} isBusy - Whether the page is waiting for an API operation.
 */
function setBusy(isBusy) {
  state.isBusy = isBusy;

  if (isBusy) {
    focusOpenDialog([
      { dialog: elements.userDialog, focusTarget: elements.userForm },
      { dialog: elements.deleteDialog, focusTarget: elements.deleteDialogContent }
    ]);
  }

  const controls = document.querySelectorAll(
    "#new-user-button, #users-table-body button, #user-dialog button, #delete-dialog button, " +
      "#users-table-search-toggle, #users-table-search-input, #users-table-search-close, " +
      "#users-table-chips button, #users-table-menu-button, #users-table-menu button, " +
      ".table-sort-button, #users-table-page-size, #users-table-page, " +
      "#users-table-page-prev, #users-table-page-next"
  );

  for (const control of controls) {
    control.disabled = isBusy;
  }

  updatePaginationControls();
  elements.userSaveButton.textContent = isBusy
    ? "Salvando..."
    : state.currentUser
      ? "Salvar alterações"
      : "Criar usuário";
}

/**
 * Create a decorative local icon for an interface action.
 *
 * @param {"edit"|"trash"} name - The supported icon name.
 * @returns {HTMLImageElement} A decorative icon element.
 */
function createIcon(name) {
  const icon = document.createElement("img");
  icon.className = "button-icon";
  icon.src = ICON_PATHS[name];
  icon.alt = "";
  return icon;
}

/**
 * Create the photo or initials avatar for one user.
 *
 * @param {Object} user - The API user record.
 * @returns {HTMLElement} An avatar element containing an image or initials.
 */
function createAvatar(user) {
  if (user.image_url) {
    const image = document.createElement("img");
    image.className = "avatar avatar-image";
    image.src = user.image_url;
    image.alt = `Foto de ${user.name}`;
    image.loading = "lazy";
    return image;
  }

  const avatar = document.createElement("span");
  const words = user.name.trim().split(/\s+/).filter(Boolean);
  let initials = "?";

  if (words.length > 0) {
    initials = words[0].slice(0, 1);

    if (words.length > 1) {
      initials += words[words.length - 1].slice(0, 1);
    }
  }

  avatar.className = "avatar avatar-placeholder";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = initials.toLocaleUpperCase("pt-BR");
  return avatar;
}

/**
 * Create an action button with visible text and a user-specific accessible name.
 *
 * @param {string} action - The delegated action identifier.
 * @param {string} label - The visible action label.
 * @param {"edit"|"trash"} iconName - The icon name passed to createIcon.
 * @param {number} userId - The user identifier passed to the action handler.
 * @param {string} userName - The user identified in the accessible name.
 * @returns {HTMLButtonElement} The configured action button.
 */
function createActionButton(action, label, iconName, userId, userName) {
  const button = document.createElement("button");
  const text = document.createElement("span");
  const accessibleName = `${label} usuário ${userName}`;

  button.className = "br-button table-action";
  button.type = "button";
  button.disabled = state.isBusy;
  button.dataset.action = action;
  button.dataset.userId = String(userId);
  button.setAttribute("aria-label", accessibleName);
  button.title = accessibleName;
  text.textContent = label;
  button.append(createIcon(iconName), text);
  return button;
}

/**
 * Build a table row that communicates loading, empty, or error state.
 *
 * @param {string} message - The state message to render.
 * @param {boolean} isEmpty - Whether to include the decorative empty-state illustration.
 * @returns {HTMLTableRowElement} A single spanning message row.
 */
function createMessageRow(message, isEmpty = false) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");

  row.setAttribute("role", "row");
  row.className = "table-message-row";
  cell.setAttribute("role", "cell");
  cell.colSpan = 5;

  if (isEmpty) {
    const illustration = document.createElement("img");
    illustration.className = "empty-illustration";
    illustration.src = "assets/govbr/illustrations/empty-space/png/1x/00.png";
    illustration.alt = "";
    cell.append(illustration);
  }

  cell.append(document.createTextNode(message));
  row.append(cell);
  return row;
}

/**
 * Create a card label and its decorative sort indicators.
 *
 * @param {string} label - The visible column label.
 * @param {string} field - The field represented by this card cell.
 * @returns {HTMLSpanElement} A label row with the current sort direction.
 */
function createCardLabelRow(label, field) {
  const row = document.createElement("span");
  const labelText = document.createElement("span");
  const indicator = document.createElement("span");
  const ascending = document.createElement("span");
  const descending = document.createElement("span");

  row.className = "table-card-label-row";
  labelText.textContent = label.split(/\s+/u).join("\u00a0");
  indicator.className = "table-sort-indicator";
  indicator.setAttribute("aria-hidden", "true");
  ascending.className = "table-sort-triangle-up";
  descending.className = "table-sort-triangle-down";
  indicator.append(ascending, descending);

  if (state.sort?.field === field) {
    indicator.classList.add(
      state.sort.direction === "asc" ? "is-ascending" : "is-descending"
    );
  }

  row.append(labelText, indicator);
  return row;
}

/**
 * Append user text as safe nodes and mark matching search ranges.
 *
 * @param {HTMLTableCellElement} cell - The cell receiving the text.
 * @param {unknown} value - The API value to display.
 */
function appendHighlightedText(cell, value) {
  const text = toSearchText(value);
  const ranges = state.terms.length > 0
    ? findHighlightRanges(text, state.terms)
    : [];
  let previousEnd = 0;

  for (const range of ranges) {
    if (range.start > previousEnd) {
      cell.append(document.createTextNode(text.slice(previousEnd, range.start)));
    }

    const mark = document.createElement("mark");
    mark.textContent = text.slice(range.start, range.end);
    cell.append(mark);
    previousEnd = range.end;
  }

  if (previousEnd < text.length || ranges.length === 0) {
    cell.append(document.createTextNode(text.slice(previousEnd)));
  }
}

/**
 * Build one user row using text nodes and DOM elements.
 *
 * @param {Object} user - The API user record to display.
 * @returns {HTMLTableRowElement} The rendered user row.
 */
function createUserRow(user) {
  const row = document.createElement("tr");
  const photoCell = document.createElement("td");
  const nameCell = document.createElement("td");
  const emailCell = document.createElement("td");
  const locationCell = document.createElement("td");
  const actionsCell = document.createElement("td");
  const actions = document.createElement("div");

  row.setAttribute("role", "row");
  photoCell.className = "photo-cell table-card-cell";
  photoCell.setAttribute("role", "cell");
  photoCell.append(createAvatar(user));
  nameCell.className = "name-cell table-card-cell";
  nameCell.dataset.label = "Nome";
  nameCell.setAttribute("role", "cell");
  nameCell.append(createCardLabelRow("Nome", "name"));
  appendHighlightedText(nameCell, user.name);
  emailCell.className = "table-card-cell";
  emailCell.dataset.label = "Email";
  emailCell.setAttribute("role", "cell");
  emailCell.append(createCardLabelRow("Email", "email"));
  appendHighlightedText(emailCell, user.email);
  locationCell.className = "table-card-cell";
  locationCell.dataset.label = "Localização";
  locationCell.setAttribute("role", "cell");
  locationCell.append(createCardLabelRow("Localização", "location"));
  appendHighlightedText(locationCell, user.location ?? "—");
  actionsCell.className = "actions-cell table-card-cell";
  actionsCell.setAttribute("role", "cell");
  actions.setAttribute("role", "group");
  actions.setAttribute("aria-label", `Ações para ${user.name}`);
  actions.className = "row-actions";
  actions.append(
    createActionButton("edit", "Editar", "edit", user.id, user.name),
    createActionButton("delete", "Excluir", "trash", user.id, user.name)
  );
  actionsCell.append(actions);
  row.append(photoCell, nameCell, emailCell, locationCell, actionsCell);
  return row;
}

/**
 * Return the table's sortable header and menu buttons.
 *
 * @returns {HTMLButtonElement[]} Buttons that represent supported fields.
 */
function getSortButtons() {
  return [...document.querySelectorAll("button[data-sort-field]")].filter((button) =>
    SORTABLE_FIELDS.includes(button.dataset.sortField)
  );
}

/**
 * Update header sort semantics and the active menu item.
 */
function renderSortControls() {
  for (const button of getSortButtons()) {
    const field = button.dataset.sortField;
    const isActive = state.sort?.field === field;

    if (button.classList.contains("table-sort-menu-item")) {
      if (isActive) {
        button.classList.add("is-active");
        button.setAttribute("aria-current", "true");
      } else {
        button.classList.remove("is-active");
        button.removeAttribute("aria-current");
      }
      continue;
    }

    const header = button.closest("th");
    header?.setAttribute(
      "aria-sort",
      isActive ? (state.sort.direction === "asc" ? "ascending" : "descending") : "none"
    );
  }
}

/**
 * Render search chips from the static template.
 */
function renderSearchChips() {
  if (!elements.searchChips || !elements.chipTemplate) {
    return;
  }

  elements.searchChips.replaceChildren();
  for (const term of state.terms) {
    const chip = elements.chipTemplate.content.cloneNode(true);
    const removeButton = chip.querySelector(".table-search-chip-remove");
    const text = chip.querySelector(".table-search-chip-text");

    removeButton.setAttribute("aria-label", `Remover ${term}`);
    removeButton.disabled = state.isBusy;
    text.textContent = term;
    removeButton.addEventListener("click", () => {
      void removeSearchTerm(term);
    });
    elements.searchChips.append(chip);
  }
}

/**
 * Toggle the table loading status and its busy region without removing either node.
 *
 * @param {boolean} isLoading - Whether data is being fetched or rendered.
 */
function setTableLoading(isLoading) {
  if (elements.loadingIndicator) {
    elements.loadingIndicator.hidden = !isLoading;
  }
  if (elements.loadingText) {
    elements.loadingText.textContent = isLoading ? "Carregando usuários" : "";
  }
  elements.tableScroll?.setAttribute("aria-busy", String(isLoading));
}

/**
 * Let the browser paint the loading indicator before synchronous rendering.
 */
export function waitForRenderFrame() {
  if (typeof requestAnimationFrame !== "function") {
    return null;
  }

  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

/**
 * Rebuild the page selector for the current result count.
 *
 * @param {number} totalPages - The number of valid pages.
 * @param {number} selectedPage - The page to select.
 */
function updatePageOptions(totalPages, selectedPage) {
  if (!elements.page) {
    return;
  }

  const options = [];
  for (let pageNumber = 1; pageNumber <= totalPages; pageNumber += 1) {
    const option = document.createElement("option");
    option.value = String(pageNumber);
    option.textContent = String(pageNumber);
    options.push(option);
  }
  elements.page.replaceChildren(...options);
  elements.page.value = String(selectedPage);
}

/**
 * Keep pagination arrows disabled at boundaries and during CRUD requests.
 */
function updatePaginationControls() {
  if (elements.pagePrevious) {
    elements.pagePrevious.disabled = state.isBusy || state.page <= 1;
  }
  if (elements.pageNext) {
    elements.pageNext.disabled = state.isBusy || state.page >= state.totalPages;
  }
}

/**
 * Render the filtered and capped users with the current sort and page state.
 */
async function renderUsers() {
  setTableLoading(true);

  try {
    const renderFrame = waitForRenderFrame();
    if (renderFrame) {
      await renderFrame;
    }
    const sortedUsers = sortRows(
      state.allUsers,
      state.sort?.field ?? null,
      state.sort?.direction ?? "asc"
    );
    const result = filterAndCap(
      sortedUsers,
      state.terms,
      SORTABLE_FIELDS,
      RESULT_CAP
    );
    const pageSize = Number(elements.pageSize?.value ?? state.pageSize);
    const requestedPage = Number(elements.page?.value ?? state.page);
    const pageResult = paginate(result.rows, requestedPage, pageSize);

    state.page = pageResult.page;
    state.pageSize = pageSize;
    state.totalPages = pageResult.totalPages;
    elements.tableBody.replaceChildren();

    if (state.allUsers.length === 0) {
      elements.tableBody.append(createMessageRow("Nenhum usuário cadastrado.", true));
    } else {
      for (const user of pageResult.items) {
        elements.tableBody.append(createUserRow(user));
      }
    }

    if (elements.counter) {
      elements.counter.textContent = counterText({
        start: pageResult.start,
        end: pageResult.end,
        total: result.rows.length
      });
    }
    if (elements.capBanner) {
      elements.capBanner.hidden = !result.isCapped;
      elements.capBanner.textContent = result.isCapped
        ? `Exibindo ${RESULT_CAP} de ${result.totalFiltered} usuários encontrados. Refine sua busca aplicando filtros.`
        : "";
    }
    if (elements.emptyState) {
      const hasNoSearchResults =
        state.allUsers.length > 0 &&
        state.terms.length > 0 &&
        result.totalFiltered === 0;
      elements.emptyState.hidden = !hasNoSearchResults;
      elements.emptyState.textContent = hasNoSearchResults
        ? "Nenhum usuário encontrado para a busca informada."
        : "";
    }

    renderSearchChips();
    renderSortControls();
    updatePageOptions(pageResult.totalPages, pageResult.page);
    updatePaginationControls();
  } catch (error) {
    if (elements.counter) {
      elements.counter.textContent = counterText({
        start: 0,
        end: 0,
        total: 0
      });
    }
    throw error;
  } finally {
    setTableLoading(false);
  }
}

/**
 * Fetch the list and update the table after initial load or mutation.
 *
 * @param {boolean} showLoading - Whether to show the loading row first.
 * @returns {Promise<boolean>} Whether the list request succeeded.
 */
async function refreshUsers(showLoading = false) {
  setTableLoading(true);
  if (showLoading) {
    elements.tableBody.replaceChildren(createMessageRow("Carregando usuários..."));
  }

  try {
    const users = await requestApi(API_USERS_URL);

    if (!Array.isArray(users)) {
      throw new Error("A API retornou uma lista de usuários inválida.");
    }

    state.allUsers = users;
    await renderUsers();
    return true;
  } catch (error) {
    elements.tableBody.replaceChildren(
      createMessageRow("Não foi possível carregar os usuários.")
    );
    if (elements.counter) {
      elements.counter.textContent = counterText({
        start: 0,
        end: 0,
        total: 0
      });
    }
    if (elements.emptyState) {
      elements.emptyState.hidden = true;
    }
    if (elements.capBanner) {
      elements.capBanner.hidden = true;
    }
    setTableLoading(false);
    showStatus(formatError(error), "error");
    return false;
  }
}

/**
 * Release a temporary object URL used by the image preview.
 */
function clearPreviewObjectUrl() {
  if (state.previewObjectUrl) {
    URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = null;
  }
}

/**
 * Render the selected file, current image, or preview placeholder.
 */
function updateImagePreview() {
  clearPreviewObjectUrl();
  elements.imagePreview.replaceChildren();

  const selectedFile = elements.imageInput.files[0] ?? null;

  if (selectedFile) {
    state.previewObjectUrl = URL.createObjectURL(selectedFile);
    appendPreviewImage(state.previewObjectUrl, `Prévia de ${selectedFile.name}`);
    return;
  }

  if (elements.removeImageInput.checked) {
    appendPreviewPlaceholder("Foto será removida");
    return;
  }

  if (state.currentUser?.image_url) {
    appendPreviewImage(state.currentUser.image_url, `Foto de ${state.currentUser.name}`);
    return;
  }

  appendPreviewPlaceholder("Prévia da foto");
}

/**
 * Append a safely configured image to the preview container.
 *
 * @param {string} source - An API image URL or temporary object URL.
 * @param {string} alternative - The image alternative text.
 */
function appendPreviewImage(source, alternative) {
  const image = document.createElement("img");
  image.className = "preview-image";
  image.src = source;
  image.alt = alternative;
  elements.imagePreview.append(image);
}

/**
 * Append a text-only placeholder to the preview container.
 *
 * @param {string} message - The placeholder text to display.
 */
function appendPreviewPlaceholder(message) {
  const placeholder = document.createElement("span");
  placeholder.className = "preview-placeholder";
  placeholder.textContent = message;
  elements.imagePreview.append(placeholder);
}

/**
 * Open the user form for a new record or an existing record.
 *
 * @param {Object|null} user - The user to edit, or null to create one.
 */
function openUserDialog(user = null) {
  if (state.isBusy) {
    return;
  }

  state.currentUser = user;
  state.userDialogReturnUserId = user?.id ?? null;
  elements.userForm.reset();
  elements.nameInput.value = user?.name ?? "";
  elements.emailInput.value = user?.email ?? "";
  elements.locationInput.value = user?.location ?? "";
  elements.userDialogTitle.textContent = user ? "Editar usuário" : "Novo usuário";
  elements.removeImageOption.hidden = !user?.image_url;
  clearDialogError(elements.userDialogError);
  updateImagePreview();
  elements.userDialog.showModal();
}

/**
 * Update the editing state after the JSON create or update request succeeds.
 *
 * @param {Object} user - The saved API user record.
 */
function acceptSavedUser(user) {
  state.currentUser = user;
  elements.userDialogTitle.textContent = "Editar usuário";
  elements.removeImageOption.hidden = !user.image_url;
}

/**
 * Close the menu and handle the new-user action.
 */
function onNewUserClick() {
  closeMenu(false);
  openUserDialog();
}

/**
 * Reset the current page before applying a new filter or sort.
 */
function resetTablePage() {
  state.page = 1;
  if (elements.page) {
    elements.page.value = "1";
  }
}

/**
 * Hide the search panel and update its disclosure state.
 */
function hideSearchField() {
  if (elements.searchField) {
    elements.searchField.hidden = true;
  }
  elements.searchToggle?.setAttribute("aria-expanded", "false");
  if (state.openPanel === "search") {
    state.openPanel = null;
  }
}

/**
 * Close search, clear its terms, chips, and input text, and restore the full list.
 *
 * @param {boolean} returnFocus - Whether to focus the search toggle after rendering.
 */
async function closeSearchField(returnFocus = true) {
  hideSearchField();
  state.terms = [];
  if (elements.searchInput) {
    elements.searchInput.value = "";
  }
  resetTablePage();
  renderSearchChips();
  await renderUsers();
  if (returnFocus) {
    elements.searchToggle?.focus();
  }
}

/**
 * Toggle the search panel and keep the menu mutually exclusive.
 */
async function onSearchToggleClick() {
  if (state.isBusy) {
    return;
  }

  if (state.openPanel === "search") {
    await closeSearchField();
    return;
  }

  closeMenu(false);
  state.openPanel = "search";
  if (elements.searchField) {
    elements.searchField.hidden = false;
  }
  elements.searchToggle?.setAttribute("aria-expanded", "true");
  elements.searchInput?.focus();
}

/**
 * Accept parsed search terms when Enter is pressed.
 *
 * @param {KeyboardEvent} event - The search input key event.
 */
async function onSearchInputKeydown(event) {
  if (event.key !== "Enter" || state.isBusy) {
    return;
  }

  event.preventDefault();
  const parsedTerms = parseSearchTerms(elements.searchInput.value);
  const existingTerms = new Set(state.terms.map(normalizeText));
  for (const term of parsedTerms) {
    const normalizedTerm = normalizeText(term);
    if (!existingTerms.has(normalizedTerm)) {
      state.terms.push(term);
      existingTerms.add(normalizedTerm);
    }
  }
  elements.searchInput.value = "";
  resetTablePage();
  await renderUsers();
}

/**
 * Return focus to the search input after chip removal.
 */
function focusSearchInput() {
  elements.searchInput?.focus();
}

/**
 * Remove a search chip, rerender the table, and return focus to the input.
 *
 * @param {string} term - The term represented by the removed chip.
 */
async function removeSearchTerm(term) {
  if (state.isBusy) {
    return;
  }

  const removedIndex = state.terms.findIndex(
    (currentTerm) => normalizeText(currentTerm) === normalizeText(term)
  );
  if (removedIndex === -1) {
    return;
  }

  state.terms.splice(removedIndex, 1);
  resetTablePage();
  await renderUsers();

  focusSearchInput();
}

/**
 * Close the sort menu and optionally return focus to its button.
 *
 * @param {boolean} returnFocus - Whether to focus the menu button.
 */
function closeMenu(returnFocus) {
  if (elements.menu) {
    elements.menu.hidden = true;
  }
  elements.menuButton?.setAttribute("aria-expanded", "false");
  if (state.openPanel === "menu") {
    state.openPanel = null;
  }
  if (returnFocus) {
    elements.menuButton?.focus();
  }
}

/**
 * Toggle the sort menu; opening it while search is open closes search and clears its terms.
 */
async function onMenuButtonClick() {
  if (state.isBusy) {
    return;
  }

  if (state.openPanel === "menu") {
    closeMenu(false);
    return;
  }

  const wasSearchOpen = state.openPanel === "search";
  // Open the menu before the awaited render so it appears without waiting for it.
  state.openPanel = "menu";
  if (elements.menu) {
    elements.menu.hidden = false;
  }
  elements.menuButton?.setAttribute("aria-expanded", "true");

  if (wasSearchOpen) {
    try {
      await closeSearchField(false);
    } catch (error) {
      showStatus(formatError(error), "error");
    }
  }
}

/**
 * Sort by a selected header or menu field.
 *
 * @param {MouseEvent} event - The sortable button click event.
 */
async function onSortFieldClick(event) {
  if (state.isBusy) {
    return;
  }

  const button = event.currentTarget;
  const field = button.dataset.sortField;
  if (!SORTABLE_FIELDS.includes(field)) {
    return;
  }

  const selectedFromMenu = button.classList.contains("table-sort-menu-item");
  state.sort = cycleSort(state.sort, field);
  resetTablePage();
  if (selectedFromMenu) {
    closeMenu(false);
  }
  await renderUsers();
  if (selectedFromMenu) {
    elements.menuButton?.focus();
  }
}

/**
 * Open the existing new-user dialog from the table menu.
 */
function onMenuAddClick() {
  closeMenu(false);
  onNewUserClick();
}

/**
 * Apply a page-size selection and return to the first page.
 *
 * @param {Event} event - The page-size change event.
 */
async function onPageSizeChange(event) {
  if (state.isBusy) {
    return;
  }

  state.pageSize = Number(event.currentTarget.value);
  resetTablePage();
  await renderUsers();
}

/**
 * Apply the selected page number.
 *
 * @param {Event} event - The page selection event.
 */
async function onPageChange(event) {
  if (state.isBusy) {
    return;
  }

  state.page = Number(event.currentTarget.value);
  await renderUsers();
}

/**
 * Move one page backward when a previous page exists.
 */
async function onPreviousPageClick() {
  if (state.isBusy || state.page <= 1) {
    return;
  }

  state.page -= 1;
  if (elements.page) {
    elements.page.value = String(state.page);
  }
  await renderUsers();
}

/**
 * Move one page forward when a next page exists.
 */
async function onNextPageClick() {
  if (state.isBusy || state.page >= state.totalPages) {
    return;
  }

  state.page += 1;
  if (elements.page) {
    elements.page.value = String(state.page);
  }
  await renderUsers();
}

/**
 * Close the sort menu on Escape and restore focus to its button.
 *
 * @param {KeyboardEvent} event - The document key event.
 */
function onDocumentKeydown(event) {
  if (event.key === "Escape" && state.openPanel === "menu") {
    event.preventDefault();
    closeMenu(true);
  }
}

/**
 * Close the sort menu when a click occurs outside its panel and button.
 *
 * @param {MouseEvent} event - The document click event.
 */
function onDocumentClick(event) {
  if (state.openPanel !== "menu" || !(event.target instanceof Element)) {
    return;
  }

  if (
    !elements.menu?.contains(event.target) &&
    !elements.menuButton?.contains(event.target)
  ) {
    closeMenu(true);
  }
}

/**
 * Handle delegated edit and delete actions in the user table.
 *
 * @param {MouseEvent} event - The table body click event.
 */
function onTableClick(event) {
  if (!(event.target instanceof Element) || state.isBusy) {
    return;
  }

  const button = event.target.closest("button[data-action]");

  if (!button || !elements.tableBody.contains(button)) {
    return;
  }

  const userId = Number(button.dataset.userId);
  let user = null;

  for (const item of state.allUsers) {
    if (item.id === userId) {
      user = item;
      break;
    }
  }

  if (!user) {
    return;
  }

  if (button.dataset.action === "edit") {
    openUserDialog(user);
    return;
  }

  if (button.dataset.action === "delete") {
    openDeleteDialog(user);
  }
}

/**
 * Open the native confirmation dialog for deleting a user.
 *
 * @param {Object} user - The user selected for deletion.
 */
function openDeleteDialog(user) {
  state.deleteUserId = user.id;
  elements.deleteDialogMessage.textContent = `Excluir ${user.name}? Esta ação não pode ser desfeita.`;
  clearDialogError(elements.deleteDialogError);
  elements.deleteDialog.showModal();
}

/**
 * Validate and save the user fields, then apply any image operation.
 *
 * @param {SubmitEvent} event - The user form submission event.
 */
async function onUserFormSubmit(event) {
  event.preventDefault();

  if (state.isBusy || !elements.userForm.reportValidity()) {
    return;
  }

  const selectedFile = elements.imageInput.files[0] ?? null;

  if (selectedFile && selectedFile.size > MAX_IMAGE_SIZE) {
    showDialogError(elements.userDialogError, "Imagem maior que 5 MiB.");
    return;
  }

  const location = elements.locationInput.value.trim();
  const userInput = {
    name: elements.nameInput.value.trim(),
    email: elements.emailInput.value.trim(),
    location: location.length > 0 ? location : null
  };
  const existingUser = state.currentUser;
  const userUrl = existingUser
    ? `${API_USERS_URL}/${encodeURIComponent(existingUser.id)}`
    : API_USERS_URL;
  const method = existingUser ? "PUT" : "POST";
  const removeImage = elements.removeImageInput.checked && !selectedFile;

  clearDialogError(elements.userDialogError);
  setBusy(true);

  try {
    const savedUser = await requestApi(userUrl, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(userInput)
    });
    acceptSavedUser(savedUser);
    let refreshed = await refreshUsers();

    if (selectedFile) {
      const imageBody = new FormData();
      imageBody.append("file", selectedFile);
      const imageUrl = `${API_USERS_URL}/${encodeURIComponent(savedUser.id)}/image`;
      const updatedUser = await requestApi(imageUrl, {
        method: "PUT",
        body: imageBody
      });
      acceptSavedUser(updatedUser);
      refreshed = await refreshUsers();
    } else if (removeImage) {
      const imageUrl = `${API_USERS_URL}/${encodeURIComponent(savedUser.id)}/image`;
      const updatedUser = await requestApi(imageUrl, { method: "DELETE" });
      acceptSavedUser(updatedUser);
      refreshed = await refreshUsers();
    }

    elements.userDialog.close();
    // On refresh failure, refreshUsers already shows the error; keep it visible.
    if (refreshed) {
      showStatus("Usuário salvo com sucesso.", "success");
    }
  } catch (error) {
    showDialogError(elements.userDialogError, formatError(error));
  } finally {
    setBusy(false);
  }
}

/**
 * Handle file selection and keep image removal mutually exclusive.
 */
function onImageInputChange() {
  if (elements.imageInput.files.length > 0) {
    elements.removeImageInput.checked = false;
  }

  updateImagePreview();
}

/**
 * Handle the current-image removal checkbox.
 */
function onRemoveImageChange() {
  if (elements.removeImageInput.checked) {
    elements.imageInput.value = "";
  }

  updateImagePreview();
}

/**
 * Reset the user form after its native dialog closes.
 */
function onUserDialogClose() {
  const returnUserId = state.userDialogReturnUserId;
  clearPreviewObjectUrl();
  elements.userForm.reset();
  elements.removeImageOption.hidden = true;
  state.currentUser = null;
  state.userDialogReturnUserId = null;
  clearDialogError(elements.userDialogError);
  updateImagePreview();
  restoreDialogFocus(elements.tableBody, elements.newUserButton, "edit", returnUserId);
}

/**
 * Keep the user dialog open while a request is in flight.
 *
 * @param {Event} event - The native dialog cancel event.
 */
function onUserDialogCancel(event) {
  if (state.isBusy) {
    event.preventDefault();
  }
}

/**
 * Close a CRUD dialog on Escape only when no request is in flight.
 *
 * @param {KeyboardEvent} event - The keyboard event inside the dialog.
 */
function onDialogKeyDown(event) {
  if (event.key !== "Escape") {
    return;
  }

  event.preventDefault();

  if (!state.isBusy && event.currentTarget instanceof HTMLDialogElement) {
    event.currentTarget.close();
  }
}

/**
 * Reset delete state and restore focus after the confirmation dialog closes.
 */
function onDeleteDialogClose() {
  const returnUserId = state.deleteUserId;
  state.deleteUserId = null;
  clearDialogError(elements.deleteDialogError);
  restoreDialogFocus(elements.tableBody, elements.newUserButton, "delete", returnUserId);
}

/**
 * Keep the delete dialog open while its request is in flight.
 *
 * @param {Event} event - The native dialog cancel event.
 */
function onDeleteDialogCancel(event) {
  if (state.isBusy) {
    event.preventDefault();
  }
}

/**
 * Delete the selected user after native dialog confirmation.
 */
async function onDeleteConfirmClick() {
  if (state.isBusy || state.deleteUserId === null) {
    return;
  }

  const userId = state.deleteUserId;
  const userUrl = `${API_USERS_URL}/${encodeURIComponent(userId)}`;
  clearDialogError(elements.deleteDialogError);
  setBusy(true);

  try {
    await requestApi(userUrl, { method: "DELETE" });
    const refreshed = await refreshUsers();
    elements.deleteDialog.close();
    if (refreshed) {
      showStatus("Usuário excluído.", "success");
    }
  } catch (error) {
    showDialogError(elements.deleteDialogError, formatError(error));
  } finally {
    setBusy(false);
  }
}

/**
 * Close the user form when its secondary controls are activated.
 */
function onUserDialogCloseClick() {
  if (!state.isBusy) {
    elements.userDialog.close();
  }
}

/**
 * Close the user form when its cancel control is activated.
 */
function onUserDialogCancelClick() {
  if (!state.isBusy) {
    elements.userDialog.close();
  }
}

/**
 * Close the delete dialog when its cancel control is activated.
 */
function onDeleteDialogCancelClick() {
  if (!state.isBusy) {
    elements.deleteDialog.close();
  }
}

/**
 * Load the user list before enabling page actions.
 */
async function initialize() {
  setBusy(true);
  await refreshUsers(true);
  setBusy(false);
}

elements.newUserButton.addEventListener("click", onNewUserClick);
elements.tableBody.addEventListener("click", onTableClick);
elements.searchToggle?.addEventListener("click", onSearchToggleClick);
elements.searchClose?.addEventListener("click", () => {
  void closeSearchField();
});
elements.searchInput?.addEventListener("keydown", onSearchInputKeydown);
elements.menuButton?.addEventListener("click", onMenuButtonClick);
elements.menuAdd?.addEventListener("click", onMenuAddClick);
for (const button of getSortButtons()) {
  button.addEventListener("click", onSortFieldClick);
}
elements.pageSize?.addEventListener("change", onPageSizeChange);
elements.page?.addEventListener("change", onPageChange);
elements.pagePrevious?.addEventListener("click", onPreviousPageClick);
elements.pageNext?.addEventListener("click", onNextPageClick);
document.addEventListener?.("keydown", onDocumentKeydown);
document.addEventListener?.("click", onDocumentClick);
elements.userForm.addEventListener("submit", onUserFormSubmit);
elements.imageInput.addEventListener("change", onImageInputChange);
elements.removeImageInput.addEventListener("change", onRemoveImageChange);
elements.userDialog.addEventListener("close", onUserDialogClose);
elements.userDialog.addEventListener("cancel", onUserDialogCancel);
elements.userDialog.addEventListener("keydown", onDialogKeyDown);
elements.userDialogClose.addEventListener("click", onUserDialogCloseClick);
elements.userDialogCancel.addEventListener("click", onUserDialogCancelClick);
elements.deleteDialog.addEventListener("close", onDeleteDialogClose);
elements.deleteDialog.addEventListener("cancel", onDeleteDialogCancel);
elements.deleteDialog.addEventListener("keydown", onDialogKeyDown);
elements.deleteDialogCancel.addEventListener("click", onDeleteDialogCancelClick);
elements.deleteConfirmButton.addEventListener("click", onDeleteConfirmClick);

initialize();
initializeNavigation(
  document.querySelector("#navigation-toggle"),
  document.querySelector("#navigation-panel"),
  document.querySelector("#navigation-dialog"),
  window.matchMedia("(max-width: 767.98px)")
);
