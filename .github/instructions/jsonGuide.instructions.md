---
name: jsonGuide
description: "Use when creating, editing, validating, or reviewing JSON configuration, manifests, fixtures, schemas, or JSON-consuming code. Covers duplicate-key safety, repository naming, coherent structures, references, validation, secrets, atomic edits, tests, and formatting."
applyTo: "**/*.json"
---

# JSON Development Guide

Follow repository conventions and preserve the owning configuration contract. Make the smallest
change that expresses the approved behavior; do not add compatibility aliases or unrelated fields.

## Object Keys and Property Names

- Duplicate object keys are forbidden at every nesting level. A JSON consumer must detect duplicate
  keys before any ordinary/lossy parse can discard an earlier value. Use a strict duplicate-aware
  parser or validation step before constructing normal objects; do not treat the surviving value
  from a lossy parse as valid input.
- Use `snake_case` for repository-owned configuration property names. Preserve mandated naming for
  standard formats, external specifications, and tool/vendor-owned properties when those
  conventions require another form.
- Keep resource identity strings (such as network, container, service, or application names) as
  values, not object keys, unless the format or an established repository contract specifically
  requires a keyed map.

## Structure and References

- Keep related settings in coherent objects that express one ownership or lifecycle boundary. Avoid
  needless fragmentation, duplicated inventories, and multiple conflicting sources of truth.
- Keep references explicit. A reference should identify its target unambiguously and be validated
  against the declared resources; do not rely on implicit ordering or a display label as identity.
- Preserve the established JSON formatting convention in the file being edited. Avoid
  reformatting unrelated objects or changing indentation solely for preference.

## Validation and Safety

- Validate syntax, schema/shape, value constraints, and cross-references. Include duplicate-aware
  parsing before a parser that would otherwise collapse repeated keys.
- Keep secrets and private key material out of JSON committed to the repository. Use approved
  external secret references or protected host-side inputs; never replace a secret with a literal
  value in an example.
- Make file updates atomically where the owning workflow can do so, especially for live
  configuration. Validate staged content before replacing the prior file and preserve the prior
  valid state on failure.
- Add focused regression tests for changed parsing, schema, or reference behavior, including
  invalid input paths such as duplicate keys when relevant. Run the cheapest relevant validation
  first, then the owning component's required checks.
