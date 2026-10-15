# Gateway Python Helpers

These Python 3 helpers own structured address validation, RHEL 9.8 / Podman
5.8.2 host preflight, general Podman state checks, and gateway DNS data. Bash
keeps workflow order, host mutations, and file staging.
Each CLI is invoked by the shell scripts with the repository root on
`PYTHONPATH`; helpers use only the Python standard library.

## Modules

| Module | Public interface | Output and failures | External effects |
|---|---|---|---|
| `config_validation` | `validate_address_declarations(config)`; CLI: `python3 -m scripts.gateway.config_validation CONFIG` | CLI returns 0 on success; validation errors go to stderr with status 1. | Reads JSON only. |
| `host_preflight` | `host_platform_matches_target(os_id, os_version)`, `podman_version_matches_target(version)`, `cockpit_password_is_valid(path)`, `validate_podman_state(config, run_command, announce)`; CLI actions: `host-platform`, `podman-version`, `password-file`, `podman-state` | Podman-state errors go to stderr; stopped containers are reported to stdout as pending. | The host deployment target is exactly RHEL 9.8 with rootful Podman 5.8.2. Podman-state checks declared host networks, optional containers, and DNS targets using read-only Podman commands. Missing selected gateway networks may be allowed only for gateway deployment. It never starts containers or creates networks. |
| `dns_records` | `generate_dns_records(config, run_command)`; CLI: `python3 -m scripts.gateway.dns_records CONFIG` | Writes `IPv4 name` records to stdout; errors go to stderr with status 1. | Runs read-only `podman container exists` and `podman inspect`. It writes no files; Bash stages output and sets permissions. |

The generic host config can omit `gateway`; it declares existing networks and
optional container/network expectations. Public functions accept parsed configuration dictionaries where noted. Podman
functions accept a `subprocess.run`-compatible `run_command` for isolated tests.
Missing fields, invalid addresses, conflicting networks, and invalid container
state raise `KeyError`, `TypeError`, `ValueError`, or `RuntimeError` as
documented in each module's docstrings.

Run the Python tests with `uv sync --group dev` followed by `uv run pytest` from
the repository root. These modules remain compatible with Python 3.9, the default runtime on the
RHEL 9.8 host target.