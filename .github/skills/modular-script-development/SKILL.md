---
name: modular-script-development
description: 'Design or refactor maintainable host automation and deployment scripts. Use when a script mixes languages, owns many unrelated responsibilities, or needs clear reusable modules, especially Bash orchestration with focused Python helpers and pytest coverage.'
argument-hint: 'Describe the script or workflow to design or refactor.'
---

# Modular Script Development

Create small, testable modules with explicit responsibilities and stable interfaces. Keep orchestration separate from operations that can be run and tested independently.

## When to Use

- Design or refactor deployment, bootstrap, or host-configuration scripts.
- A shell script embeds Python, JSON-processing code, or several unrelated workflows.
- Split a script into reusable tasks without creating trivial one-line modules.

## Procedure

1. Read the relevant architecture contract, repository instructions, implementation, and nearby tests. Treat supplied anti-examples as evidence of what to avoid, not as templates to copy.
2. List the script's responsibilities, side effects, inputs, outputs, and required order. Mark which tasks can run independently or be reused.
3. Keep the current core language for orchestration. If Bash owns the workflow, use Bash for command sequencing and host operations. Add another language only when it provides a strong, concrete benefit that Bash cannot provide cleanly, such as complex structured-data or address validation.
4. Split by atomic responsibility, not by line count. Prefer modules that can be invoked independently, tested, and reused. Examples include prerequisite checks, host setup, Podman network setup, container setup, and DNSMasq configuration. Keep the entry script thin and responsible for ordering, shared failure handling, and reporting.
5. Keep each module below 1,000 lines where practical; aim for about 500 or fewer. Split larger modules when their responsibilities justify it. Do not create tiny modules or wrappers solely to satisfy a size target.
6. Keep each operation's implementation in one language. Do not embed repeated Python programs in shell heredocs. Do not duplicate validation or state changes across the shell and helper module.
7. If Python is justified, put each independent task's logic in one focused, importable Python module with a clear public function. Do not combine unrelated tasks into one helper module or split a task across tiny modules. Let the shell call a small module CLI adapter, for example `python3 -m package.module`; keep the adapter thin. Add focused pytest coverage for the public function.
8. Document each module's purpose, public functions, inputs, outputs, errors, external commands, and side effects. Add docstrings to Python modules and functions. For shell, add concise comments that document each function's contract. Keep interface documentation near the module and give CLI entry points useful help text.
9. Define predictable interfaces. Prefer explicit arguments and structured input/output for structured data. Specify output format, exit status, and failure behavior. Send diagnostics to stderr and machine-readable results to stdout when both are needed.
10. Keep mutation behind explicit operations. Run validation and read-only preflight before host changes. Make retries and partial failure behavior clear; never hide failures or remove unrelated resources.
11. Add focused tests at module boundaries. Test Python functions with pytest, including invalid inputs and error cases. Test shell orchestration using existing repository conventions and safe fakes or disposable resources. Verify that a preflight failure causes no mutation.
12. Run the narrowest relevant tests first, then required repository checks. Review the diff for duplicated logic, unnecessary wrappers, undocumented interfaces, mixed-language blocks, and accidental behavior changes.

## Layout Guidance

Use the repository's established structure. A typical arrangement is:

```text
scripts/
  deploy.sh                 # workflow orchestration
  lib/
    prerequisites.sh        # host-tool and environment checks
    host_setup.sh           # host configuration
    podman_networks.sh      # declared network operations
    gateway_container.sh    # container lifecycle operations
    gateway_dns.sh          # DNSMasq inputs and reload
src/<package>/              # focused Python helpers, only when justified
  network_validation.py
```

Do not create every example module by default. Keep a task in the entry script when it is short, cohesive, and not independently reusable or testable.

## Formatting Rules

- Give every Bash function a concise contract comment, then place `# ---------------------------------- #` after its closing brace. Keep clear spacing between functions.
- Follow repository-specific Python rules. In this repository, Python modules and functions need docstrings, pytest is the test framework, and separator or banner comments between Python functions are not allowed. Use blank lines and regions only when existing guidance permits them.
- Do not add another language just to make a module appear reusable. Do not split code only to keep the entry script visually short.

## Completion Check

- Entry point coordinates; focused modules own atomic work.
- Each module has a single language and documented interface.
- Python exists only for a stated benefit and is covered by pytest.
- Module sizes remain practical without artificial fragmentation.
- Validation precedes mutation; failures preserve unrelated state.
- Focused tests and applicable repository checks pass.
