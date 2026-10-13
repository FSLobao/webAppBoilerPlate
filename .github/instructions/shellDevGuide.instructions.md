---
description: "Use when writing or reviewing Bash scripts, shell libraries, deployment automation, container startup scripts, or shell tests. Covers Bash style, safety, errors, modularity, and validation."
applyTo: "**/*.sh"
---

# Bash Shell Development

Follow repository conventions and keep shell code explicit, testable, and safe to rerun. These rules apply to executable scripts, sourced libraries, container startup scripts, and tests.

## Interpreter and Shell Mode

- Write Bash unless a specific target requires another shell. Do not claim POSIX portability for Bash scripts.
- Use `#!/usr/bin/env bash` for executable scripts, matching this repository.
- Start executable scripts with `set -Eeuo pipefail`. Document a specific reason for any exception.
- Sourced libraries must not change the caller's shell options, traps, working directory, or positional parameters when sourced.
- Handle optional arguments explicitly, such as `${1:-}`. Do not rely on unset values becoming empty by accident.

## Structure and Formatting

- Use two spaces for new shell code. Preserve the surrounding style when editing existing files; avoid unrelated reformatting.
- Keep constants near the top and declare function-local variables with `local`.
- Put executable flow in `main` when a script has multiple functions, and finish with `main "$@"`. Sourced libraries must not run a main function when loaded.
- Keep functions focused. Document each function's purpose, arguments, global state read or changed, output streams, and return status as applicable.
- End every function with this separator on its own line:

  ```bash
  # ---------------------------------- #
  ```

- Keep comments useful. Explain contracts and non-obvious reasons; do not narrate obvious commands.
- Do not impose a hard 100-line limit. Use the [modular script development skill](../skills/modular-script-development/SKILL.md) for responsibility boundaries and module-size guidance.

## Data and Command Safety

- Quote variable and command substitutions by default. Prefer `${name}` for named variables, `"${array[@]}"` for arrays, and `"$@"` to forward arguments.
- Use arrays for command arguments. Do not assemble argument lists in strings or use `eval` to execute them.
- Use `read -r` and an explicit delimiter when reading input. Do not parse lists with `for item in $(command)` or unquoted expansions.
- Keep structured-data parsing out of shell word splitting. Use an existing structured-data tool or a focused helper in another language only when it provides a clear benefit. Do not embed Python programs in shell heredocs; follow the modular script development skill.
- Use `--` before path operands when the command supports it. Treat filenames and external input as data, not options or shell code.
- Avoid aliases in scripts. Use functions for reusable commands.

## Errors and Process State

- Check important command results explicitly and report actionable errors to stderr. Keep normal results on stdout when callers may consume them.
- Do not assume `set -e` catches every failure. Its behavior changes in conditionals, pipelines, functions called from conditions, and command substitutions.
- Preserve command status when assigning command output. Declare locals separately from command substitutions, for example:

  ```bash
  local result
  result=$(some_command) || return
  ```

- Do not hide errors with `|| true` unless failure is expected and the reason is clear.
- Return nonzero from reusable library functions. Let the executable entry point decide whether to exit.
- Use `$(command)`, not legacy backticks. Use Bash `[[ ... ]]` for string and file tests and `(( ... ))` for arithmetic.

## Host and Deployment Safety

- Separate read-only checks from mutations. Validate all inputs and prerequisites before changing host state.
- Make operations idempotent where practical. Check ownership before replacing or removing generated resources; leave unrelated resources untouched.
- Stage generated files safely, use atomic replacement when practical, and clean only temporary paths created by the current process.
- Use `mktemp` for temporary files and directories. Install cleanup traps only for resources the script created; preserve the original exit status.
- Never use broad prune or deletion commands for deployment cleanup. Require explicit scope and ownership checks before destructive operations.
- Require elevated privileges only for operations that need them, and fail with a clear diagnostic when the required privilege is absent.

## Validation and Tests

- Run `shellcheck -s bash` and `bash -n` on every changed shell file. Fix findings or document a narrow, justified suppression.
- Run focused behavior tests for changed logic. Test error paths and verify preflight failures cause no mutations.
- Keep tests isolated. Prefer temporary directories and fake commands for host operations; use only disposable resources for integration tests.
- Do not claim a host integration check passed unless it ran in the required target environment.

## References

- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html)
- [ShellCheck Wiki](https://www.shellcheck.net/wiki/)
- [ShellCheck SC2086: quote to prevent word splitting and globbing](https://www.shellcheck.net/wiki/SC2086)
- [ShellCheck SC2310: `set -e` behavior in conditional function calls](https://www.shellcheck.net/wiki/SC2310)
