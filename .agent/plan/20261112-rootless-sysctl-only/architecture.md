# Architecture: rootless host sysctl-only mode

**Status:** `ready_for_planning` (architecture complete; no unresolved decisions)

## Objective and scope

Add a supported `--sysctl-only` apply mode to
`deploy/scripts/prepare-rootless-host.sh`. It configures and verifies
`net.ipv4.ip_unprivileged_port_start=443` using the existing sysctl file and
verification path, without inspecting or changing SELinux or firewall state and
without calling `systemctl`.

In scope:

- Preserve the current no-argument broad apply, `--check`, and help exit
  behavior.
- Add focused tests and update the CLI help, `README.md`, and the rootless
  Gateway recipe where they describe this host-preparation operation.
- Keep the new mode root-only, dependency-free, and isolated from real host
  state in tests.

Out of scope: changing the broad legacy apply behavior, introducing another
host-preparation executable, changing deployment checks, or changing the
architecture contract.

## Acceptance criteria

1. `--sysctl-only` writes only `/etc/sysctl.d/90-rootless-ports.conf` as
   `net.ipv4.ip_unprivileged_port_start=443\n` with mode `0644`, applies it
   through the existing `sysctl -p` path, and verifies the runtime value is
   `443`.
2. Its dispatch path does not call `preflight`, firewall inspection/mutation
   helpers, SELinux inspection/mutation helpers, or `systemctl`.
3. Root, sysctl-specific commands, `/etc/sysctl.d`, the target path type, the
   current runtime value, and existing file contents/mode are checked before
   any persistent or runtime mutation.
4. All inputs, prerequisites, and rollback state (target-file presence,
   contents, mode, and current runtime value) are read before mutation.
   Preflight/read failure guarantees the target file and runtime value remain
   unchanged. After a config/runtime mutation starts, failure triggers
   best-effort restoration of the previous file presence/content/mode and
   runtime value where feasible; restoration failures are reported. Absolute
   rollback cannot be guaranteed under OS, filesystem, or kernel failures.
5. Repeated successful runs converge to the same exact content, mode, and
   runtime setting. Existing no-argument apply, `--check`, and help continue to
   work with their existing success/error conventions.
6. Tests use disposable state and safe command fakes; they do not alter host
   sysctls, SELinux, firewall state, or services and introduce no dependency.
7. Documentation clearly distinguishes the isolated sysctl mode from broad
   legacy apply, and separately preserves the architecture's SELinux and
   external-firewall requirements for deployment.

## Recommended architecture

Keep the behavior in the existing Bash script. Add one explicit mode state
(recommended CLI spelling: `--sysctl-only`) and branch in `main` after argument
parsing, help handling, the existing root check, and installation of the temp
file cleanup trap:

1. Run a sysctl-only preflight and capture the complete rollback snapshot:
   whether the target file exists, its contents and mode if present, and the
   current runtime value. Complete all prerequisite and state reads before
   attempting a target-file or runtime mutation.
2. Run the existing `prepare_sysctl` implementation through a sysctl-only
   transaction boundary. If a target-file or runtime mutation has started and
   the operation fails, attempt to restore the prior file state and runtime
   value independently, report each restoration failure, and preserve the
   original operation's explicit nonzero failure behavior.
3. Return its status without entering broad preflight, firewall processing, or
   SELinux processing.

The sysctl-only preflight should check only the prerequisites the reused path
and restoration need: `sysctl`, `cmp`, `mktemp`, `mv`, `chmod`, `stat`, and
`rm`; the sysctl directory; and, if present, that the target is a regular
non-symlink file. Read and save the target's complete contents and mode, its
presence/absence, and the current runtime value before mutation. Do not include
`systemctl`, SELinux files or runtime probes, firewall state, or commands used
only by the broad path. `prepare_sysctl` already reads the runtime value,
compares the full desired file content, obtains its mode, and decides whether
a change is required before its first write; retain those checks in the
pre-mutation phase.

Preflight/read failures must not change the target file or runtime value. Once
a persistent-file or runtime mutation has started, any failure in installation,
application, or post-apply verification must trigger best-effort restoration:
if the file previously existed, restore its content and mode; if it did not,
remove the newly created target; and restore the saved runtime value through
the sysctl interface when feasible. Attempt file and runtime restoration
independently so one rollback failure does not suppress the other. Report
rollback failures in addition to the original failure, and retain the original
operation's nonzero exit behavior. This is not an absolute atomicity promise:
OS, filesystem, or kernel failures can also prevent rollback.

The sysctl-only mode deliberately does **not** decide whether SELinux is
disabled or whether host firewall services are in an approved state. It must
not call their inspectors, even read-only. This is distinct from the full
deployment contract: before deploying, operators must still satisfy that
contract's SELinux requirement and use the externally managed firewall policy.
The mode can be invoked when those external conditions are not met; it will
only prepare the requested sysctl.

Do not reinterpret `--check` as a sysctl-only check. Its current broad
read/report behavior remains unchanged. Document it as the broad check, and
describe `--sysctl-only` as an apply-only operation. No new check option is
required by this scope.

## Component boundaries and data flow

```text
arguments
   |
   +-- no args / --check --> existing broad preflight --> sysctl
   |                                             --> firewall
   |                                             --> SELinux
   |
   +-- --sysctl-only --> root check --> sysctl-only preflight
                                          --> snapshot file/runtime state
                                          --> existing sysctl state read/compare
                                          --> atomic config write if needed
                                          --> sysctl -p --> runtime verification
                                          --> best-effort restore on post-mutation failure
```

- **CLI adapter (`parse_args`, `usage`, `main`):** recognize one new option,
  preserve old argument handling and status behavior, select the correct
  preflight and operation sequence.
- **Sysctl-only preflight:** validate only prerequisites and target-path
  safety for sysctl work and capture all state needed for rollback before
  mutation; no SELinux/firewall data flow.
- **Existing sysctl operations (`compare_file_line`, `write_sysctl_config`,
  `prepare_sysctl`):** sole owners of exact-content comparison, 0644 mode,
  atomic replacement, immediate apply, and runtime verification. The
  sysctl-only transaction boundary owns the pre-mutation snapshot and invokes
  best-effort restoration on a post-mutation failure; broad-mode behavior
  remains unchanged.
- **Existing broad preflight and operations:** unchanged and reachable only
  from existing broad modes.
- **Tests:** invoke a disposable script copy with a temporary sysctl directory
  and fake `sysctl`; fail loudly or record any attempted call to
  `systemctl`/SELinux probes. This avoids adding a production path override or
  making tests dependent on host configuration.
- **Documentation:** CLI help and README describe both modes; the recipe uses
  `--sysctl-only` for sysctl preparation and independently retains the
  architecture/deployment gates.

## Contracts and compatibility

| Interface | Contract |
| --- | --- |
| `prepare-rootless-host.sh` (no args) | Existing broad apply, unchanged. |
| `prepare-rootless-host.sh --check` | Existing broad, read-only report, unchanged. |
| `prepare-rootless-host.sh --sysctl-only` | Root-only sysctl apply; no SELinux/firewall inspection or mutation and no `systemctl`. |
| `-h` / `--help` | Continue to exit successfully and print usage; add the new option description. |
| Sysctl config | Exact single line `net.ipv4.ip_unprivileged_port_start=443` plus newline; mode `0644`. |
| Successful apply | `sysctl -p /etc/sysctl.d/90-rootless-ports.conf`, followed by `sysctl -n` verification of `443`. |
| Invalid arguments / missing root | Existing nonzero behavior and diagnostics remain; mode dispatch must not bypass these guards. |
| Failure before mutation | Target-file presence/content/mode and runtime value remain unchanged. |
| Failure after mutation starts | Best-effort restore prior file presence/content/mode and runtime value where feasible; report rollback failures and preserve the original operation's nonzero behavior. Absolute rollback is not guaranteed under OS/filesystem/kernel failures. |

No new runtime, package, service, environment variable, or systemd integration
is needed. `/etc/sysctl.d` is the persistent configuration surface; the
existing explicit `sysctl -p <file>` is the immediate application surface.

## Security and operational concerns

- Setting this threshold to `443` lowers the privileged-port boundary: any
  unprivileged process in the relevant network namespace may bind ports from
  443 upward, including the range 443–1023. Keep the existing recipe warning
  prominent and require operator approval and backup/reversal instructions.
- The new mode's guarantee is intentionally narrow: it cannot change firewall
  or SELinux state because it skips all related inspectors and mutators. Its
  success does not prove that the host satisfies the full deployment
  architecture.
- Preserve the existing regular-file/no-symlink check and use of an atomic
  same-directory temp file. Do not follow a symlink or replace another path.
- Tests must exercise behavior only in a temporary directory with safe command
  fakes. Cover successful apply; repeat-run idempotency; every injected
  preflight/read failure leaving config and runtime unchanged; sysctl apply
  failure restoring prior config/runtime when the fakes permit; and explicit
  reporting when rollback itself fails. For external preconditions, model
  SELinux as enforcing and firewall units as active, make any inspector
  invocation fail or record it, and confirm the mode performs no firewall,
  SELinux, or `systemctl` inspection or mutation.
- The existing sysctl path writes the config before applying it. The bounded
  contract is therefore unchanged state for preflight/read failures and
  best-effort rollback after mutation begins, not an absolute failure-atomicity
  guarantee under arbitrary OS/filesystem/kernel failures.

## Reuse candidates

| Repository path | Component | Fit | Limitations |
| --- | --- | --- | --- |
| `deploy/scripts/prepare-rootless-host.sh:240-255` | `compare_file_line` | Reuse for exact one-line content comparison; distinguishes changed content from comparison errors. | Do not move its comparison after mutation; it is called by `prepare_sysctl`. |
| `deploy/scripts/prepare-rootless-host.sh:259-282` | `write_sysctl_config` | Reuse existing same-directory `mktemp`, exact content, `0644`, and atomic `mv -T` behavior. | It is state-changing and relies on fixed `/etc/sysctl.d`; preflight must complete before calling it. |
| `deploy/scripts/prepare-rootless-host.sh:285-355` | `prepare_sysctl` | Reuse current-state reads, change detection, apply, and runtime verification unchanged. | It both inspects and mutates based on `CHECK_ONLY`; it is not a preflight by itself, and check-mode behavior should not be expanded. |
| `deploy/scripts/prepare-rootless-host.sh:30-47, 259-282` | `fail`, `log`, `cleanup_temp` | Existing diagnostics and temporary-file cleanup are appropriate for the new path. | The cleanup trap is installed in `main`; preserve its exit-status behavior. |
| `deploy/scripts/prepare-rootless-host.sh:204-237, 596-634` | Broad `preflight` and `main` | Reuse existing broad dispatch unchanged for no-argument/`--check` behavior. | Must not be called in `--sysctl-only`; it explicitly invokes systemd/firewall and SELinux checks. |
| `.agent/contracts/ARCHITECTURE.md:89-96, 358-360, 887` | Architecture contract | Defines disabled SELinux as a pre-existing deployment condition and firewall controls as external. | Does not authorize the sysctl-only preparation mode to inspect or alter these states; docs must distinguish preparation from deployment qualification. |

No shell-specific test harness or Bats dependency was found in the repository
inventory. Prefer a small Bash test harness using existing shell/coreutils and
command fakes. A disposable copy can redirect the sysctl directory in a single
test-only substitution; do not add a production environment override solely
for tests.

## Alternatives and tradeoffs

| Option | Tradeoffs | Reason not selected |
| --- | --- | --- |
| Add a `--sysctl-only` mode to the existing script (recommended) | Small dispatch change, one implementation of sysctl logic, preserves current entry point and behavior. | — |
| Add a separate sysctl-only executable | Clear standalone surface, but duplicates CLI/state logic or requires extraction and a new shared module; risks behavior drift. | More code and boundaries than one additional mode needs. |
| Reuse broad `--check` as a precondition for sysctl-only apply | Existing check reports all host state, including SELinux and firewall, but does not mutate. | Violates the explicit requirement that this mode not invoke those inspectors and couples sysctl work to unrelated state. |
| Replace the broad default with sysctl-only behavior | Avoids broad mutations by default. | Breaks the explicit no-argument compatibility requirement and changes current operational behavior. |
| Add a new dependency or host service for sysctl application | Could offer additional configuration management surfaces. | Existing `sysctl -p` and sysctl.d file already meet the requirement without a dependency or service mutation. |

## Decisions and assumptions

### Decisions

- Use `--sysctl-only` as the sole new mode name.
- Keep `--check` broad and read-only; do not add a combined mode.
- Dispatch to a sysctl-specific preflight and reuse the existing
  `prepare_sysctl` path; never call the broad preflight from the new branch.
- Treat SELinux/firewall status as outside this mode. Document the separate
  full-deployment requirements rather than adding inline probes.
- Keep tests isolated through fakes and a disposable script copy, with no
  host/runtime mutation.
- Complete all prerequisite/state reads before mutation; guarantee unchanged
  config/runtime on preflight failure; after mutation starts, attempt
  best-effort restoration of the prior target-file presence/content/mode and
  runtime value, report rollback failures, and make no absolute rollback
  guarantee under OS/filesystem/kernel failures.

### Assumptions

- The test phrase “invalid SELinux/firewall preconditions without touching
  them” means that the new operation does not require or inspect those states:
  simulated enforcing/active states must remain untouched, and the sysctl
  operation can still proceed if its own preflight passes.
- The no-argument broad mode is intentionally retained as legacy behavior
  despite the architecture contract's non-mutation rule for SELinux; this task
  adds a safer alternative without changing that compatibility surface.
- “Current state” means readable runtime sysctl value and existing target
  file's type/content/mode, all inspected before the first persistent/runtime
  mutation.

### Decision blockers

None. Failure atomicity is resolved by the bounded contract above: unchanged
state is guaranteed for preflight/read failures; restoration after mutation
begins is best effort, must report rollback failures, and is not guaranteed
under OS/filesystem/kernel failures.

## Web research

Queries were generic and contained no repository identifiers or private
content:

1. “official Linux sysctl sysctl.d manual sysctl -p configuration file RHEL 9”
2. “official systemd sysctl.d(5) man page sysctl.d drop-in file behavior Linux kernel sysctl documentation”
3. “official Linux kernel documentation net.ipv4.ip_unprivileged_port_start defines first unprivileged port security behavior”

| Candidate reviewed | Findings and use |
| --- | --- |
| Red Hat, *Managing, monitoring, and updating the kernel*, RHEL 9, Chapter 5, [Configuring kernel parameters at runtime](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_monitoring_and_updating_the_kernel/configuring-kernel-parameters-at-runtime_managing-monitoring-and-updating-the-kernel) (accessed 2026-11-12; no publication date shown) | Documents root permissions, persistent `/etc/sysctl.d/` configuration, assignment-per-line format, and applying a specific file immediately with `sysctl -p <file>`. Confirms the existing utility/file approach is supported on the target family. |
| systemd RHEL 9 manual, [`sysctl.d(5)`](https://redhat-plumbers.github.io/systemd-rhel9/sysctl.d.html), systemd 252 (accessed 2026-11-12) | Describes `.conf` assignments in `/etc/sysctl.d/` and boot-time loading by `systemd-sysctl.service`. Supports using the established drop-in for persistence; does not require restarting a service for this mode because immediate application uses `sysctl -p`. |
| Linux upstream [`Documentation/networking/ip-sysctl.rst`](https://github.com/torvalds/linux/blob/master/Documentation/networking/ip-sysctl.rst) | Search excerpt identifies `ip_unprivileged_port_start` as a network namespace sysctl and its role in the privileged-port boundary. Use the existing recipe warning to make the security impact explicit. The raw source fetch was rate-limited, so the exact current text was not independently checked. |
| `sysctl-explorer.net` result | Third-party summary of the threshold behavior; not used as normative evidence because upstream kernel documentation is preferable. |

Research limits: documentation search results do not replace RHEL 9.8 host
integration validation. The architecture and implementation behavior are
verified only against repository source and documentation, not a production
host.

## Evidence

| Claim | Evidence |
| --- | --- |
| Script sets the key, value, and persistent file path. | `deploy/scripts/prepare-rootless-host.sh:10-16` |
| Existing broad preflight requires `systemctl`, inspects both firewall units, and calls SELinux inspectors. | `deploy/scripts/prepare-rootless-host.sh:204-237` |
| Existing sysctl path checks runtime, exact file content, and mode before mutation; then atomically writes, applies with `sysctl -p`, and verifies runtime. | `deploy/scripts/prepare-rootless-host.sh:259-355` |
| Existing main invokes broad preflight before sysctl, then firewall and SELinux operations. | `deploy/scripts/prepare-rootless-host.sh:596-634` |
| README currently documents the no-argument broad behavior. | `README.md:37-52` |
| Rootless recipe currently warns that no selective mode exists and gates broad apply on SELinux/firewall status. | `docs/recipes/gateway-headscale-podman-rootless.md:232-258` |
| Architecture requires SELinux already disabled and forbids changing it; host firewall policy is external and the target notes firewall services disabled. | `.agent/contracts/ARCHITECTURE.md:89-96, 358-360, 887` |
| RHEL 9 documents the sysctl.d file and per-file `sysctl -p` application. | Red Hat RHEL 9 docs, URL above, Chapter 5, sections 5.3–5.4. |
| systemd reads sysctl.d configuration at boot. | systemd 252 `sysctl.d(5)`, URL above. |
