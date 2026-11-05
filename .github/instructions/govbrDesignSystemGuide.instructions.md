---
name: govbrDesignSystemGuide
description: "Use when creating or changing webapp interfaces, GOV.BR Design System components, CSS, responsive layouts, typography, icons, images, or accessibility. Covers official-source reuse and verification."
applyTo: "**/*.{html,css,scss,sass,jsx,tsx,vue,svelte},webapp/frontend/**/*.{js,mjs}"
---

# GOV.BR Design System Webapp Guide

Use the [official GOV.BR Design System](https://www.gov.br/ds/home) as the
interface reference for webapps in this repository. These instructions define
the repository workflow; they do not certify government approval or compliance.
Keep existing application behavior intact when changing presentation.

## Read Before Implementing

1. Read the relevant project contract, this guide, and the
   [source-backed reuse guide](../../docs/recipes/govbr-design-system.md).
2. Follow the official page for each component or foundation being changed.
   Check its anatomy, states, responsive behavior, accessibility, and examples.
3. Inspect existing frontend dependencies, assets, and integration patterns.
   Choose one compatible integration and record its release, official sources,
   dependencies, and licenses.
4. Define the affected screens and acceptance checks before editing.
   Preserve existing behavior. A documentation request alone does not authorize
   a frontend migration.
5. Include only resources required for the implementation. For the current static
   frontend, assess local assets, relative paths, and preserved license notices.
6. Initialize components for the selected release. Verify user flows and update
   affected documentation.
7. Report evidence, deviations, limitations, and update or rollback procedures.

Follow the official [integration workflow](https://docs-ds.estaleiro.serpro.gov.br/govbr-ds-site-content/como-comecar/fluxo-dev/fluxo-dev.md)
for the selected release's required dependencies and load order. Do not assume Design System
assets are standalone.
The [Core 3.7.0 package metadata](https://registry.npmjs.org/@govbr-ds%2fcore/3.7.0) lists
`flatpickr: ^4.6.9` and `@popperjs/core: ^2.9.2` as dependencies. Check which dependencies the
selected components require; [LICENSES.md](../../LICENSES.md) records Flatpickr's project license.
The visual Sign-in component does not implement GOV.BR authentication or replace backend security.

## Reuse and Delivery

- Prefer maintained official components and styles over locally reconstructed
  look-alikes. Preserve their documented markup, classes, tokens, and states.
- Select one compatible integration: Core for HTML/CSS/JavaScript, or the
  appropriate official component integration for an existing framework.
  Check the release documentation before combining packages or major versions.
- Reuse an installed package or vetted local assets first. Adding a package,
  build stage, external CDN, or remote font requires a justified dependency and
  deployment change, not an incidental styling edit.
- The current `webapp/frontend/` is a static, no-build frontend served under
  `/webapp/`. Preserve this delivery model unless the task explicitly changes it.
  Use relative asset paths that remain valid under that URL prefix.
- When local distribution is needed, obtain files from the official release.
  Pin the version, retain applicable license notices, and record source URLs
  and the update procedure. Never hand-edit distributed vendor files.
- Load documented dependencies in their required order. Keep application
  overrides separate from vendor CSS, and scope overrides to application needs.
- Initialize only the documented interactive components in use. Preserve
  existing listeners and avoid duplicate initialization after rerenders.
- Use official resource links when redistribution rights are unclear.
  A software license does not automatically authorize logos or photographs.

## Layout and Visual Foundations

- Use the official grid, containers, breakpoints, gutters, spacing, typography,
  and color tokens for the selected release. Consult the reuse guide for sources;
  do not invent pixel values or copy values from unrelated portal pages.
- Start from the documented page templates and component composition.
  Use header, navigation, breadcrumb, content, and footer when appropriate
  to the application's information architecture.
- Preserve responsive behavior, readable content width, and consistent alignment.
  Verify dense tables and long text at narrow widths without losing controls.
- Use documented typography and icon resources. Provide readable fallbacks
  when fonts or icons fail, and avoid icon-only actions without accessible names.
- Obtain brand assets from official identity resources. Preserve proportions,
  safe areas, contrast, and any stated usage restrictions.
- Give informative images meaningful alternative text. Mark decorative images
  with empty alternative text; keep essential instructions in real text.

## Multi-Page Navigation and Menus

- Treat multi-page sites as a first-class layout. Keep shared headers, navigation,
  breadcrumbs, and footers consistent while making the current page clear.
- Use links for navigation and buttons for actions. Preserve stable, shareable URLs,
  direct page loads, refresh, browser back/forward, and meaningful page titles.
- Mark the current destination with `aria-current="page"`. Keep breadcrumbs aligned
  with the real information hierarchy and link each available parent destination.
- Build site navigation with semantic `<nav>`, lists, links, and disclosure buttons.
  Give each navigation landmark a distinct accessible name when a page has several.
- For expandable menus, expose state with `aria-expanded` and `aria-controls`.
  Support keyboard activation, predictable tab order, Escape to close, and focus
  return to the trigger when a menu or dialog closes.
- Make menus usable on touch and narrow viewports. Keep essential destinations
  available without hover, and show active and expanded states beyond color alone.
- Add a visible-on-focus skip link to the main content on pages with repeated
  navigation. Give its target a stable ID; ensure focus reaches the new content.
- For client-side route changes, update `document.title`, preserve browser history,
  and move focus to the new page heading or main region after rendering. Keep ordinary
  anchor navigation for full-page routes.
- Treat site navigation as navigation, not an ARIA `menu` widget. Use menu roles and
  arrow-key behavior only when implementing the corresponding application menu pattern.
- Avoid global keyboard shortcuts by default. When a requirement needs shortcuts,
  document them visibly, check conflicts with browser, operating-system, and assistive
  technology commands, and follow the applicable WCAG rules for character shortcuts.
- Follow the official [WAI-ARIA guide](https://www.gov.br/ds/guias/wai-aria) and the
  relevant component guidance in the source-backed reuse guide.

## Behavior and Accessibility

- Preserve the API contract, authorization, validation, and business rules.
  Presentation changes must not replace backend security checks.
- Implement semantic landmarks, heading hierarchy, labels, error associations,
  accessible names, and visible keyboard focus.
- Verify keyboard operation and focus management for menus, dialogs, tabs,
  and other interactive components. Check the component's documented behavior.
- Make loading, empty, success, validation, and failure states explicit.
  Use more than color alone to communicate meaning.
- Check contrast and accessibility against the official references linked in the
  reuse guide. Component reuse alone is not proof of application accessibility.

## Completion Evidence

- Account for every changed screen and component with its official source.
- Record reused asset origins, versions, licenses, and any justified deviations.
- Run the existing focused checks appropriate to the modified files.
- Verify the actual application in the browser at the documented responsive
  boundaries, including a narrow viewport, keyboard navigation, and error states.
- For multi-page work, open every changed route directly and test refresh, back/forward,
  active navigation, breadcrumbs, skip links, menu states, and any documented shortcuts.
- Confirm that assets resolve under `/webapp/`, with no new console errors,
  broken requests, or unintended external runtime dependencies.
- Update directly affected documentation. Report checks performed and remaining
  limitations separately; claim compliance only to the extent actually verified.
