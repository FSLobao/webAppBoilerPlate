---
name: sqlDevGuide
description: "Use when creating, editing, testing, or reviewing SQL, PostgreSQL schemas, migrations, queries, views, or stored routines. Covers naming, table and column descriptions, script structure, data integrity, permissions, and validation."
applyTo: "**/*.sql"
---

# SQL and PostgreSQL Development Guide

## Scope and Precedence

- Read the relevant project contract, owning schema, migrations, and application queries before editing. Contracts govern behavior; this guide governs SQL conventions.
- Use PostgreSQL as the reference database. The architecture contract selects PostgreSQL 18 by default, with the version configurable per instance. Verify the actual target version, extensions, and migration runner before choosing syntax.
- Preserve existing object names, identifier language, schema ownership, and public interfaces. Do not rename unrelated objects or introduce a naming migration solely to satisfy this guide.
- Follow an explicitly adopted organizational data standard when available and compatible with the owning contract. Do not invent rules or attribute local preferences to an unreadable or unavailable reference.
- Apply the organizational rules summarized below from "Padrão de estruturas de dados da Anatel", adapted by the project owner's decisions: PostgreSQL replaces SQL Server; identifiers use uppercase.
- Apply this guide to SQL embedded in application code and migration frameworks when relevant, even when the file extension does not match automatic attachment.
- Follow [the documentation guide](./docsDevGuide.instructions.md) for Markdown and [modular-script-development](../skills/modular-script-development/SKILL.md) when writing script helpers. Do not add a wrapper when the migration runner, PostgreSQL, or existing tools already provide the capability.

## Naming and Identifiers

- Use descriptive, unquoted, uppercase `SCREAMING_SNAKE_CASE` identifiers for new schemas, tables, columns, views, routines, constraints, and indexes. Avoid spaces, accents, reserved words, quoted mixed case, and unexplained abbreviations.
- Write SQL keywords in uppercase. PostgreSQL folds unquoted identifiers to lowercase; quoted identifiers are case-sensitive.
- Keep identifiers within PostgreSQL's default 63-byte limit, including generated constraint and index names. Do not rely on silent truncation; avoid collisions after shortening.
- For new objects, use singular Portuguese business terms without accents. Avoid foreign terms when a Portuguese equivalent exists, irrelevant articles/prepositions, organizational-unit names, and inconsistent synonyms. Use Arabic digits for numerals. Preserve legacy interfaces rather than silently renaming them.
- Limit new table, column, and view names to 32 characters. Abbreviate related names consistently without losing business meaning. This organizational limit is stricter than PostgreSQL's identifier ceiling.
- Prefix tables by their organizational class: `TB_` for ordinary tables, `TH_` for history, `TL_` for operation logs, `TT_` for temporary processing, `DIM_` for dimensions, `FATO_` for facts, and `STG_` for raw staging.
- A prefix does not implement database behavior: a `TT_` name is not a substitute for `CREATE TEMP TABLE`, nor does `TH_` automatically retain history.
- Prefix columns by semantic class, not merely SQL type, using the mapping below. Follow the prefix with the specific business concept; avoid tautologies such as `NO_NOME` or `ID_IDENTIFICADOR`.
- Name surrogate keys for their entity, such as `id_dispositivo`, rather than bare `id`. Reuse the referenced key name in child tables; add a business-role suffix when multiple relationships target the same entity.
- For external references, include the source-system qualifier and document database, schema, table, and column provenance. Do not pretend a cross-database logical reference is an enforced PostgreSQL foreign key.
- Name binary indicators with `IC_`, dates with `DT_`, and instants with `DH_`. Use PostgreSQL `boolean` for yes/no values, not an arbitrary integer encoding.
- Use `PK_<table>` for primary keys, `FK_<child>_<parent>[_<role>]` for foreign keys, `IX_<table>_<nn>` for indexes, and `CC_<table>[_<column>]_<nn>` for checks. Start sequences at `01`; maintain stable, collision-free names within PostgreSQL's 63-byte ceiling.
- Implement alternate keys using unique indexes or unique constraints as required by the relationship model. Name standalone unique indexes with the `IX_` convention; keep unique-constraint naming consistent with the owning migration tool.
- Prefix views with `VW_`, procedures with `SP_`, functions with `FN_`, and triggers with `TRG_<table>_<purpose>_<nn>`. Do not introduce a routine merely to satisfy a naming pattern.
- For new database provisioning, use `db_<system>` where deployment contracts permit it. Do not rename an existing configured database to introduce the prefix.
- Schema-qualify persistent objects in migrations, administrative scripts, and stored routine references. Do not rely on an implicit or user-writable `search_path`.

### Column Semantic Classes

| Prefix | Meaning | PostgreSQL guidance |
| --- | --- | --- |
| `AA_`, `DD_`, `MI_`, `MM_` | Year, day, minute, month | Use appropriate integer ranges; prefer a complete date/time when separate components are unnecessary. |
| `DT_` | Calendar date | Use `date`. |
| `DH_` | Date and time | Use `timestamp with time zone` for instants; document any justified local-time representation. |
| `HH_` | Time or hour value | Choose `time`, an integer, or a numeric representation according to meaning; document units and granularity. |
| `CO_` | Business code | Use text when leading zeros or letters matter; do not assume a numeric representation. |
| `IC_` | Binary indicator | Use `boolean`; prefer `NOT NULL` when an unknown state is invalid. |
| `ID_` | Record identifier | Use the approved key type; prefer integer identity for new generated numeric keys. |
| `SG_` | Abbreviation | Use text with domain-appropriate validation. |
| `DE_` | Short description | Limit to 1,000 characters when this organizational class is used. |
| `ED_` | Address | Document whether physical, email, web, or another address. |
| `NO_` | Name | Use text with justified business limits. |
| `TX_` | Free-form long text | Use `text` or a justified length limit. |
| `NU_` | Number not covered by another class | Choose the required numeric range and precision. |
| `PC_` | Percentage | Use exact numeric representation; document scale and allowed range. |
| `QT_` | Count or quantity | Choose the domain-appropriate representation and state units. |
| `VR_` | Monetary or decimal measure | Use suitable numeric precision/scale; state currency or measurement units. |
| `BI_` | Binary content | Use `bytea` only when database storage is justified. |
| `GE_`, `GF_` | Geometry, geography | Use an approved spatial implementation such as PostGIS; do not assume the extension exists. |
| `XL_` | XML | Use PostgreSQL `xml` when XML semantics are required. |

Do not force new domains such as UUID or JSON into an inaccurate semantic class. Ask when the approved classification does not cover a required concept.

## Tables, Fields, and Data Integrity

- Define each table's entity or event, row granularity, ownership, primary key, and relationships before adding fields. Prefer normalized structures; justify denormalization with a concrete requirement.
- Target at least third normal form for transactional models. For dimensional models, use a star schema rather than snowflake; distinguish raw collection staging from transformed warehouse staging.
- Preserve raw source content in collection staging; perform business transformations in a separate processing layer. Document lineage and avoid modifying replicated data outside its authoritative source.
- Declare an explicit owning role and a primary key for every application table. Prefer a single generated key; use stable explicit keys for lookup tables with fewer than 30 rows. Explain justified composite keys.
- Declare relationships explicitly. Review circular dependencies, mandatory relationships in both directions, and one-to-one relationships before introducing them.
- Order columns in new tables as primary key, foreign keys, business fields, then lifecycle/audit fields. Append columns to existing tables rather than rebuilding them solely for physical ordering.
- Include a creation timestamp in transactional tables where applicable, and a load timestamp in fact and dimension tables. Document timestamp defaults and their PostgreSQL transaction-time semantics.
- Distinguish history from operation logs. Prefer application-owned recording where suitable; justify database triggers or routines when needed. Assess data sensitivity and document classification without storing personal examples.
- Avoid multivalued fields that obscure individual business values and binary payload storage without justification.
- Choose types for domain meaning, range, precision, and supported operations. Do not default every identifier to text or every structured value to `jsonb`.
- Use `jsonb` for structured data when justified as with unclear structure, relationships or variable content in runtime.
- Use geographic types only when justified by the domain, such as latitude/longitude coordinates. Document the coordinate reference system and ensure appropriate spatial indexing.
- Prefer identity columns over new `serial` declarations when a generated integer key is required. Choose `GENERATED ALWAYS` or `BY DEFAULT` deliberately and still declare the key's uniqueness constraint; identity alone does not guarantee uniqueness.
- Use `numeric` with appropriate precision and scale for exact decimal values. Use floating-point types only when approximation is acceptable. Preserve identifiers with leading zeros as text.
- Use `date` for calendar dates and `timestamp with time zone` for instants. Document timezone interpretation; PostgreSQL does not retain an instant's original named timezone.
- Use `NOT NULL`, `UNIQUE`, `CHECK`, and foreign keys to enforce invariants at the database boundary. A `CHECK` alone does not reject null values; add `NOT NULL` when absence is invalid.
- Represent business categories through lookup tables and foreign keys rather than enum types or enumerated `CHECK` lists. Use `CHECK` for numeric ranges, formats, and cross-column invariants; binary yes/no values use native `boolean`.
- Define defaults only when they represent valid domain behavior. Distinguish absent, unknown, empty, and zero values rather than replacing them with arbitrary sentinels.
- Express defaults using native PostgreSQL column defaults. Do not invent separately named `df_` default constraints: SQL Server's default-constraint objects have no direct PostgreSQL equivalent.
- Specify foreign-key deletion/update behavior deliberately. Do not introduce cascading deletion without an approved ownership and data-retention requirement.
- Do not add an index merely because a column exists. Primary-key and unique constraints create supporting indexes; referencing foreign-key columns do not automatically receive indexes.
- Ensure every foreign key has suitable index coverage on the referencing columns, reusing an existing index with appropriate leading keys where possible. Do not create a duplicate index when a primary-key, unique, or other suitable index already covers it.
- Ensure every spatial field has a suitable spatial index. Document coordinate reference system, geometry shape, and meaning; distinguish point, line, and polygon names. For latitude/longitude pairs, provide the corresponding spatial representation; WKT alone does not replace it.
- Use query patterns and measured plans to justify additional indexes. Consider write cost, storage, selectivity, and existing indexes.

## Textual Descriptions and In-Code Documentation

- Every new application table and every new column must have a meaningful persisted description using `COMMENT ON TABLE` and `COMMENT ON COLUMN`. Source comments alone are not a substitute for catalog descriptions.
- When modifying a table or column's meaning, update its description in the same migration. For legacy objects, document affected objects without expanding into an unrelated catalog cleanup.
- Table descriptions must identify the business purpose, what one row represents, key relationships, and relevant lifecycle or retention rules.
- Column descriptions must explain business meaning and relevant units, allowed values, null semantics, defaults, derivation, sensitivity classification, and relationship role. Include only applicable details; do not merely repeat the column name or SQL type.
- Keep business descriptions concise, understandable to nonspecialists, and free of tautologies. Explain acronyms and translate necessary foreign terminology.
- List discrete values as `Valor - Descrição`, separated by semicolons, using the actual PostgreSQL representation. Do not copy inconsistent legacy indicator examples into Boolean definitions.
- Begin primary-key descriptions with `Chave primária - <table>` and foreign-key descriptions with `Chave estrangeira - <table>.<column>`, then explain the business relationship where useful.
- Describe logical reference fields exposed by views and materialized views through `COMMENT ON VIEW`, `COMMENT ON MATERIALIZED VIEW`, and `COMMENT ON COLUMN` when adding those interfaces.
- Document public functions and procedures with `COMMENT ON FUNCTION` or `COMMENT ON PROCEDURE`, including the input argument types needed to identify overloaded routines. Explain inputs, outputs, errors, side effects, execution privileges, and transaction expectations.
- Add catalog comments for non-obvious constraints, indexes, and triggers when their rationale is not clear from the definition. Keep descriptions synchronized when definitions change.
- Write human-facing catalog descriptions in Brazilian Portuguese unless the owning contract specifies otherwise. Write developer-oriented script and implementation comments in English.
- Comments are not private storage: PostgreSQL catalog comments can be read by connected users. Never include credentials, personal records, or other sensitive values in them.
- Each authored SQL script needs a short opening `--` comment block describing purpose, target database/version, prerequisites, execution tool, required role, parameters, transaction behavior, side effects, and rollback or recovery when relevant.
- Put routine implementation documentation immediately before its definition. Give private routine helpers at least a one-line summary; document non-obvious local variables only when needed.
- Use `-- ` comments to explain intent and tradeoffs. Do not introduce decorative separators such as `-- -----` or banner blocks. Prefer cohesive files and blank lines; preserve existing separators unless cleanup is requested.
- Do not copy Python docstrings or JavaScript documentation tags into SQL. Use source comments for implementation context and `COMMENT ON` for durable database-object contracts.

Example of persisted descriptions; assume the `app` schema already exists:

```sql
CREATE TABLE app.TB_DISPOSITIVO (
    ID_DISPOSITIVO bigint GENERATED ALWAYS AS IDENTITY,
    NO_DISPOSITIVO text NOT NULL,
    CONSTRAINT pk_tb_dispositivo PRIMARY KEY (ID_DISPOSITIVO)
);

COMMENT ON TABLE app.TB_DISPOSITIVO IS
    'Cadastro de dispositivos; cada linha representa um dispositivo identificado pela chave interna.';
COMMENT ON COLUMN app.TB_DISPOSITIVO.ID_DISPOSITIVO IS
    'Chave primária - tb_dispositivo. Identificador interno gerado pelo banco, sem significado de negócio.';
COMMENT ON COLUMN app.TB_DISPOSITIVO.NO_DISPOSITIVO IS
    'Nome de exibição do dispositivo; obrigatório e sem garantia de unicidade.';
```

The example illustrates syntax and documentation, not an approved application schema.

## SQL Script Definitions and Formatting

- Keep each migration or operational script focused on one cohesive change. Follow existing file locations, ordering, migration identifiers, and rollback conventions.
- Use the existing formatter and linter. Without a configured formatter, use four-space indentation, one statement per logical block, one column or constraint per line in table definitions, and semicolon-terminated statements.
- List target columns explicitly in `INSERT` statements. Avoid `SELECT *` in persistent interfaces and application queries; use clear aliases for joins and calculated expressions.
- Separate SQL from `psql` meta-commands. A file containing commands such as `\set` or `\connect` requires `psql` and cannot be passed unchanged to a generic database driver.
- Document parameters individually, including type, required/default status, accepted values, and effect. Do not embed environment-specific database names, credentials, or filesystem paths without a declared deployment contract.
- Use driver bind parameters for values. For dynamic identifiers, use the driver's identifier-composition API or PostgreSQL `format('%I', ...)`; never concatenate untrusted SQL.
- In PL/pgSQL, prefer `EXECUTE ... USING` for dynamic statement values. In `psql`, distinguish quoted values (`:'name'`) from quoted identifiers (`:"name"`); do not use raw substitution for untrusted input.
- Prefer declarative SQL and set-based operations over procedural loops. Use PL/pgSQL only when required; keep routines cohesive and use tagged dollar quoting for their bodies.
- Declare routine language and behavior deliberately. Set volatility, null-input behavior, and parallel-safety attributes only when justified; never claim `IMMUTABLE` for functions that depend on changing data or time.
- Never suppress unexpected failures with a broad exception handler or a success-shaped return. Propagate errors or handle a specific, documented condition.

## Execution, Migrations, and Permissions

- Use the existing migration runner when available. Applied versioned migrations are immutable unless the project's migration contract explicitly permits otherwise; add a new migration rather than editing history.
- Verify the target database, role, and schema before changing data. Use least-privilege roles; application runtime roles should not receive schema-owner or superuser privileges merely to simplify deployment.
- For standalone `psql` scripts, use `-X` to ignore startup customizations and `-v ON_ERROR_STOP=1` to stop on SQL errors. Require the caller to check the exit status. Never put passwords in command-line arguments or committed files.
- Define one owner for transaction boundaries: the runner or the script. Use transactions for compatible cohesive changes, but do not blindly wrap every script in `BEGIN`/`COMMIT` or `--single-transaction`.
- Identify statements that cannot run inside a transaction block, including `CREATE INDEX CONCURRENTLY` and `CREATE DATABASE`. Run them through the runner's supported nontransactional path and document partial-failure cleanup.
- Assess lock levels, table rewrites, validation scans, and data volume before DDL or bulk DML. Use scoped lock/statement timeouts where appropriate; fail explicitly rather than waiting indefinitely.
- Plan backward-compatible deployment order, backfill strategy, constraints, and application cutover. For irreversible changes, require approval and a tested recovery path; do not invent a lossless rollback.
- Do not use `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, or broad exception handling to conceal schema drift or unexpected data. Idempotent setup must verify that existing objects match the required definition.
- Require an explicit scope and reviewed predicate for destructive DML. Document intended full-table operations, `TRUNCATE`, `DROP`, and `CASCADE` before execution; do not run them against live data without authorization.
- Prefer `SECURITY INVOKER`. If `SECURITY DEFINER` is necessary, restrict ownership and execution grants, set a safe `search_path` with trusted schemas and `pg_temp` last, and review default `PUBLIC` execution privileges.

## Validation and Completion

- Use existing migration checks, SQL linting, and database tests. Do not install a new database or validation dependency solely to edit instructions.
- Validate actual SQL changes against a disposable PostgreSQL instance matching the target major version and extensions. Do not claim that text parsing proves database behavior.
- Test the affected schema or migration path, including supported upgrade and recovery paths, defaults, null handling, constraint violations, and permissions.
- Verify that every new table and column has a nonempty meaningful catalog description. Inspect with `psql`'s `\d+`, `obj_description`, or `col_description`; include relevant assertions in existing schema tests.
- Check organizational prefixes, 32-character table/column/view limits, primary-key presence, and foreign-key/spatial index coverage. Verify catalog descriptions against business meaning, not just their presence.
- Verify application queries and generated models still agree with changed types, names, and defaults. Do not weaken constraints or tests to make a migration pass.
- Use `EXPLAIN` for plan inspection when appropriate. `EXPLAIN ANALYZE` executes the statement; run it only in a safe environment with controlled data and side effects.
- Report exact validation commands, results, and checks not run. Update directly affected documentation in the same change.

## References

PostgreSQL defines identifier behavior and SQL semantics, not a mandatory business naming style. Naming preferences and documentation scope above are repository conventions. Consult version-specific documentation for the deployed major version.

- Organizational source: "Padrão de estruturas de dados da Anatel", supplied by the project owner. Applicable rules and approved PostgreSQL adaptations are recorded in this guide so execution does not depend on the attachment or corporate modeling tools.
- [Repository architecture contract](../../docs/contracts/ARCHITECTURE.md)
- [PostgreSQL lexical structure and identifiers](https://www.postgresql.org/docs/18/sql-syntax-lexical.html)
- [Object descriptions with COMMENT](https://www.postgresql.org/docs/18/sql-comment.html)
- [Constraints](https://www.postgresql.org/docs/18/ddl-constraints.html)
- [Identity columns](https://www.postgresql.org/docs/18/ddl-identity-columns.html)
- [Function definitions and security](https://www.postgresql.org/docs/18/sql-createfunction.html)
- [Index creation and concurrent builds](https://www.postgresql.org/docs/18/sql-createindex.html)
- [psql scripting, interpolation, and error handling](https://www.postgresql.org/docs/18/app-psql.html)
