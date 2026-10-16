# Python Development Guidelines for Coding Agents

General engineering conventions for Python code in this repository: styling, typing,
documentation, testing and package management.

**Scope and precedence**

- Project requirements (behavior, architecture, security, API design, deployment) are
  defined in the project contract and the reference documents under `docs/`. Read them
  before implementing. They are not repeated here.
- This file covers only general Python conventions. If a contract or reference document
  conflicts with this file, the contract wins for behavior; this file wins for style
  and tooling.
- Apply these rules to code you write or modify. Do not mass-reformat unrelated code or
  make drive-by refactors.
- If a user request conflicts with a rule here, say so and ask before proceeding.

---

## 1. Package and environment management

- Use **uv** for everything: environments, dependencies, running tools and scripts,
  and installing dependencies in container builds. Do not use `pip`, `pip-tools`,
  Poetry or manual virtualenvs.
- `pyproject.toml` is the single source of project metadata, dependencies and tool
  configuration. Do not add `requirements.txt`, `setup.py`, `setup.cfg`, `tox.ini` or
  `.flake8`.
- Commit `uv.lock`. Never edit it by hand. Regenerate it only through uv commands.
- Add or remove dependencies with `uv add` / `uv remove` (use `--dev` or a dependency
  group for tooling). Do not edit dependency lists by hand and then forget to re-lock.
- Install reproducibly with `uv sync --locked` in CI and container builds.
- Run tools through uv: `uv run pytest`, `uv run ruff check .`.
- The Python version is pinned in `.python-version` and `requires-python`. Use language
  features available in that version and nothing newer.
- In a uv workspace, the root `pyproject.toml` holds shared tool configuration (Ruff,
  pytest defaults). Member packages declare only their own metadata and dependencies.
- Add a dependency only when the standard library or an existing dependency cannot do
  the job reasonably. Prefer well-maintained, widely used packages, and mention new
  dependencies in your summary.

## 2. Code style

Follow PEP 8. **Ruff is the single tool** for linting, import sorting and formatting
(section 5). Do not add Black, isort, flake8, pylint or pydocstyle.

- Naming: `snake_case` for functions, methods and variables; `PascalCase` for classes;
  `UPPER_SNAKE_CASE` for constants; a leading underscore for private members. Names
  should say what a thing is or does; avoid abbreviations that are not obvious.
- Prefer small, single-purpose functions with clear inputs and outputs. Keep entry
  points and framework glue thin, and put logic in plain, testable functions or classes.
- Avoid mutable module-level state. Pass dependencies (configuration, loggers,
  clients) explicitly or through constructors so code stays testable.
- Use `pathlib.Path` for paths, context managers for resources, f-strings for
  formatting (except in logging calls), and `enum`/`dataclass`/typed models over loose
  dicts and magic strings when a structure is stable.
- Handle errors deliberately: catch specific exceptions, never a bare `except:`, and
  avoid `except Exception` unless at a top-level boundary that logs and continues.
  Do not swallow errors silently. Raise specific, meaningful exception types and chain
  with `raise ... from err`.
- Use timezone-aware datetimes (`datetime.now(UTC)`); store and compare in UTC.
- Logging: use the `logging` module (never `print` in library code). Pass values as
  arguments or structured fields, not interpolated into the message. Never log
  secrets, tokens or personal data.
- Do not leave dead code, commented-out code or unused imports.

### 2.1 Type hints

- Annotate every function parameter and return value, and any non-obvious variable.
- Use built-in generics and union syntax: `list[str]`, `dict[str, int]`, `str | None`.
  Do not import `List`, `Dict`, `Optional` or `Union` from `typing`.
- Use `collections.abc` for abstract parameter types (`Iterable`, `Sequence`,
  `Mapping`, `Callable`); return concrete types.
- Use `Final` for constants and `Self`, `Protocol`, `TypedDict` where they fit.
  Keep `Any` rare and narrow.
- Do not silence the type checker with `# type: ignore` without a specific error code
  and a short reason.

## 3. Documentation

### 3.1 Docstrings

Google style, English, triple double quotes. The docstring is the **first statement
inside** the module, class or function, never above it.

- Required on every module, class and public function or method. Private helpers need
  at least a one-line summary.
- First line: one imperative sentence ending with a period ("Load the configuration.",
  not "Loads..."). Extra detail goes after a blank line.
- **Do not repeat types** in the docstring; they live in the signature. Write
  `name: description`.
- Use only the sections that apply, in this order: `Args:`, `Returns:`, `Yields:`,
  `Raises:`.
  - Never write `Args: None`, `Returns: None` or `Raises: None`. Omit the section.
  - `Raises:` lists only exceptions the function deliberately raises, by specific type.
  - For a tuple return, describe each element in order.
- **Module docstring:** purpose, main public API, side effects. No
  `Args`/`Returns`/`Raises`. Never copy one module's docstring into another.
- **Class docstring:** purpose and public attributes. Document constructor arguments
  there, not in `__init__`.
- **Attributes, dataclass fields and module constants:** a one-line string literal
  directly below the assignment.
- Update the docstring in the same edit whenever a signature or behavior changes.
  Never bulk find-and-replace inside docstrings. Re-read them after renaming
  parameters.
- Document the *contract* (units, invariants, side effects, error conditions), not what
  the code obviously does.

```python
def move_to_archive(path: Path, *, overwrite: bool = False) -> Path:
    """Move a file into the archive directory.

    If a file with the same name already exists and ``overwrite`` is False, the
    existing file is renamed with a timestamp before the move.

    Args:
        path: File to move.
        overwrite: Replace an existing archived file with the same name.

    Returns:
        Final location of the archived file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
```

### 3.2 Comments and layout

- Comments explain *why*, not *what*. Use complete sentences: `# ` followed by text,
  and two spaces before an inline `#`.
- **No separator or banner comments** (`# -----`, `# =====`, `# #####`) between
  functions or methods. Use PEP 8 spacing: two blank lines at top level, one inside
  classes.
- To group a long file (over about 300 lines), use `# region <Name>` /
  `# endregion`, one level only, and sparingly. Splitting the module is usually
  better.
- Use `# TODO(name): ...` for pending work, with enough context to act on it.
- In existing files, do not add new separator lines; leave old ones unless asked to
  clean them up.

### 3.3 Project documentation

- Keep the README accurate for setup, run and test instructions when you change them.
- Keep design decisions in `docs/`, not in code comments. When behavior changes,
  update the affected documentation in the same change.
- If the project exposes an HTTP API, keep its generated OpenAPI documentation accurate
  by giving routes and models clear summaries, descriptions and response types rather
  than maintaining separate hand-written API docs.

---

## 4. Testing

- Use **pytest**. Run with `uv run pytest`.
- Layout: unit tests live next to the component they test (a `tests/` folder in that
  package). Cross-component and integration tests live in a top-level `tests/` folder,
  separated from unit tests, and use markers (`@pytest.mark.integration`) so each level
  can be run on its own.
- Test files are named `test_<module>.py`; test functions describe behavior, for
  example `test_rejects_expired_token`, not `test_1`.
- Structure each test as arrange, act, assert. One behavior per test; several
  assertions are fine when they describe the same behavior.
- Use fixtures for setup and teardown, `tmp_path` for files, and
  `pytest.mark.parametrize` for input variations instead of loops inside tests.
- Keep tests deterministic and isolated: no dependence on test order, wall-clock time,
  randomness, network access or shared state. Inject or freeze clocks and seeds.
- **Unit tests** may use fakes or mocks for external systems. **Integration tests**
  exercise real components (real database, real HTTP calls) and should not mock the
  code under test.
- Test error paths and boundaries as well as the happy path: invalid input,
  empty results, permission and authorization failures, and concurrency where relevant.
- Every bug fix comes with a regression test that fails without the fix.
- Prioritize thorough coverage of core logic and security-relevant behavior over
  chasing a coverage percentage on trivial code.
- Do not weaken or delete an existing test to make a change pass. If a test is wrong,
  explain why and fix it deliberately.
- Test code follows the same Ruff rules as production code, apart from the
  per-file ignores in section 5.1.

---

## 5. Ruff

Ruff handles linting, import sorting, docstring checks and formatting.

### 5.1 Configuration

Configuration lives once, in the root `pyproject.toml`. Do not add `[tool.ruff]`
tables to member `pyproject.toml` files. Keep this template and the real config in
sync; change rule selection only through a reviewed edit.

```toml
[dependency-groups]
dev = ["ruff", "pytest"]

[tool.ruff]
target-version = "py312"           # match requires-python
line-length = 88
# extend-exclude = ["<path/to/generated-or-migration-files>"]

[tool.ruff.lint]
select = [
  "E", "W",   # pycodestyle
  "F",        # pyflakes
  "I",        # import sorting
  "D",        # docstrings (Google convention below)
  "UP",       # pyupgrade: modern typing and syntax
  "B",        # bugbear: likely bugs
  "S",        # bandit: security
  "DTZ",      # naive datetime usage
  "ASYNC",    # async pitfalls
  "C4", "SIM", "PT", "RUF",
  "G",        # logging format
  "T20",      # stray print()
  "ERA",      # commented-out code
]
ignore = [
  "D107",     # constructor args are documented in the class docstring
]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.isort]
known-first-party = ["<your_package>"]

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["D", "S101", "S105", "S106"]   # asserts and fake credentials in tests
# "**/scripts/**" = ["T20"]                     # CLI tools may use print()

[tool.ruff.format]
docstring-code-format = true
```

If the project uses FastAPI, also tell bugbear that its dependency markers are
intentional in argument defaults:

```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = [
  "fastapi.Depends", "fastapi.Security", "fastapi.Query",
  "fastapi.Path", "fastapi.Header", "fastapi.Body",
]
```

### 5.2 Commands

```bash
uv run ruff check .            # lint (add --fix for safe autofixes)
uv run ruff format .           # format
uv run ruff format --check .   # CI check, no changes
```

- Run `ruff check --fix` and `ruff format` before finishing any change.
- CI runs `uv sync --locked`, `ruff check .`, `ruff format --check .` and the tests.
  A Ruff failure fails the pull request.

### 5.3 Suppressions

- Fix the code first. Suppress only when a rule is wrong for that specific line.
- Use a targeted, justified inline suppression, for example
  `# noqa: S104 -- must bind all interfaces inside the container`. No bare `# noqa`
  and no file-wide `# ruff: noqa`.
- For structural cases (tests, generated files, CLI scripts), use `per-file-ignores`
  in the root config instead of scattered `noqa` comments.

### 5.4 VS Code

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

---

## 6. Working method

**Before coding**
- Read the relevant contract sections and reference documents, and state which ones
  you are implementing.
- Look at neighboring code and follow established local patterns unless they conflict
  with this file. Do not copy outdated patterns from older code (old typing imports,
  separator comments, stale docstrings).

**Definition of done**
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass.
- [ ] Type hints and docstrings follow sections 2 and 3, and existing docstrings
      affected by the change are updated.
- [ ] Tests added or updated (including error paths, and a regression test for bug
      fixes) and `uv run pytest` passes.
- [ ] Dependencies changed only through uv, with `uv.lock` updated.
- [ ] README and `docs/` updated where behavior, setup or usage changed.
- [ ] No secrets, credentials or personal data in code, logs, tests or documentation.
- [ ] Summary of the change lists new dependencies and any deviations from the
      contract or these guidelines.

## References

- PEP 8, PEP 257, PEP 484, PEP 604
- Ruff: https://docs.astral.sh/ruff/
- uv: https://docs.astral.sh/uv/
- pytest: https://docs.pytest.org/
- Google Python Style Guide, docstring section
