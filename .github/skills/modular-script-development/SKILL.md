---
name: modular-script-development
description: 'Use when planning, creating, modifying, debugging, testing, or reviewing any project script in Bash, Python, JavaScript, TypeScript, or another language, including CLI tools, build tasks, CI automation, deployment, bootstrap, maintenance, and script helpers. Keep responsibilities cohesive, entry points thin, interfaces explicit, and side effects testable.'
argument-hint: 'Describe the project script, language, workflow, or change to plan, implement, or review.'
---

# Modular Script Development

Create cohesive, testable scripts with explicit responsibilities and stable interfaces in any language. Separate orchestration from reusable operations without forcing small scripts into multi-file frameworks.

## When to Use

- Plan, create, modify, debug, test, or review any script used by this project.
- Include Bash, Python, JavaScript, TypeScript, other languages, extensionless executables, and commands embedded in package tasks, CI, or container configuration.
- Apply the same contracts to script helpers and shared libraries. Extract embedded programs when they need independent testing or own substantial logic.
- Scale the workflow to the change. A short, cohesive script may remain one file; loading this skill does not require a refactor.

## Scope and Precedence

- Read the applicable architecture contract and language/file instructions first. They govern behavior, style, runtime versions, package management, and required checks.
- This skill defines a cross-language workflow, not a replacement for language-specific instructions. Do not introduce a runtime, dependency, test runner, or directory structure merely to follow an example.
- Apply the skill within the agent's role. Planners specify boundaries and checks; coordinators include them in delegations; coders implement and validate; read-only reviewers assess code and supplied evidence without running commands.
- Preserve existing CLI behavior, output formats, ordering, and exit status unless the approved task changes them. Do not refactor unrelated scripts.

## Procedure

1. Read the implementation, callers, applicable instructions, and nearby tests. Search for existing helpers before adding logic. Treat supplied anti-examples as evidence of what to avoid, not templates to copy.
2. Identify responsibilities, inputs, outputs, side effects, dependencies, and required execution order. Mark operations that can run independently or be reused. Define observable acceptance conditions and preservation tests before changing behavior.
3. Keep the existing core language unless a concrete requirement justifies changing it. For new scripts, choose an already-supported language suited to the work: shell for command sequencing, Python or JavaScript for complex structured data or control flow. Explain any added language or runtime.
4. Split by cohesive responsibility, not line count. Extract when responsibilities change independently, logic is duplicated, or a boundary enables meaningful testing or reuse. Keep entry points focused on argument parsing, ordering, error-to-exit translation, and reporting. Avoid generic helper buckets, trivial wrappers, and modules created solely to shorten an entry point.
5. Keep reusable logic callable without launching the CLI. Importing a module or sourcing a library must not parse CLI arguments, run commands, change the caller's environment, or mutate resources. Pass configuration and external collaborators explicitly rather than relying on mutable global state.
6. Give each operation one implementation and one clear owner. Keep substantive logic in its native language module instead of embedded programs or repeated cross-language fragments. Use a small CLI adapter only where a process boundary is needed; do not require every internal module to expose its own CLI.
7. Define predictable interfaces: arguments, environment variables, working-directory assumptions, input/output formats, errors, and side effects. Use structured formats for structured data. Keep machine-readable results on stdout and diagnostics on stderr; reserve process termination for entry points, not reusable functions. Provide useful help for user-facing CLIs, without prompting during non-interactive execution.
8. Treat subprocess arguments as data. Use argument arrays/sequences without a shell by default; do not interpolate external input into command strings. Make environment, working directory, output handling, and relevant timeouts explicit. Detect launch failures, nonzero status, and signal termination; report failures without converting them into successful results.
9. Validate inputs and prerequisites before mutation. Make state-changing operations safe to rerun where practical, and document retry and partial-failure behavior. Retry only suitable transient failures with a bounded policy. Use scoped temporary resources, guaranteed cleanup, and atomic file replacement where practical. Never overwrite or remove unrelated resources. Add dry-run or confirmation behavior only when the task's mutation risk warrants it.
10. Document contracts near public interfaces using the language's conventions. Cover purpose, inputs, outputs, errors, external commands, and side effects without narrating obvious code. Keep CLI help and directly related documentation consistent with behavior.
11. Test core logic and CLI boundaries separately using existing repository tooling. Cover successful and invalid inputs, exact output shape and exit status, dependency failures, paths with spaces, and import/source safety where relevant. For mutations, verify preflight failure changes nothing, cleanup preserves unrelated state, and repeated execution has the intended effect. Use temporary directories and safe fakes; reserve host integration tests for disposable, explicitly scoped resources.
12. Run the narrowest relevant tests, then applicable language checks. Review the diff for duplicated logic, unnecessary abstractions, undocumented interfaces, embedded programs, and accidental behavior changes. Report exact checks and limitations; never claim target-host behavior from mocks alone.

## Language Guidance

### Bash

- Follow the [shell development instructions](../../instructions/shellDevGuide.instructions.md), including function contract comments, closing separators, quoting, arrays, error handling, and source-safe libraries.
- Keep command orchestration in Bash when appropriate. Do not embed Python programs in shell heredocs; use a focused helper only for a concrete benefit. Data/template heredocs are not embedded programs.
- Run `bash -n`, `shellcheck -s bash`, and focused behavior tests for changed shell files as required by the shell instructions.

### Python

- Follow the [Python development instructions](../../instructions/pythonDevGuide.instructions.md) for uv, supported Python versions, typing, docstrings, pytest, and Ruff. Do not add separator or banner comments between functions.
- Keep CLI parsing and error-to-status translation in `main`; guard script execution with `if __name__ == "__main__":` and use `sys.exit(main())` when returning an exit status. Use a thin `__main__.py` or configured console entry point only when packaging calls for it.
- Put reusable logic in focused, importable functions or classes. Use argument sequences with `subprocess.run`, `shell=False`, and explicit failure handling such as `check=True` when nonzero status is an error.
- Use the repository's uv invocation for scripts, module CLIs, pytest, and configured lint/format checks. Do not add packaging solely to expose a helper.

### JavaScript and TypeScript

- Follow the existing runtime version, package manager, ESM/CommonJS format, and language instructions. TypeScript scripts must use the established execution or build path; do not add a transpiler or switch module formats for this workflow.
- Export reusable functions without starting work during import. Keep CLI invocation in the existing entry-point pattern or a separate thin entry file when needed; do not add a wrapper file by default.
- Await asynchronous operations and handle rejected promises at the CLI boundary with actionable stderr diagnostics and a nonzero status. Prefer setting `process.exitCode` and allowing output/cleanup to finish over calling `process.exit()` prematurely.
- Prefer `spawn` or `execFile` with argument arrays and no shell. Handle both launch errors and completion status; consume or deliberately route child streams to avoid blocked pipes.
- Use the existing test runner and configured lint/type checks. If no JavaScript test runner exists, consider the supported runtime's built-in `node:test` before proposing a dependency.

### Other Languages and Embedded Commands

- Apply the same responsibility, interface, import/load-safety, process, mutation, and testing rules through the language's native conventions.
- Inspect package tasks, CI steps, container entry points, and callers when changing a script contract. Keep short glue inline; extract substantial logic into a script that can be tested directly.

## Layout Guidance

Reuse the repository's established script, library, source, and test directories. Keep a cohesive task in one file when it is short and not independently reusable or testable. Add a helper beside related code when a real responsibility boundary warrants it, not to satisfy a prescribed tree or line budget.

## Completion Check

- All affected scripts, helpers, and callers are covered regardless of language or filename extension.
- Entry points coordinate; cohesive functions/modules own reusable work without artificial fragmentation.
- Public interfaces are explicit; importing/sourcing reusable code causes no operational side effects.
- Language/runtime choices are justified, and existing behavior is preserved unless intentionally changed.
- Validation precedes mutation; failures and cleanup preserve unrelated state.
- Focused tests and applicable language checks pass, or missing validation is explicitly reported.

## Sources and Adaptation

- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html): function contracts, argument arrays, stderr, and maintainability. Its 100-line rewrite rule is not adopted; responsibility and complexity determine extraction and language choice here.
- [Python `__main__`](https://docs.python.org/3/library/__main__.html): minimal entry points, importable logic, and exit-status conventions.
- [Python `subprocess`](https://docs.python.org/3/library/subprocess.html): argument sequences, shell boundaries, process status, and timeouts.
- [Node.js child processes](https://nodejs.org/api/child_process.html): shell-free process APIs, launch errors, completion, and stream handling.
- [Node.js process termination](https://nodejs.org/api/process.html#processexitcode): graceful exit status without truncating pending output.
- [Node.js test runner](https://nodejs.org/api/test.html): built-in testing when supported and no repository runner exists.

These sources inform the workflow, not repository-specific formatting or tooling. Responsibility-based extraction, mutation safety, and the cross-language acceptance checks above are project policy, not universal numeric thresholds.
