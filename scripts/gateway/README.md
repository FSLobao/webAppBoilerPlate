# Gateway Python Helpers

These Python 3 helpers own strict JSON loading, structured address validation,
RHEL 9.8 / Podman 5.8.2 host preflight, general Podman state checks, and gateway
DNS data. Bash keeps workflow order, host mutations, and file staging.
Each CLI is invoked by the shell scripts with the repository root on
`PYTHONPATH`; helpers use only the Python standard library.

These host helpers keep remote-access planning separate from the container
runtimes in [`gateway/development/`](../../gateway/development/).
`remote_access` validates disabled-by-default metadata, plans candidate routes
and session ownership, and exposes callback-based application and rollback
for tests. Gateway preflight checks configured pools and literal endpoints
against read-only host route state. SSH TUN allocation and PAM cleanup are
implemented but remain disabled until production inputs and target acceptance.
The Gateway remote-access path is IPv4-only: configured Podman destinations,
tunnel pools and pairs, host return routes, and generated DNS A records use
IPv4. Enabling `gateway.remote_access.ssh_tun` requires exactly `enabled`,
`account`, `address_pool`, `authorized_keys_path`, and `max_sessions`; the
account is `gateway-tunnel`. Its root-managed public-key file is mounted
read-only at `/run/gateway/ssh_tun/authorized_keys`, separate from Gateway
login keys and per-container destination keys.
The confirmed Layer 3 contract and acceptance
requirements are in
[`docs/plans/gateway-plan.md`](../../docs/plans/gateway-plan.md) and
[`docs/contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md`](../../docs/contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md).
Tunnel-runtime acceptance must remain pending; base Gateway bootstrap is planned
to remain container-independent and offline before tunnel activation.

## Modules

| Module | Public interface | Output and failures | External effects |
|---|---|---|---|
| `strict_json` | `load_json(path)`, `loads_json(contents)`; CLI: `python3 -m scripts.gateway.strict_json CONFIG` | Returns parsed JSON or reports invalid JSON to stderr with status 1. Rejects duplicate object keys recursively before a normal JSON object is constructed. | Reads JSON only. `scripts.gateway.strict_json` re-exports the shared implementation from `gateway.development.strict_json`; the CLI can validate shell inputs before `jq` parses them. |
| `host_config_validation` | `load_host_config(path)`, `validate_host_config(config)`; CLI: `python3 -m scripts.gateway.host_config_validation CONFIG` | Rejects the removed Gateway-level network override; file loading also rejects duplicate keys. Errors go to stderr with status 1. | Reads JSON only. Shares its implementation with container startup; top-level `networks` is the sole Podman network inventory. |
| `config_validation` | `validate_address_declarations(config)`; CLI: `python3 -m scripts.gateway.config_validation CONFIG` | CLI returns 0 on success; validation errors go to stderr with status 1. | Reads JSON only. |
| `remote_access` | `validate_remote_access_config(config)`, `validate_remote_access_host_routes(config, routes)`, `validate_activation_addresses(...)`, `plan_remote_routes(...)`, `apply_route_plan(plan, add_route, remove_route)` | Rejects unknown OpenVPN route/CCD fields and incomplete enabled SSH TUN inputs. OpenVPN activation also requires an operator's `profile_reviewed: true` acknowledgment and a deterministic host return-route gateway. Candidate default routes and Podman-overlapping routes fail. | Pure validation and planning. Apply calls only supplied callbacks and rolls back confirmed completed changes. Callbacks must leave routes unchanged when they raise; partial mutations cannot be detected safely. It never reads an OpenVPN profile or launches host commands. |
| `host_preflight` | `host_platform_matches_target(os_id, os_version)`, `podman_version_matches_target(version)`, `selinux_mode_matches_target(mode)`, `cockpit_password_is_valid(path)`, `validate_gateway_networks(config, run_command, announce)`, `validate_podman_state(config, run_command, announce)`; CLI actions: `host-platform`, `podman-version`, `selinux-mode`, `password-file`, `gateway-networks`, `podman-state` | Gateway network checks report missing networks as planned creation and configured DNS targets as `readiness/unverified`. Declared Podman networks and configured remote pools are checked against one IPv4 host-route snapshot; default routes are ignored, and exact connected/local bridge routes are allowed only when Podman inspection proves the declared network interface and subnet. Generic podman-state errors go to stderr; stopped containers are reported to stdout as pending. | The host deployment target is exactly RHEL 9.8 with rootful Podman 5.8.2 and SELinux already Disabled. Gateway checks use read-only Podman network commands and `ip -j -4 route show table all`; they do not inspect or operate application containers. Generic podman-state uses the same host-route check, retains read-only inspection of declared containers, and requires declared networks to exist. The Gateway attaches to every network in the global inventory. |
| `gateway.development.dns_records` | `generate_dns_records(config, ready_targets, run_command)`; host re-export: `scripts.gateway.dns_records` | Returns active `IPv4 name` records only for supplied configured container names and full Podman IDs that inspect as exact, running, healthy targets on configured networks/subnets. Missing, stopped, or unhealthy targets are pending. | Queries only supplied IDs and exact configured network fields through the existing Gateway Podman socket. Formatted output contains target ID/name, running/health state, and that network's IPv4 address; no environment, mounts, or secret-bearing status is printed. Writes no files. |
| `gateway.development.dns_refresh` | `effective_config_revision(config)`, `validate_handoff_request(config, request)`, `render_handoff(...)`; CLI actions: `revision CONFIG`, `request-revision REQUEST`, and `handoff --config CONFIG --hosts HOSTS` | Revision is `sha256:` plus SHA-256 of canonical effective JSON. Handoff requires `config_revision`, configured target `target_scope`, and `ready_targets` entries with configured `container` and full immutable `id`. Stale revisions and out-of-scope identities fail before inspection. | Pure validation/merge helpers are import-safe. Container CLI reads request JSON on stdin and existing hosts, inspects only supplied IDs, and writes candidate hosts to stdout. Host shell owns atomic replacement, DNSMasq validation/reload, and shared apply lock. |
| `gateway.development.ssh_tun_runtime` | OpenSSH `authkeys`, startup `check`, PAM `pam`, and forced `session` actions | Matches only plain Ed25519 keys from the root-owned configured public-key file. Reserves one bounded connection slot; PAM alone creates and removes its exact TUN interface and address pair. | Root auth-key and PAM entrypoints use private `/run` state and argument-array `ip` commands. Pending reservations expire after 60 seconds when allocator/lifecycle events run. OpenSSH liveness bounds abrupt TCP cleanup. No watcher or production key is included. |
| `gateway.development.remote_forwarding` | `acquire_forwarding(owner_id, interfaces, ...)`, `release_forwarding(owner_id, previous, ...)` | Leases one ownership-tagged nftables table and the Gateway namespace forwarding bit across OpenVPN and SSH sessions. | Uses a private locked `/run` state file, allows only `tun*` to configured Podman interfaces and established replies, drops Podman-to-Podman forwarding, and never adds NAT or host routes. |

The generic host config can omit `gateway`; its top-level `networks` array
declares the Podman application/service networks, with optional container and
network expectations. Both preflight paths compare declared networks with
IPv4 routes from all routing tables, including local-address routes. They
permit default routes and only exempt exact connected/local routes tied to
the inspected interface and subnet of a declared Podman network. Gateway
network validation is separate and permits missing declared networks while
reporting planned creation. Duplicate object keys at any nesting level are invalid;
the shared strict JSON loader rejects them before lossy parsing. Public
functions accept parsed configuration dictionaries where noted. Podman
functions accept a `subprocess.run`-compatible `run_command` for isolated Podman
and `ip` command tests. Optional `gateway.remote_access` metadata remains
disabled in the checked-in host config. OpenVPN is described as UDP/1194,
`tun`, `topology subnet`, `auth SHA256`, `cipher AES-256-CBC`, client pool
`172.24.0.0/21`, and pushed domain `anatel.gov.br`; no Podman route push or CCD
entry is declared. The external profile was not read. SSH TUN remains disabled
until an operator supplies the dedicated key file, separate address pool, and
maximum session count. The fixed tunnel account is `gateway-tunnel`. Host
deployment adds one protocol-186 route for each enabled pool through the
deterministic Gateway address; no production route is active from checked-in
configuration.

The root-owned readiness CLI accepts a JSON request like:

```json
{
  "config_revision": "sha256:<64 lowercase hexadecimal digits>",
  "target_scope": ["api"],
  "ready_targets": [
    {
      "container": "api",
      "id": "<full 64-character Podman container ID>"
    }
  ]
}
```

`target_scope` contains all configured DNS container names affected by that
app event. `ready_targets` contains only IDs reported ready; the Gateway
independently requires exact identity, running state, healthy state, and the
configured network address. Stop/failure notifications keep the target in
scope and omit its identity. A replacement event supplies the replacement ID.
Create root-owned requests with mode `0600`; the handoff contains no secrets. Obtain
the current hash with `sudo scripts/refresh-gateway-dns.sh --revision`, then
invoke `sudo scripts/refresh-gateway-dns.sh --handoff REQUEST.json`. The app
caller does not write Gateway files or manage the Gateway lifecycle.
Missing fields, invalid addresses, conflicting networks, and invalid container
state raise `KeyError`, `TypeError`, `ValueError`, or `RuntimeError` as
documented in each module's docstrings. `scripts/refresh-gateway-dns.sh
--revision` returns the active canonical configuration revision;
`--handoff REQUEST.json` applies one root-controlled, readiness-scoped handoff.
The request scope names configured DNS target containers affected by one
application event. Include every affected configured target in `target_scope`;
include only currently ready full Podman IDs in `ready_targets`. Stop/failure
events omit the target identity to remove its former record. Replacement events
provide the replacement ID. The Gateway checks running and healthy state again,
then atomically publishes only records valid for the scoped targets. Bootstrap
and apply stay application-container independent. No watcher or app-side edits
to Gateway files are used.

The container-only `gateway.development.openvpn_runtime` validates profile
ownership, mode, and read-only mount flags without opening profile contents.
OpenVPN runs as a supervised client with `--ifconfig-noexec`, `--route-noexec`,
and `--block-ipv6`. `--pull-filter reject` rejects pushed `ifconfig-ipv6` and
`route-ipv6` options before application. The operator-reviewed local profile
must contain no IPv6 tunnel or route directives; profile contents remain
unread by the runtime. Hooks also reject IPv6 tunnel/route variables and all
IPv4 route candidates. The route-up hook validates the assigned IPv4 address
and complete route candidates before adding the address or enabling forwarding.
Private per-process state binds hooks to one runtime, preserves valid reconnect
state, and lets the supervisor remove only its owned address and forwarding
changes. A matching pre-existing tunnel address is rejected as unowned. The
configured Podman networks are already connected, so no route is installed
through the tunnel.
`nftables` allows new forwarding only from `tun*` to configured Podman
interfaces, permits stateful replies, and drops application-network
forwarding. OpenVPN and each SSH session hold a shared lease; one disconnect
does not remove forwarding still owned by another tunnel. The Gateway changes
IPv4 forwarding only in its namespace and restores the prior value after the
last owner exits. Quadlet installs exact protocol-186 host routes for enabled
OpenVPN and SSH pools through the deterministic Gateway address. No host
firewall rules or default routes are changed.

SSH TUN runs only for the locked, non-root `gateway-tunnel` account. Root's
`AuthorizedKeysCommand` is one root-owned fixed helper; local OpenSSH accepts
`AuthorizedKeysCommandUser root`. The helper validates key type and exact
key-file membership before reserving; client command data cannot select a
program. PAM `open_session` validates the same canonical endpoint pair and
creates the allocated `tunN` as `gateway-tunnel` before OpenSSH attaches.
Required PAM failure aborts the SSH session. `close_session` removes only the
recorded interface and shared-forwarding lease. Public-key paths and maximum
sessions are mandatory when enabled. The fixed command rejects non-empty
`SSH_ORIGINAL_COMMAND`, reports the client-side peer pair, and stays alive
until disconnect. Do not use `ssh -N`: the client must request a session.

Both runtimes remain opt-in. The configured production profile remains
disabled; the profile file was not opened or connection-tested. Synthetic
runtime tests exercise fake command transports, concurrent reservations,
session-specific teardown, shared forwarding, and the address/route guards.
Disposable actual SSH TUN and source-preservation validation remains separate
from normal unit tests and target-host acceptance.
`profile_reviewed: true` is an operator attestation because profile plugins
and external file references cannot be verified without reading profile
contents. Runtime logs are reduced to fixed sanitized diagnostics.

Run the Python tests from the repository root with
`uv run --locked python -m pytest`. These host-side helpers remain compatible
with Python 3.9, the default runtime on the RHEL 9.8 host target.