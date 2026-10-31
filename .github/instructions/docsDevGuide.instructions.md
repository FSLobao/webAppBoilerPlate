---
name: documentationDevGuide
description: "Use when creating, editing, validating, or reviewing documentation files. Covers language, navigation, reproducible procedures, configuration references, safety, and validation."
applyTo: "**/*.md"
---

# Documentation Development Guide

Follow repository conventions and preserve the owning documentation contract. Make the smallest
change that expresses the approved behavior; do not add compatibility aliases or unrelated fields.

## Audience, Language, and Writing Style

- User directed content should be written clearly and unambiguously, avoiding assumptions about the reader's prior knowledge or context.
- User directed content must be written in Brazilian Portuguese, unless otherwise specified by the documentation contract.
- Agent directed content must be written in English, clear but concise, avoiding unnecessary verbosity while providing sufficient detail for the agent to act correctly.
- Include diagrams using mermaid syntax where appropriate to visually represent complex relationships or workflows.
- Use tables to summarize and organize information clearly, for example, indicating argument names, types, and descriptions.
- Ensure that all references to other documentation sections, figures, or tables are accurate and up-to-date.
- Maintain consistent terminology and style throughout the documentation to avoid confusion and ensure clarity.
- Use proper Markdown syntax for headings, lists, code blocks, and other elements to ensure readability and correct rendering.
- Preserve commands, identifiers, paths, configuration keys, and API names verbatim rather than translating them.
- For Python comments and docstrings, follow sections 3.1 and 3.2 of [the Python development guide](./pythonDevGuide.instructions.md). For JavaScript and TypeScript documentation comments, follow [the JavaScript/TypeScript development guide](./jsTsDevGuide.instructions.md). For other languages, follow the applicable language guide and neighboring code.
- For SQL source comments and persisted table, column, and routine descriptions, follow [the SQL development guide](./sqlDevGuide.instructions.md).

## Page Content and Implementation Status

- State the page's purpose and intended audience. Include prerequisites, ordered steps, examples, expected results, and troubleshooting where relevant; omit sections that do not apply.
- Write affirmatively and objectively, focusing strictly on actions that must or can be performed. Avoid describing, disproving, or extensively discussing extraneous checks, non-applicable tasks, or steps that have no purpose in the intended workflow.
- Keep overview, procedural, and reference content distinct. Link to authoritative details rather than duplicating information that can drift.
- Clearly distinguish implemented, planned, experimental, and unverified behavior. Never present proposed commands as tested; state relevant platform and version limitations.

## Configuration References

- Describe configuration parameters in tables with parameter path, description, type, required/optional status, default, constraints, units, and example. Explicitly indicate when no default or unit applies.
- Link to the authoritative configuration, schema, or implementation. Verify documented defaults and validation rules against that source.
- Provide a minimal valid example when useful. Use safe example values, mark placeholders clearly, and explain relationships or precedence between parameters.

## Reproducible Procedures and Safety

- Specify the operating system, shell, working directory, required permissions, dependencies, and input files before presenting commands.
- Use language-tagged code fences. Clearly identify placeholders and their replacements; keep expected output separate from executable commands.
- Keep code blocks in documentation and recipes concise (single-liners or short 2-3 line commands). Extract multi-step, complex, or loop logic into modular scripts in `deploy/scripts/` or appropriate script directories. Link documentation to the scripts, displaying how to call them, their arguments, prerequisites, and expected outputs.
- Describe the expected outcome and how to verify success. Include actionable troubleshooting for relevant failures.
- Before potentially destructive commands, explain affected data, service interruptions, required backups, and rollback steps. State explicitly when an operation cannot be reversed.
- Keep secrets and private key material out of documentation and examples. Use approved external secret references, and avoid commands that expose secrets in logs or shell history.
- Before documenting a custom script, search repository sources and official tool documentation for capabilities already integrated into the solution. Prefer those capabilities; explain the unmet requirement when a script is necessary.
- Link to official documentation for relevant tool behavior and supported versions. Do not send private repository content or secrets to external search services.

## Page Navigation

- Start each user-facing Markdown documentation page with a collapsible index as its first rendered element, after any YAML frontmatter. Put the explicit `top` anchor on the index so return links lead to the index itself. Include one ordered-list link for every top-level section:

  ```html
  <details id="top">
      <summary>Índice</summary>
      <ol>
          <li><a href="#visão-geral">Visão geral</a></li>
      </ol>
  </details>
  ```

- A top-level section is a peer content section at the page's main section heading level, excluding a standalone page title. For a page with one `#` title and `##` sections, use the `##` sections; for a page whose peer sections use `#`, use those sections. Do not skip heading levels.
- At the end of every top-level section, after all its subsections and before the next peer section or end of file, add this responsive up-arrow hyperlink to `#top`. Adjust image paths relative to the page; do not assume a root README is available:

  ```html
  <div>
    <a href="#top" title="De volta ao topo da página">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="./docs/images/up-arrow_white.svg">
        <img align="right" width="40" height="40" src="./docs/images/up-arrow.svg" title="De volta ao topo da página" alt="De volta ao topo da página">
      </picture>
    </a>
    <br><br>
  </div>
  ```

- Replace the example index entry with the page's actual section titles and rendered anchors. Keep index order synchronized with section order.
- Retain descriptive link titles and image alt text. Translate navigation labels only when the documentation contract specifies a language other than Brazilian Portuguese.

## Validation

- Check Markdown structure, heading hierarchy, fenced code blocks, and table formatting. Avoid duplicate peer headings and explicit anchor IDs; verify that every fragment link resolves to the intended rendered section.
- Validate index entries, return-to-top links, relative documentation links, and both arrow image paths from the page's location.
- Preview changed navigation, HTML, tables, and Mermaid diagrams in the intended renderer. Do not assume that heading punctuation, accents, spaces, or underscores produce a particular anchor.
- Validate configuration examples with existing schema or parsing checks when available. Verify commands safely in the documented environment when feasible; otherwise label them unverified.
- Use existing documentation checks and tooling. Do not introduce scripts or dependencies solely for checks that existing tools or a focused manual review can perform.
