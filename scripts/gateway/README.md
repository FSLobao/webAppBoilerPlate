# Gateway Python Helpers

These Python 3 helpers own strict JSON loading, structured address validation,
RHEL 9.8 / Podman 5.8.2 host preflight, general Podman state checks, and gateway
DNS data. Bash keeps workflow order, host mutations, and file staging.
Each CLI is invoked by the shell scripts with the repository root on
`PYTHONPATH`; helpers use only the Python standard library.

These host helpers keep remote-access planning separate from the container
runtimes in [`gateway/development/`](../../gateway/development/).
`remote_access` validates optional OpenVPN, SSH TUN, and WireGuard
metadata, plans candidate routes and session ownership, and exposes
callback-based application and rollback for tests. Gateway preflight checks
configured pools and the WireGuard UDP listener against read-only host state.
The client-reachable WireGuard endpoint is supplied to peer generation and is
not stored in host config or checked by Gateway preflight.
OpenVPN has no endpoint configuration field; its optional `client_pool` enables
allocation checks and the managed host return route.
The checked-in config enables OpenVPN and WireGuard; SSH TUN remains disabled.
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
WireGuard peer operations are implemented by
`gateway.development.wireguard`; host module preflight and loading are implemented
by `wireguard_kernel`. Gateway preflight checks module loadability without loading
it. Apply loads the module and configures the Gateway service to load it at every
start, while respecting host module blacklists. The host `wg` utility is not
required; the image includes `wireguard-tools`. Base Gateway bootstrap remains
container-independent and offline before tunnel activation.

## Modules

| Module | Public interface | Output and failures | External effects |
|---|---|---|---|
| `strict_json` | `load_json(path)`, `loads_json(contents)`; CLI: `python3 -m scripts.gateway.strict_json CONFIG` | Returns parsed JSON or reports invalid JSON to stderr with status 1. Rejects duplicate object keys recursively before a normal JSON object is constructed. | Reads JSON only. `scripts.gateway.strict_json` re-exports the shared implementation from `gateway.development.strict_json`; the CLI can validate shell inputs before `jq` parses them. |
| `host_config_validation` | `load_host_config(path)`, `validate_host_config(config)`; CLI: `python3 -m scripts.gateway.host_config_validation CONFIG` | Rejects the removed Gateway-level network override; file loading also rejects duplicate keys. Errors go to stderr with status 1. | Reads JSON only. Shares its implementation with container startup; top-level `networks` is the sole Podman network inventory. |
| `config_validation` | `validate_address_declarations(config)`; CLI: `python3 -m scripts.gateway.config_validation CONFIG` | CLI returns 0 on success; validation errors go to stderr with status 1. | Reads JSON only. |
| `remote_access` | `validate_remote_access_config(config)`, `validate_remote_access_host_routes(config, routes)`, `validate_activation_addresses(...)`, `plan_remote_routes(...)`, `apply_route_plan(plan, add_route, remove_route)` | Rejects retired and unknown OpenVPN fields, including legacy JSON `endpoint`, plus unknown route/CCD fields and incomplete enabled SSH TUN inputs. `client_pool` is optional. Without it, validation warns and does not validate allocation membership or plan a managed host return route. Candidate default routes and Podman-overlapping routes fail. | Pure validation and planning. Apply calls only supplied callbacks and rolls back confirmed completed changes. Callbacks must leave routes unchanged when they raise; partial mutations cannot be detected safely. It never reads an OpenVPN profile or launches host commands. |
| `gateway.development.wireguard` | CLI: `gateway-wireguard run [CONFIG]`; `gateway-wireguard server-key generate|validate`; `gateway-wireguard peer generate|approve|revoke|list` | Enabled configuration requires explicit IPv4 server/pool/UDP bind and port/resolver/key-path inputs. `--apply` generates a missing server key after preflight; an existing key is validated and reused, never replaced. Peer generation requires a reachable client endpoint through `--endpoint`; it is not host configuration. Generation creates pending public metadata and writes the one-time `.conf` profile only to verified foreground `/dev/tty`. Approval requires a reference and future timezone-aware expiry. Revocation removes only that peer. If peer rollback, interface deletion, and link-down all fail, the CLI creates a root-owned mode-0600 fail-stop marker and installs nftables drops for wg0, its published UDP input port, and IPv4 UDP output with that source port. The table comment binds its ownership to the marker token; restarts verify an exact existing table without replacing it. The server exits when its health check sees the marker; startup refuses to configure wg0 while it persists, and the Quadlet service holds failed status without automatic restart. | Uses argument-array `wg`/`ip`/`nft` calls. Persists public peer metadata, sanitized audit, and the fixed fail-stop marker only under `/var/lib/gateway/wireguard`; server private key uses the explicit read-only mount. A failed control path can leave live tunnel traffic active despite marker, nft attempt, and server exit. Operator must stop and verify runtime state before removing the marker and restarting. Never stores/logs peer private keys or exposes an HTTP/API. Run peer CLI as container root through `podman exec`; TTY checks cannot detect external recording. |
| `wireguard_kernel` | `check_wireguard_kernel_support(run_command, module_path, modprobe_path)`, `load_wireguard_kernel_support(...)`; CLI: `python3 -m scripts.gateway.wireguard_kernel` | Read-only check confirms `modprobe --dry-run` resolves WireGuard without loading it. The CLI loads the module and verifies `/sys/module/wireguard`; failures go to stderr with status 1. | Uses `/usr/sbin/modprobe --use-blacklist`; does not install packages, change module policy, or unload the shared module. |
| `host_preflight` | `host_platform_matches_target(os_id, os_version)`, `podman_version_matches_target(version)`, `selinux_mode_matches_target(mode)`, `cockpit_password_is_valid(path)`, `validate_gateway_networks(config, run_command, announce)`, `validate_podman_state(config, run_command, announce)`; CLI actions: `host-platform`, `podman-version`, `selinux-mode`, `password-file`, `gateway-networks`, `podman-state` | Gateway network checks report missing networks as planned creation and configured DNS targets as `readiness/unverified`. When WireGuard is enabled, preflight dry-runs module resolution without loading it, checks existing server-key metadata, a temporary UDP bind probe, and route conflicts before mutation. An unloaded but loadable module is reported as planned for `--apply`. A missing key is also reported as planned; preflight does not generate it. It does not validate client endpoint reachability. | The host deployment target is exactly RHEL 9.8 with rootful Podman 5.8.2 and SELinux already Disabled. Gateway checks use read-only Podman network commands and `ip -j -4 route show table all`; they do not inspect or operate application containers. Generic podman-state uses the same host-route check, retains read-only inspection of declared containers, and requires declared networks to exist. The Gateway attaches to every network in the global inventory. |
| `gateway.development.dns_records` | `generate_dns_records(config, ready_targets, run_command)`; host re-export: `scripts.gateway.dns_records` | Returns active `IPv4 name` records only for supplied configured container names and full Podman IDs that inspect as exact, running, healthy targets on configured networks/subnets. Missing, stopped, or unhealthy targets are pending. | Queries only supplied IDs and exact configured network fields through the existing Gateway Podman socket. Formatted output contains target ID/name, running/health state, and that network's IPv4 address; no environment, mounts, or secret-bearing status is printed. Writes no files. |
| `gateway.development.dns_refresh` | `effective_config_revision(config)`, `validate_handoff_request(config, request)`, `render_handoff(...)`; CLI actions: `revision CONFIG`, `request-revision REQUEST`, and `handoff --config CONFIG --hosts HOSTS` | Revision is `sha256:` plus SHA-256 of canonical effective JSON. Handoff requires `config_revision`, configured target `target_scope`, and `ready_targets` entries with configured `container` and full immutable `id`. Stale revisions and out-of-scope identities fail before inspection. | Pure validation/merge helpers are import-safe. Container CLI reads request JSON on stdin and existing hosts, inspects only supplied IDs, and writes candidate hosts to stdout. Host shell owns atomic replacement, DNSMasq validation/reload, and shared apply lock. |
| `gateway.development.ssh_tun_runtime` | OpenSSH `authkeys`, startup `check`, PAM `pam`, and forced `session` actions | Matches only plain Ed25519 keys from the root-owned configured public-key file. Reserves one bounded connection slot; PAM alone creates and removes its exact TUN interface and address pair. | Root auth-key and PAM entrypoints use private `/run` state and argument-array `ip` commands. Pending reservations expire after 60 seconds when allocator/lifecycle events run. OpenSSH liveness bounds abrupt TCP cleanup. No watcher or production key is included. |
| `gateway.development.remote_forwarding` | `acquire_forwarding(owner_id, interfaces, ...)`, `release_forwarding(owner_id, previous, ...)` | Leases one ownership-tagged nftables table and the Gateway namespace forwarding bit across OpenVPN, SSH TUN, and WireGuard. | Uses a private locked `/run` state file, allows only active tunnel interfaces to configured Podman interfaces and established replies, drops Podman-to-Podman forwarding, and never adds NAT or host routes. |

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
entry is declared. The optional pool is present in this disabled example, but
must not be inferred when absent from another configuration. Without it, runtime
checks the assigned address/mask against Podman subnets but cannot verify client
allocation or manage/validate a host return route; symmetric replies are not
guaranteed. The external profile was not read. SSH TUN remains disabled
until an operator supplies the dedicated key file, separate address pool, and
maximum session count. The fixed tunnel account is `gateway-tunnel`. Host
deployment adds one protocol-186 route for each enabled, configured pool through the
deterministic Gateway address; no production route is active from checked-in
configuration.

WireGuard is enabled in versioned config with bind `0.0.0.0`, UDP port `1194`,
peer pool `192.168.10.0/24`, server/resolver `192.168.10.1`, and key path
`/etc/gateway/wireguard/server.key`. The peer allocator reserves the server
address. `--check` stays read-only and reports planned key creation when the
path is absent. `--apply` creates a key only when absent; it reuses an existing
key to preserve previously issued client profiles and never replaces it. The
reachable client endpoint is supplied per peer with `--endpoint`; host preflight
does not test external reachability. Key creation uses a short-lived rootful,
network-isolated helper with no capabilities and one writable key-directory
mount. The long-running Gateway mounts only the key file read-only. Conditional
Quadlet publishes the configured UDP port and adds `NET_ADMIN` only when a
remote transport is enabled.

The WireGuard administrator workflow uses existing container exec; it adds no
listener or public API. Generate a pending peer profile only from a direct,
foreground, non-recording terminal:

```bash
podman exec --interactive --tty --user 0 gateway \
  gateway-wireguard peer generate \
  --id "device-01" --owner "approved-owner-id" --purpose "development access" \
  --endpoint "vpn.example.org"
podman exec --user 0 gateway gateway-wireguard peer approve \
  "device-01" --approval-reference "approved-change-reference" \
  --expires-at "YYYY-MM-DDTHH:MM:SS+00:00"
podman exec --user 0 gateway gateway-wireguard peer list
podman exec --user 0 gateway gateway-wireguard peer revoke \
  "device-01" --reason "access ended"
```

Generation writes no profile to stdout, files, environment, logs, or persistent
state. The endpoint is public metadata, not a secret; the generated profile and
private key never enter command arguments. A failed or uncertain terminal write leaves an inactive
pending peer; identify it by ID/public fingerprint and revoke it. Never retry
or recover its private key. The audit records container UID, not a proven
human identity; host audit must identify the operator invoking `podman exec`.
Trust every Gateway-container administrator with all-network access.

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
`route-ipv6` options before application. The local profile must contain no IPv6 tunnel or route directives; profile
contents remain unread by the runtime. Hooks also reject IPv6 tunnel/route variables and all
IPv4 route candidates. The route-up hook validates the assigned IPv4 address
and complete route candidates before adding the address or enabling forwarding.
With no configured `client_pool`, the hook still validates the assigned IPv4
address/mask and rejects any assigned subnet overlapping a Podman subnet, before
interface or forwarding mutation. It warns that it cannot verify allocation
membership or a host return route, so symmetric replies are not guaranteed.
Private per-process state binds hooks to one runtime, preserves valid reconnect
state, and lets the supervisor remove only its owned address and forwarding
changes. A matching pre-existing tunnel address is rejected as unowned. The
configured Podman networks are already connected, so no route is installed
through the tunnel.
`nftables` allows new forwarding only from `tun*` or `wg0` to configured
Podman interfaces, permits stateful replies, and drops application-network
forwarding. OpenVPN, WireGuard, and each SSH session hold a shared lease; one disconnect
does not remove forwarding still owned by another tunnel. The Gateway changes
IPv4 forwarding only in its namespace and restores the prior value after the
last owner exits. Quadlet installs exact protocol-186 host routes for enabled,
configured OpenVPN, SSH, and WireGuard pools through the deterministic Gateway address. No host
firewall rules or default routes are changed.

For a WireGuard fail-stop marker, do not restart or delete it automatically.
Stop the Gateway unit and have an operator verify `wg0` is deleted, no
unapproved peer remains active, and no owned protocol-186 peer route remains.
Inspect the fail-stop nftables table and remove it only after verifying its
ownership comment matches the token in the marker. The runtime never deletes a
same-name table or rebuilds an existing table. Pre-token marker/table state
cannot satisfy this check and requires manual recovery; do not infer ownership.
Only then may the operator remove `/var/lib/gateway/wireguard/critical-failure`
and start the unit explicitly. A server process exit does not prove the kernel
interface or traffic stopped; if interface controls and the nftables drop both
fail, live tunnel traffic remains an unavoidable residual risk until host
recovery.

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

All remote-access runtimes remain opt-in. The configured production profile remains
disabled; the profile file was not opened or connection-tested. Synthetic
runtime tests exercise fake command transports, concurrent reservations,
session-specific teardown, shared forwarding, secret-safe peer lifecycle, and
the address/route guards. The current host lacks WireGuard kernel support, so
kernel tunnel, packet forwarding, and source-preservation validation remain
separate from unit tests and target-host acceptance.
Activation does not require a separate profile-review confirmation. Runtime logs
are reduced to fixed sanitized diagnostics.

Run the Python tests from the repository root with
`uv run --locked python -m pytest`. These host-side helpers remain compatible
with Python 3.9, the default runtime on the RHEL 9.8 host target.