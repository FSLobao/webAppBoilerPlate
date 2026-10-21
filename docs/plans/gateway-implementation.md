# Gateway Bootstrap

**Status:** Base Gateway bootstrap, readiness-scoped DNS handoff, and opt-in OpenVPN, SSH TUN, and additive IPv4 WireGuard runtimes are implemented. The versioned config enables OpenVPN and WireGuard; SSH TUN remains disabled. WireGuard uses bind `0.0.0.0`, UDP `1194`, pool `192.168.10.0/24` with server/resolver `192.168.10.1` reserved, and key path `/etc/gateway/wireguard/server.key`. Each client endpoint is supplied to `peer generate --endpoint`, not stored in host config. WireGuard schema, Quadlet UDP publication, public peer inventory, root-only server-key and peer lifecycle commands, `/dev/tty` one-time `.conf` profile output, and split-DNS recipes are implemented. Read-only preflight reports a missing server key as planned; `--apply` generates it only if absent and reuses an existing key. On 2026-10-20, isolated container-only WireGuard packet acceptance passed on the disposable host after the kernel module autoloaded from a `--network none --cap-add NET_ADMIN` container. The test exposed and fixed server interface activation ordering. This does not claim deployed-host acceptance. `dns_records` remains empty and no application lifecycle caller is included. No production server key, endpoint, or peer profile was used in isolated testing.
**Deployment authorization:** Disposable test host only. The attached VS Code environment is authorized for Podman tests; do not deploy to a live host.
**Qualification target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux disabled. No target acceptance is claimed yet.

## Decisions and Limits

- On 2026-10-08, the requester confirmed that the infrastructure owner approved Cockpit access through the rootful Podman socket. The approver's identity is not recorded here.
- On 2026-10-15, the requester selected SELinux disabled and unrestricted container egress through normal Podman host egress with masquerading. Disabling SELinux removes mandatory access controls; tests must verify the host is already disabled and must not change its security settings.
- Cockpit uses `/run/podman/podman.sock` at the same path inside the container. The bind mount is read-only, but the API still grants broad control over rootful containers. `gateway-admin` belongs to the container's root group to access that socket.
- Host deployment scripts require RHEL 9.8 and rootful Podman 5.8.2, with a working Quadlet generator and SELinux disabled. Podman's Quadlet feature floor is 4.4; it is not the supported host target. Verify package provenance and exact kernel/Quadlet behavior on the authorized disposable host.
- The image is Debian 13 `linux/amd64`, pinned to a base-image digest and Debian snapshot dated 2026-10-08. Package versions are pinned in the Containerfile. Update the snapshot, base digest, and package set together after security review.
- The container does not run systemd as PID 1. Bash supervises foreground OpenSSH, DNSMasq, and Cockpit websocket processes and forwards shutdown signals. Cockpit websocket standalone flags and the process lifecycle passed a local container smoke test.
- **Existing IPv4 Layer 3 paths:** the external OpenVPN server remains in place and allocates client addresses; the Gateway config enables its OpenVPN client. SSH TUN uses an explicitly configured non-overlapping pool and dedicated `gateway-tunnel` account, but remains disabled. These paths provide routed split-tunnel access to configured Podman IPv4 CIDRs, not per-service forwarding. This does not disable unrelated IPv6 on the host or client; the Gateway runtime does not force IPv4 for the outer SSH connection, so clients that need it must use `ssh -4`. The external OpenVPN server remains outside this project; no DHCP, TAP, or Ethernet bridging is planned.
- **Additive WireGuard server:** the Gateway provides an IPv4-only WireGuard runtime alongside, not instead of, OpenVPN client and SSH TUN. Approved peers receive every top-level Podman CIDR, including `shared`, application, and PostgreSQL networks. The configured peer pool is `192.168.10.0/24`; server address `192.168.10.1` is reserved inside that pool and also serves split DNS. The host listener is `0.0.0.0:1194/UDP`. The reachable client endpoint is supplied per profile through `peer generate --endpoint`; it is not in host config or preflight. `--apply` creates `/etc/gateway/wireguard/server.key` only when absent; an existing key is reused and never replaced.
- **WireGuard trust boundary:** any user with administrative privileges to the Gateway container can manage peers and can reach all configured Podman networks. Such administrators receive broad network access; service credentials remain separately required. The implemented interface is a root-only CLI through container exec; no public admin HTTP/API exists.
- **WireGuard key lifecycle:** Read-only `--check` reports a missing server key as planned. The positional deployment pipeline preflights before apply; standalone `--apply` assumes a successful prior `--check`. Apply builds a short-lived isolated helper and creates the root-owned server key only when the configured path is absent. Existing keys are cryptographically validated and reused; they are never rotated automatically. Keep the configured key to preserve previously issued client profiles. If a later apply step fails, the generated key remains for retry. The root-only `gateway-wireguard peer` CLI generates client keys inside Gateway. Pending peers are inactive. A separate explicit approval activates one peer and requires an approval reference and UTC expiry. Profiles print once only to matching foreground stdin/stdout `/dev/tty`; pipes fail closed. Private keys are never persisted, logged, placed in arguments, or placed in environment. If output fails, identify and revoke the pending peer; never retry or recover its key. Persistent audit stores container UID, peer ID, public fingerprint, operation, and public metadata. Host auditing must identify the human invoking `podman exec`. No public admin HTTP/API exists.
- **WireGuard host publication:** enabled Quadlet publishes only the explicit configured UDP bind and port. Host preflight briefly binds the configured UDP socket to detect local conflicts; it does not reserve the port or prove external reachability. The endpoint is required only for client profile generation. The requester declined an external firewall/perimeter requirement; do not add an external firewall prerequisite.
- **DNS split and migration:** internal suffix is exactly `dev.anatel`, internal-only and non-public. DNS emits A records, never AAAA. `dns_records` is currently empty. Host schema now accepts exact `.dev.anatel` names; older documentation examples were migrated. WireGuard does not push routes or DNS; its profile carries only split routes and a resolver comment, not a global DNS directive. OpenVPN pushed-domain options belong to its external server/profile and are not Gateway JSON configuration.
- **Per-OS DNS:** Windows 11 uses NRPT for `dev.anatel`; Linux uses systemd-resolved routing-only `~dev.anatel` and a per-link resolver; macOS uses `/etc/resolver/dev.anatel`. Recipes now use the implemented peer CLI. Client OS behavior still needs validation on Windows 11, Linux, and macOS systems.
- **SSH TUN key configuration:** enabling `gateway.remote_access.ssh_tun` requires `enabled`, `account`, `address_pool`, `authorized_keys_path`, and `max_sessions`. The fixed account is `gateway-tunnel`; its root-managed public-key file is mounted read-only at `/run/gateway/ssh_tun/authorized_keys`. Keep this allow-list separate from `/etc/gateway/authorized_keys` for Gateway login and from each destination container's keys. Checked-in config remains disabled and contains no production key or pool.
- **Route contract; target acceptance pending:** Gateway reaches each Podman CIDR through its connected Podman interface. Quadlet owns one host route for each configured OpenVPN, SSH, or WireGuard pool through the deterministic lowest-sorted configured Gateway address, tagged `proto 186`; service hooks add and remove each exact route. OpenVPN `client_pool` is optional. Without it, no OpenVPN host return route is rendered, inspected, or deleted, and symmetric client reply routing is not guaranteed. WireGuard reserves the server address from peer allocation and owns exact per-peer `/32` routes inside the Gateway namespace. Host preflight recognizes only exact tagged pool routes. The host Podman masquerade path still needs isolated target validation. Developer default routes and ordinary egress are not replaced; the Gateway adds no SNAT/DNAT or app-to-app forwarding rules.
- **OpenVPN runtime:** host preflight checks profile path, regular-file type, root ownership, and private mode without reading contents. Quadlet mounts the profile read-only and grants only `/dev/net/tun` plus `NET_ADMIN` when enabled. OpenVPN runs under a supervisor with `--ifconfig-noexec` and `--route-noexec`; the up hook validates the assigned address/mask before configuring `tun0`, checks allocation membership only when `client_pool` is configured, and always rejects an assigned subnet overlapping a Podman network. Missing pool emits a warning and disables allocation-prefix and host return-route validation; symmetric replies are not guaranteed. The route-up hook rejects every pushed/profile route. `nftables` limits namespace forwarding to TUN-to-Podman and stateful replies, rejects inter-network forwarding, and restores only the forwarding value changed by the runtime. Cleanup verifies the ownership comment and deletes the exact inspected kernel table handle; a same-name replacement is preserved. Logs are reduced to fixed sanitized diagnostics.
- **OpenVPN configuration ownership:** protocol, port, topology, and pushed-domain options come from the external server/profile; `client_to_client` is server-side. Gateway JSON keeps the opaque profile path and optional `client_pool`; it has no OpenVPN endpoint field. This new setup keeps schema version 1 but rejects retired OpenVPN fields, including legacy JSON `endpoint`, without migration compatibility. The profile remains opaque and is not inspected by this project; activation has no separate profile-review confirmation.
- **Shared-forwarding rollback failure:** when runtime state remains writable, an acquisition rollback that cannot remove its exact nftables table or restore the original IPv4 forwarding value persists the owner, table tag, original value, and failed rollback steps in root-owned runtime state. New acquisition and release calls then fail closed until operator recovery. If state persistence also fails, callers still receive a typed critical exception, but no shared-state recovery record is guaranteed. The state does not claim that forwarding is fully rolled back; inspect recorded ownership against live nftables and sysctl state before removing only resources that still match. WireGuard also records its persistent critical marker, attempts UDP/interface drop rules, and attempts to remove `wg0`; OpenVPN and SSH report the critical acquisition failure and do not mark the lease successful. No automatic recovery command exists.
- Runtime acceptance remains pending. The versioned config enables OpenVPN, but its opaque production profile was not read or tested; external file references, plugins, scripts, endpoint behavior, and authentication requirements remain human-review inputs. SSH TUN remains disabled. SSH `-N` suppresses the forced session; use a session request with the fixed forced command. `AuthorizedKeysCommand` runs a root-owned, fixed Python helper as root because the isolated OpenSSH 10.0p2 image accepts the setting; the helper validates the exact dedicated account, Ed25519 key allow-list, and normalized connection endpoints before creating a bounded reservation. It accepts no client command or executable input and does not allocate interfaces before PAM authentication. The required PAM hook provisions only the allocated user-owned TUN and IPv4 point-to-point pair; a failed hook aborts before OpenSSH handles the TUN request. The real two-session integration test exercises successful open/close, source preservation, and independent teardown. Pending unauthenticated slots expire after 60 seconds on allocator/lifecycle events; no watcher or process-table scan runs. Tunnel-only `ClientAliveInterval 15` / `ClientAliveCountMax 3` bounds lost TCP cleanup. Shared nftables leases allow `tun*` to configured Podman interfaces and established replies, drop Podman-to-Podman forwarding, and add no NAT. The fixed command rejects non-empty `SSH_ORIGINAL_COMMAND`, reports its assigned client-side address pair, and holds the session until disconnect. The OpenSSH 10.0p2 probe found reversed `%C` endpoint order versus PAM `SSH_CONNECTION`; the integration ran against the same upstream version. Both values are normalized as unordered endpoint pairs. Production values remain absent. Actual target host routes, DNS forwarding, abrupt-loss timing, reconnect races, real OpenVPN coexistence, and operator network review remain outstanding. See [the permission probe](../evidence/ssh-tun-permission-probe-2026-10-19.md) and [runtime test record](../evidence/ssh-tun-runtime-implementation-2026-10-19.md).
- **Remaining WireGuard deployment gates:** the versioned config defines bind `0.0.0.0:1194/UDP`, peer pool `192.168.10.0/24`, server/resolver `192.168.10.1`, and key path `/etc/gateway/wireguard/server.key`. The peer allocator reserves `.1`; read-only preflight reports key creation as planned when the file is absent. `--apply` creates it with a short-lived helper only after preflight and image build, validates existing keys without replacing them, and retains a generated key if later steps fail. A reachable endpoint is required only for `peer generate --endpoint` and is not checked by host preflight. The interface is fixed as `wg0`. Target network and client acceptance remain pending. The root-only CLI, peer approval reference, expiry, audit metadata, and direct-TTY one-time `.conf` output are implemented. See [Gateway plan, Phase 7](gateway-plan.md#phase-7-wireguard-peer-onboarding-and-split-dns).
- The current [startup.sh](../../gateway/development/startup.sh) keeps `PermitTunnel no` by default. When explicitly enabled, it limits point-to-point TUN access to the dedicated account, root-managed key command, fixed forced session command, and required PAM lifecycle hook.
- **Phase 1 preflight behavior (2026-10-19):** Gateway `--check` validates Podman network definitions and checks declared subnets against all IPv4 host routes, including local-address routes. It ignores default routes and allows only exact connected routes or bridge-local addresses demonstrably matching inspected declared Podman networks; it does not blanket-ignore routes on Podman-named interfaces. Generic `host-preflight.sh --check` runs the same route check and retains its declared-container inspection and stopped-container reporting behavior. Gateway preflight and apply do not inspect or operate application containers or DNS targets. Missing networks are reported as planned creation, and DNS declarations are reported as `readiness/unverified` from config alone. `--apply` writes only pending DNS comments; readiness-scoped DNS refresh is a separate explicit handoff.
- **Readiness-scoped DNS handoff (2026-10-19):** `scripts/refresh-gateway-dns.sh --revision` prints `sha256:` plus SHA-256 of canonical UTF-8 JSON (sorted keys, compact separators) for the effective generated host config. `--handoff REQUEST.json` accepts a strict JSON envelope with `config_revision`, `target_scope`, and `ready_targets`; target scope lists only configured `dns_records[].container` names affected by one app readiness event, and each ready identity supplies that configured name and its full Podman container ID. Application lifecycle callers must send a complete scope for affected DNS targets: omit stopped, failed, or pending targets from `ready_targets`; send the replacement's new ID after replacement. The Gateway re-inspects only supplied IDs, verifies exact container ID/name, running and healthy state, and each exact configured DNS network/subnet. Absent or unhealthy targets stay pending, and old addresses within scope are removed without stale fallback. Other configured targets remain unchanged. The handoff stages and tests DNSMasq hosts, atomically replaces the managed file, and signals DNSMasq; the root shell entrypoint never starts/stops or inspects application containers. `--apply` and handoff share a host lock. No application lifecycle caller, generic watcher, or app-side Gateway-file editing is added in this slice.
- **Remote-access implementation slice (2026-10-19):** Schema version 1 accepts optional strict `gateway.remote_access` metadata without changing the sole top-level Podman `networks` inventory. The current config enables OpenVPN with only the opaque profile path and optional client pool; protocol, port, device, topology, client-to-client behavior, authentication, cipher, domain pushes, and endpoint are not duplicated in Gateway JSON. SSH TUN remains disabled with no configured account, key path, session limit, or address pool. Enabling it requires all four explicit inputs and a root-owned non-empty public-key file. The account is the image's locked, non-root `gateway-tunnel` user. Gateway `--check` validates configured pools against Podman CIDRs and host routes; default routes are ignored. The root auth-key command reserves idempotently under a private lock; PAM alone provisions the interface after authentication. Per-session resources and shared OpenVPN/SSH forwarding are ownership-checked. Quadlet adds one deterministic host return route per enabled pool. The external profile was not read, copied, parsed, or mounted. Production key/pool values, end-to-end source-preservation testing, and target acceptance remain pending.
- The Gateway currently loads only gateway-login public keys from `/etc/gateway/authorized_keys`. Application destination keys remain unimplemented. The plan requires one root-managed `authorized_keys` file per container, allowing multiple public keys, read-only consumption, and installation for a dedicated non-root destination account. Host audit records file changes; PAM and operator-session controls remain external and are not revalidated here. Private keys must never be copied to the host or containers.
- The requester confirmed on 2026-10-19 that `192.168.9.0/24` is available and approved for use. This is an approval/availability confirmation, not a measured host route-table result. The checked-in JSON declares `shared` (`192.168.9.0/24`, Gateway `192.168.9.2`) and `webApp` (`192.168.8.0/29`) in the top-level Podman application-network inventory. `shared` remains a Podman bridge, not a physical/host interface, host network attachment, VPN route, or tunnel address pool. Gateway attaches to both, `nginx` uses `shared`, and the combined `webApp` plus `postgres` containers use both networks. This matches the all-networks Gateway contract. The approved order is Gateway bootstrap first, then application/NGINX deployment; the top-level declarations may precede those containers. Application deployment owns creating or updating app objects in the same versioned config, creating its containers, readiness, and reconciling the existing Gateway for newly declared networks; it must not create another Gateway or maintain a separate Gateway network list. Pending VPN/tunnel fields remain distinct under `gateway.remote_access`. Static Gateway address and HTTP proxy route validation are implemented; NGINX runtime deployment and target-host Quadlet acceptance remain pending. No services were deployed.
- Gateway SSH binds `0.0.0.0` for external forwarding; Cockpit stays on `127.0.0.1`. The perimeter controls SSH access. NGINX binds `0.0.0.0:8080` for the DHCP-assigned host address.

## Host Inputs and State

Provision base Gateway external inputs before `--check`; tunnel-runtime inputs are separate and are not required for base checks or bootstrap. Application containers and DNS targets are not Gateway prerequisites in the approved design. The deployment never creates or overwrites external inputs.

| Path | Owner and mode | Purpose and responsibility |
|---|---|---|
| `/etc/gateway/authorized_keys` | `root`; no group/world write | OpenSSH `authorized_keys` format. Public keys for gateway login only. Infrastructure owns updates and backup. |
| `/etc/gateway/application-keys/<container>/authorized_keys` | `root:root`, `0600` | Multiple public keys for one container's dedicated non-root destination account. The path is referenced by config and mounted read-only. Never store private keys here. |
| `/etc/gateway/cockpit-password` | `root:root`, `0600` | One-line password for the container's `gateway-admin` Cockpit account. Keep outside Git; infrastructure owns rotation and backup. |
| `/etc/gateway/tls/gateway.cert` | `root:root`, commonly `0644` | Cockpit TLS certificate supplied by infrastructure. |
| `/etc/gateway/tls/gateway.key` | `root:root`, `0600` | Matching Cockpit TLS private key. Keep outside Git; infrastructure owns backup and rotation. |
| `/var/lib/gateway/ssh_host_keys/` | `root:root`, `0700`; private key `0600` | Persistent Ed25519 SSH host identity, created only when both key files are absent. Infrastructure owns backup and restore. |
| `/var/lib/gateway/generated/config.json` | `root:root`, `0644` | Replaceable copy of the selected versioned configuration. |
| `/var/lib/gateway/generated/inputs.json` | `root:root`, `0644` | Non-secret file metadata and the SSH host-key public fingerprint. Detects credential/certificate replacement and avoids storing secret hashes or contents. |
| `/var/lib/gateway/dns/hosts` | `root:root`, `0644` | Replaceable DNSMasq hosts input. Gateway apply records configured names as pending and does not query target containers. |
| `/etc/containers/systemd/gateway.container` | `root:root`, `0644` | Generated Quadlet definition. The deployment replaces it only when it matches the gateway-owned signature. |
| `/run/podman/podman.sock` | Rootful Podman socket | Host-managed endpoint. The deployment does not expose it over TCP or change host security policy. The target requires SELinux disabled. |
| `/etc/gateway/openvpn/ERMXDF02.ovpn` | Root-managed, private, outside Git; authorized read-only runtime mount | Supplied external OpenVPN client profile. Runtime mounting and activation are authorized, but the profile was not read or used this phase. Do not read or copy it. VPN client prefixes, routes, and ownership remain separate inputs. |
| Configured SSH TUN pool | Deployment input, distinct from Podman CIDRs and OpenVPN pool | Address source for unique point-to-point session pairs. Session/interface/route state is runtime-owned and cleaned on teardown; do not treat this pool as a Podman network. |

The generated config and DNS directories are mounted read-only. Atomic file replacement inside those directories remains visible to the running container, allowing DNSMasq to reload without retaining a bind mount to an old file inode.

Application data, volumes, secrets, and unrelated Podman resources are not owned by this deployment. The gateway never copies developer private keys or modifies application containers. Changes to the gateway public-key file, Cockpit password, or Cockpit TLS files update only non-secret metadata and trigger a restart so file bind mounts cannot keep using old inodes. A changed persistent SSH host-key fingerprint fails preflight; rotate that identity only through a separate approved procedure.

## Operator Workflow

Edit `config/host_config.json` with the real network names and non-overlapping IPv4 CIDRs. The
`dev.anatel` is the accepted internal suffix. `dns_records` remains empty, so the example below is
only a configuration shape and does not assert a live DNS answer:

```json
{
  "name": "backend.project-a.dev.anatel",
  "container": "project-a-backend",
  "network": "project-a-net"
}
```

Validate the versioned input without host access or writes:

```bash
./scripts/deploy-gateway.sh --validate-config config/host_config.json
```

The reusable host preflight can also validate host configurations without a gateway section:

```bash
./scripts/host-preflight.sh --validate-config config/host_config.json
sudo ./scripts/host-preflight.sh --check config/host_config.json
```

Generic checks compare declared network subnets with existing Podman networks and inspect containers
listed in `containers` or `dns_records`; stopped containers are reported as pending. They do not
require gateway credentials, RHEL 9, or Quadlet. Gateway checks use a separate network-only
preflight: missing networks are reported as planned creation and each DNS declaration is reported
as `readiness/unverified`, without inspecting application containers.

On a disposable RHEL 9.8 host with rootful Podman 5.8.2, run read-only preflight, then apply only after it passes:

```bash
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
sudo ./scripts/deploy-gateway.sh --apply config/host_config.json
```

The one-argument alternative runs validation, preflight, and apply in order:

```bash
sudo ./scripts/deploy-gateway.sh config/host_config.json
```

Standalone `--apply` assumes that `--check` passed and does not repeat preflight. Apply-stage
Quadlet/DNS candidate validation and post-activation health checks remain enabled.
Startup health retries use the configured timeout and interval. If the Gateway unit reaches a
terminal inactive/failed state, apply stops retrying immediately. On activation or readiness failure,
the script prints Podman and systemd diagnostics, stages a temporary Quadlet/drop-in with automatic
restart and container removal disabled, and preserves the failed state instead of rolling it back.
A later retry reuses only the ownership-marked override; successful health checks restore the normal
Quadlet and remove that override.

`--apply` creates missing declared networks and installs config-only pending DNS comments; it does not inspect, create, start, stop, or otherwise operate application/DNS-target containers. The readiness-scoped DNS refresh handoff remains unimplemented, so pending names do not resolve until that handoff exists. For explicitly enabled remote-access config, Quadlet owns only the configured host pool routes; per-session Gateway interfaces and forwarding are created by authenticated tunnel runtimes. Do not claim remote Layer 3 access from config validation alone. Base Gateway validation/bootstrap remains container-independent and offline; the supplied OpenVPN profile and live SSH TUN session are not needed for base bootstrap. Production activation still requires operator inputs and runtime acceptance.

The approved future handoff is revision-scoped: after its own readiness checks, application deployment requests DNS refresh; a dedicated refresh operation will inspect Podman and publish only a live, valid address for the declared network. Absent, stopped, or not-ready targets remain pending, are not started by Gateway, and have no record. Application lifecycle requests refresh after readiness, stop, and replacement. No generic background watcher is planned; protocol session lifecycle hooks are separate, narrowly scoped operations. Unexpected application crashes may leave a prior DNS record until explicit refresh or Gateway restart, but generated state must never fall back to that stale address.

Inspect and recover with:

```bash
sudo systemctl status gateway.service
sudo journalctl -u gateway.service
sudo podman ps -a --filter name=gateway
sudo podman inspect gateway
sudo podman logs --tail 100 gateway
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
```

If the container is still running, use `sudo podman exec -it gateway /bin/bash` for interactive
inspection. A stopped container remains available to `podman inspect` and `podman logs`.

Apply does not delete application networks. In the approved design, Gateway apply never changes
application containers; on a clean host it can bootstrap with none present. Failures before service
activation restore the previous generated Quadlet, configuration, and DNS files, then attempt to
restore the prior service and image tag. Activation or readiness failures instead preserve the
debug Quadlet, ownership-marked systemd drop-in, and Podman container for diagnosis; a successful
retry restores normal service behavior and removes the temporary override. Newly created networks,
image layers, and persistent host keys remain; failure output reports additive network changes.

Decommissioning is a separate operator action. First stop and disable the gateway, then remove only its generated Quadlet and container. Keep application networks, host keys, secrets, and application data unless their owners separately approve removal:

```bash
sudo systemctl disable --now gateway.service
sudo rm -- /etc/containers/systemd/gateway.container
sudo systemctl daemon-reload
sudo podman rm gateway
```

## Local Checks

On an x86_64 development host with Podman, `jq`, `ssh-keygen`, and OpenSSL:

```bash
podman build --pull=always --file gateway/development/Containerfile \
  --tag localhost/gateway:1 gateway/development
bash tests/scripts/test-gateway-config.sh
bash tests/scripts/test-gateway-container.sh
```

The container test uses temporary keys and a self-signed certificate, creates no network attachment or published port, and removes its test container and temporary files on exit.

## Validation Status

Validation ran on 2026-10-19 in the uncommitted worktree based on revision `0d29e67b2a26130e58e2028bca66ad049db864ff`. The host matched the qualification OS/runtime baseline: RHEL 9.8 (`redhat-release-9.8-1.0.el9.x86_64`), rootful Podman 5.8.2 (`podman-5.8.2-7.el9_8.x86_64`), SELinux `Disabled`, systemd 252, and the Podman Quadlet generator. `/dev/net/tun` existed as a root-owned character device with mode `0666`; no tunnel was activated. The kernel was `5.14.0-687.56.1.el9_8.x86_64`. Python 3.14.8 matched `pyproject.toml`.

Read-only host checks and observed results:

- `. /etc/os-release && printf '%s %s\n' "$ID" "$VERSION_ID"`: `rhel 9.8`.
- `podman version`: client/engine `5.8.2`; `podman info --format 'rootless={{.Host.Security.Rootless}} selinux={{.Host.Security.SELinuxEnabled}} graph={{.Store.GraphRoot}}'`: `rootless=false selinux=false`.
- `getenforce`: `Disabled`.
- `systemctl --version | head -n 1`: `systemd 252 (252-67.el9_8.6)`.
- `rpm -qf /usr/bin/podman /usr/libexec/podman/quadlet; rpm -q redhat-release podman`: both Podman files belonged to `podman-5.8.2-7.el9_8.x86_64`; RHEL release was `redhat-release-9.8-1.0.el9.x86_64`.
- `uname -r`: `5.14.0-687.56.1.el9_8.x86_64`; `stat -c '%F %a %U:%G' /dev/net/tun`: `character special file 666 root:root`.
- `ip -j -4 route show table all`: read the route table summarized below.

The observed IPv4 route table contained the default route via `192.168.7.1`, connected route `192.168.7.0/24`, and loopback/local routes. It had no overlap with configured `shared` (`192.168.9.0/24`) or `webApp` (`192.168.8.0/29`). The read-only Gateway network preflight passed and reported both networks as planned creation. It did not create networks or inspect application containers.

Passed checks:

- `python3.14 -m scripts.gateway.host_preflight gateway-networks config/host_config.json` passed against actual Podman networks and host routes. It reported `shared` and `webApp` as planned network creation.
- `bash tests/scripts/test-gateway-config.sh` passed all configuration and isolated host-preflight cases, including fake Podman and route-command coverage.
- `podman build --file gateway/development/Containerfile --tag localhost/gateway:1 gateway/development` passed. The pinned image ID remained `8b47ec7ed39e4315cb796faccca9444c6e4f083ddbba3dc28429844c47c685b3`.
- `bash tests/scripts/test-gateway-container.sh` passed: missing mounts were rejected; the image had no generated SSH host keys; SSH key authentication, DNSMasq record refresh, Cockpit TLS, and SIGTERM shutdown worked. This isolated test used generated test-only credentials, `--network none`, and removed its test container.
- `./scripts/deploy-gateway.sh --validate-config config/host_config.json` and `./scripts/host-preflight.sh --validate-config config/host_config.json` passed.
- `python3.14 -m scripts.gateway.strict_json config/host_config.json` and `python3.14 -m scripts.gateway.host_config_validation config/host_config.json` passed.
- `python3.14 -m compileall -q scripts/gateway tests/scripts/test_gateway_host_preflight.py` passed.
- `bash -n scripts/host-preflight.sh scripts/deploy-gateway.sh gateway/development/startup.sh tests/scripts/test-gateway-config.sh tests/scripts/test-gateway-container.sh` passed.
- `git diff --check` passed.
- After the smoke test, no `gateway-test-*` container remained; `gateway.service` remained inactive and host routes were unchanged.

Follow-up validation ran on 2026-10-19 in the same uncommitted worktree based on revision `0d29e67b2a26130e58e2028bca66ad049db864ff`. The repository has no `uv.lock`, so `uv sync --locked` was not run and no dependency or lock files changed. User-local uv 0.8.22 was installed from the official x86_64 release after its SHA-256 matched `741ff1f5742c5a4a25d2f829e8395355e43f7a5ae2ebc6368e9ae2df0efb69cf`; system Python was not changed. With `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never`, `uv run --no-project --python python3.14 --with pytest==8.4.2 python -m pytest -q tests/scripts/test_gateway_host_preflight.py` passed (52 tests), and the same command with `-q` passed the full suite (85 tests). The first focused attempt using the `pytest` console entry point failed collection because `scripts` was not importable; using `python -m pytest` fixed the invocation.

`bash -n tests/scripts/test-gateway-container.sh` and `bash tests/scripts/test-gateway-container.sh` passed; the isolated container test left no test container. `shellcheck` was unavailable, so that check did not run. Ruff is unavailable and is not configured in `pyproject.toml`.

These results separate mocked route regression coverage (`test-gateway-config.sh`) from the successful live, read-only route-table preflight. The image tests prove local container service behavior on the target-matched disposable host, not Quadlet activation or full target acceptance. No `--apply`, host setting change, network creation, route mutation, tunnel activation, or OpenVPN profile access occurred. The prior approval for `192.168.9.0/24` remains distinct from the actual route-table observation above.

### Latest OpenVPN runtime-slice validation (2026-10-19)

This record covers the current uncommitted worktree based on revision
`0d29e67b2a26130e58e2028bca66ad049db864ff`. The repository now has `uv.lock`;
the commands below used `uv run --locked`. The earlier note above that no lock
file existed describes the preceding validation environment.

- `uv run --locked python -m pytest` passed: 137 tests.
- `uv run --locked python -m pytest tests/scripts/test_gateway_openvpn_runtime.py -q` passed: 18 tests.
- `tests/scripts/test-gateway-config.sh` passed, including the target Quadlet
  generator dry-run and checks that cleanup removes only the exact
  protocol-186 return route.
- `podman build --pull=always --file gateway/development/Containerfile --tag localhost/gateway:1 gateway/development`
  passed. Image ID: `fc5f526f0ccaa6650311ce27f3d56c12c7641c93cc7497d823939e568a3c4252`.
- `tests/scripts/test-gateway-container.sh` passed against that rebuilt image:
  missing mounts were rejected, the image contained the OpenVPN runtime/tools
  and no generated SSH host keys, and the SSH/DNSMasq/Cockpit lifecycle smoke
  test passed and removed its test container.
- `bash -n gateway/development/startup.sh scripts/deploy-gateway.sh tests/scripts/test-gateway-config.sh tests/scripts/test-gateway-container.sh`
  passed.
- `uv run --locked ruff check gateway/development/openvpn_runtime.py tests/scripts/test_gateway_openvpn_runtime.py`
  and `uv run --locked ruff format --check gateway/development/openvpn_runtime.py tests/scripts/test_gateway_openvpn_runtime.py`
  passed.
- `uv run --locked ruff check .` reported six findings: two existing `TRY004`
  findings in `scripts/gateway/host_preflight.py` and four existing test import
  or unused-import findings in
  `tests/scripts/test_gateway_config_validation.py`,
  `tests/scripts/test_gateway_host_preflight.py`, and
  `tests/scripts/test_strict_json.py`. They are outside this runtime slice and
  were not changed. `shellcheck` was unavailable.
- `./scripts/deploy-gateway.sh --check config/host_config.json` stopped
  read-only with status 1 because
  `/etc/gateway/authorized_keys` is missing, empty, or not a regular file.
  No credential was created to bypass that preflight.

No deployment apply, live route mutation, profile read, OpenVPN connection,
TUN activation, packet-level source-preservation test, or external server
change was performed. The profile remains opaque and OpenVPN disabled in the
checked-in config. Source preservation and symmetric reply routing therefore
remain unverified; the host's Podman masquerade path is an explicit acceptance
risk. SSH TUN remains the next runtime implementation slice.

### Target-host acceptance

- [ ] Validate clean-host Gateway bootstrap without application containers, all-network attachment, lifecycle, reboot recovery, idempotence, persistence, and rollback.
- [ ] Validate OpenVPN profile mounting and connection, concurrent OpenVPN and SSH TUN sessions, route conflict checks, symmetric replies, full-protocol forwarding, and source-address preservation.
- [ ] Validate unrestricted container egress through host masquerading and forwarding isolation between application networks.
- [ ] Validate split DNS, readiness-scoped DNS publication, and DNS refresh after target replacement.
- [ ] Validate SSH ProxyJump, direct SSH through tunnels, and independent destination authentication.
- [ ] Validate Cockpit Podman operations through the Unix socket and the minimum required capabilities and TUN-device access.

No deployment, Quadlet service activation, route mutation, remote runtime test, or full target acceptance test ran. The supplied OpenVPN client profile at `/etc/gateway/openvpn/ERMXDF02.ovpn` is authorized for read-only runtime mounting and activation, but was not read or used this phase. Remaining blockers include VPN client prefixes, routes, and ownership; the SSH TUN pool and restricted account/session policy; client OS details; and external server routing. `/dev/net/tun` presence was checked, but TUN use and required capabilities were not tested.

### Reviewer defect follow-up (2026-10-19)

The initial OpenVPN runtime slice was already present in the uncommitted
worktree: `gateway/development/openvpn_runtime.py` and its test file were
untracked at the start of this follow-up, based on revision
`0d29e67b2a26130e58e2028bca66ad049db864ff`. The worktree also contained
unrelated pre-existing changes. This follow-up addresses only the three
Reviewer findings in that runtime.

- OpenVPN's installed Debian 13 version is 2.6.14. It rejects
  `--ifconfig-ipv6-noexec` and `--route-ipv6-noexec`; runtime uses documented
  `--pull-filter reject` rules for pushed IPv6 interface/route options,
  `--block-ipv6`, and candidate rejection instead. The operator-reviewed
  local profile must contain no IPv6 tunnel or route directives. Profile
  contents remain unopened.
- Forwarding and tunnel address setup moved to route-up, after address and
  route candidates validate. Failed initial candidates make no kernel changes.
  Private mode-0700 runtime state binds hooks to one random attempt ID, records
  owned tunnel/forwarding changes, preserves valid reconnect state, and lets
  cleanup preserve unrelated addresses and pre-existing matching addresses.
- `uv run --locked python -m pytest` passed: 144 tests; focused OpenVPN tests
  passed: 25 tests.
- Scoped Ruff lint/format, Python compile, and `git diff --check` passed.
  Repository-wide Ruff still reports the six pre-existing findings listed
  above; no unrelated files were changed to address them.
- A temporary image build passed with ID
  `1e7a8e2d45824c1fa71a7b28107cd56d7f81c1d37de2a6a2e2b4714df05dfd1a`.
  Image smoke confirmed fail-closed missing mounts, runtime compilation,
  OpenVPN IPv6 option parsing, runtime help, and packaged tools/hooks. The
  temporary image tag was removed. No full service lifecycle image test ran
  during this follow-up.
- No deploy apply, profile read, OpenVPN connection, TUN activation, or host
  route/firewall mutation occurred. The profile remains opaque and disabled.

Host file-change auditing and PAM controls are assumed from the external security policy, not validated by the boilerplate. Do not claim target acceptance until the remaining gates pass.

### SSH TUN permission probe (2026-10-19)

The scoped probe used generated Ed25519 keys, isolated rootful Podman network namespaces, `/dev/net/tun`, and `NET_ADMIN`. It did not use a production key or profile, or manually change a host route or sysctl. Direct root TUN creation succeeded in both namespaces. With `PermitTunnel point-to-point`, a matching `tunnel="0"` key, and a non-root UID 1000 session, OpenSSH opened `/dev/net/tun` but `ioctl(TUNSETIFF)` returned `EPERM` after privilege separation dropped the session process to UID 1000.

Precreating persistent `tun0` and `tun1` as root with each device owned by the dedicated test UID let those same non-root SSH sessions attach successfully. Two root-owned key slots, each restricted to its own tunnel ID, carried simultaneous bidirectional TCP packet tests; the server observed each distinct client tunnel source address. A third fixed key command also opened a TUN session without `-N`. The test confirms that a fixed per-key command runs with a session request, while `ssh -N -w` opens the tunnel channel without invoking a session command.

This does not implement or accept the production SSH TUN lifecycle. Static slots do not provide a dynamic allocator; the probe did not test safe interface teardown, Gateway-to-Podman forwarding, host return routes, OpenVPN coexistence, or RHEL-host OpenSSH behavior. The checked-in Gateway still sets `PermitTunnel no`. The test containers, generated host key, and synthetic private keys were removed. Podman removed the temporary container endpoints; no manual host route, sysctl, or security setting was changed.

### Readiness-scoped DNS handoff validation (2026-10-19)

Validation used Python 3.14.8, locked uv dependencies, rootful Podman 5.8.2,
and disposable containers/networks only. `uv run --locked python -m pytest`
passed 182 tests with one existing opt-in SSH integration skipped. The focused
DNS tests passed 26 tests. Scoped Ruff lint/fix and format checks, Bash syntax
checks, `git diff --check`, both Gateway config validation CLIs, and the
existing `tests/scripts/test-gateway-config.sh` passed. `shellcheck` was not
installed.

`podman build --pull=always --file gateway/development/Containerfile --tag
localhost/gateway:1 gateway/development` passed. Final image ID:
`24336fc0290010e5fc89b4bb244f34ab2a39fcaf058d295b9b2e59078bc2759b`.
`tests/scripts/test-gateway-container.sh` passed its isolated SSH, DNSMasq,
Cockpit, and shutdown smoke test.

`tests/scripts/test-gateway-dns-runtime.sh` passed against actual DNSMasq in
the isolated Gateway container. A temporary rootful Podman API socket let the
Gateway inspect only the supplied full target ID. The test observed the
healthy target address, forced a distinct address for a replacement identity,
verified DNSMasq served the replacement and no longer served the old address,
then sent a stopped-target handoff and verified the name no longer resolved
after real DNSMasq reload. Its exact test containers, network, socket service,
and temporary files were cleaned up. The first runtime attempt caught a
malformed Go-template delimiter before inspection; the template was corrected
and final runtime validation passed. No application deployment or host Gateway
apply occurred.

No live `--check` or `--apply` was run. No production Gateway file, route,
systemd unit, host security setting, production credential, or OpenVPN profile
was read or changed. RHEL 9.8 / Podman 5.8.2 Quadlet lifecycle, host return-route
idempotence, and reboot recovery remain host acceptance gates. Application
deployment still must call the explicit handoff on readiness, stop/failure,
and replacement events.

### Final verification (2026-10-19)

Validation ran in the uncommitted worktree based on revision
`0d29e67b2a26130e58e2028bca66ad049db864ff`, on RHEL 9.8 with rootful Podman
5.8.2, SELinux disabled, Python 3.14.8, and uv 0.8.22.

- `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never uv lock --check` and
  `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never uv sync --locked` passed.
- `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never uv run --locked python -m pytest -q`
  passed: 188 tests, 1 opt-in SSH integration skipped.
- `RUN_GATEWAY_SSH_TUN_INTEGRATION=1 UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never uv run --locked python -m pytest -q tests/scripts/test_gateway_ssh_tun_integration.py`
  passed: the real two-session same-key SSH TUN/PAM test verified concurrent
  sessions, distinct source preservation, privileged PAM UID, and independent
  teardown.
- `tests/scripts/test-gateway-config.sh` passed its validation, Quadlet
  rendering, and exact owned-route cleanup cases.
- `podman build --pull=always --file gateway/development/Containerfile --tag localhost/gateway:1 gateway/development`
  passed. Final image ID:
  `b3b18f6b5fa6c99853bec527f635010285801bb60ad1ec64df1ebaaec0d4f7ad`.
- `tests/scripts/test-gateway-container.sh` passed missing-mount rejection,
  image content checks, SSH authentication, DNSMasq refresh, Cockpit TLS, and
  clean shutdown using generated test-only credentials.
- `tests/scripts/test-gateway-dns-runtime.sh` passed against actual DNSMasq:
  it published a healthy target, replaced its container identity and address,
  removed the stale address, then removed the stopped target after reload.
  The test's `python3` lookup was scoped to `/usr/bin/python3.14`.
- `bash -n gateway/development/startup.sh scripts/deploy-gateway.sh scripts/host-preflight.sh scripts/refresh-gateway-dns.sh tests/scripts/test-gateway-config.sh tests/scripts/test-gateway-container.sh tests/scripts/test-gateway-dns-runtime.sh`
  and `git diff --check` passed.
- Ruff lint on the new Gateway modules and related tests passed. Repository-wide
  `ruff check .` still reports four baseline findings in
  `tests/scripts/test_gateway_config_validation.py`,
  `tests/scripts/test_gateway_host_preflight.py`, and
  `tests/scripts/test_strict_json.py`. Repository-wide
  `ruff format --check .` reports four baseline files; comparison with the
  committed tree confirmed the same findings predate this worktree. No
  repository-wide formatting was applied. `shellcheck` was unavailable.
- `python3.14 -m scripts.gateway.host_preflight gateway-networks config/host_config.json`
  passed against live Podman and IPv4 host routes. It reported `shared`
  (`192.168.9.0/24`) and `webApp` (`192.168.8.0/29`) as planned network
  creation. Route state matched the pre-test observation. This scoped network
  preflight did not read credentials; the full deployment `--check` was not
  run because it validates live password and private-key material.

All disposable test containers, networks, temporary credentials, and the
temporary Podman API socket process were cleaned up. No host route or security
setting changed. The built `localhost/gateway:1` image is intentionally kept.
No deployment `--apply`, production key use, OpenVPN profile access, or
production tunnel activation occurred.

Remaining acceptance requires an operator's explicit non-secret review of the
real OpenVPN profile and endpoint behavior; external VPN-server and client
return-path evidence; the application owner's readiness/stop/replacement
integration with the DNS handoff; and authorized Quadlet start/stop/reboot
testing plus the Windows 11 client VM check. These are external acceptance
gates; this verification found no new implementation failure.

### Final verification (2026-10-20)

Validation ran in the existing uncommitted worktree. The checked-in
WireGuard configuration remains disabled and contains no deployment values.

- `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never /root/.local/bin/uv lock --check`
  passed.
- `UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never /root/.local/bin/uv run --locked python -m pytest -q`
  passed: 218 tests, 1 skipped. Focused WireGuard, remote-access, forwarding,
  and host-preflight tests passed: 122 tests.
- Ruff passed on WireGuard runtime, shared forwarding, remote-access validation,
  and their directly scoped tests. Including
  `tests/scripts/test_gateway_host_preflight.py` reports one pre-existing
  `PLR0402` import finding at line 12; the same line exists in `HEAD` and was
  not changed. No unrelated lint cleanup was applied.
- `bash -n` passed on all six changed Bash files:
  `gateway/development/startup.sh`, `scripts/deploy-gateway.sh`,
  `scripts/host-preflight.sh`, `tests/scripts/test-gateway-config.sh`,
  `tests/scripts/test-gateway-container.sh`, and
  `tests/scripts/test-gateway-dns-runtime.sh`. `shellcheck` is unavailable.
- `tests/scripts/test-gateway-config.sh` passed its configuration, Quadlet
  rendering, and exact owned-route cleanup cases.
- `nft --check --file -` accepted source-generated `inet` fail-stop table
  statements with test-only port/ownership values and normal shared forwarding
  rules with test-only interfaces. This includes the family-neutral output UDP
  drop expression using `meta l4proto udp`; this is syntax validation, not
  live firewall acceptance.
- Eight changed documentation files passed fenced-JSON parsing, local-link and
  heading-anchor checks. All four fenced JSON blocks parsed, 39 local links
  resolved. WireGuard recipes use the configured internal DNS suffix, and the
  implementation documentation records that suffix.
- A read-only host preflight with test-only in-memory WireGuard values stopped
  before key metadata or Podman inspection because the host has no loaded
  WireGuard kernel module. The host also has no `wg` utility. No module was
  loaded, no host route or production configuration changed, and no key value
  or OpenVPN secret was read.
- The final image built under unique tag
  `localhost/gateway:verify-20261020T103150-42281`, image ID
  `5a485e5a5fcd6c5fe62049a511e21bf09cd350a5182c91173fe1bb51eb598920`.
  `tests/scripts/test-gateway-container.sh` passed against that image in
  network-none mode: the fail-stop marker remained, `wg0` was not initialized,
  and SSH, DNSMasq, Cockpit TLS, DNS refresh, and shutdown remained functional.
  `tests/scripts/test-gateway-dns-runtime.sh` passed against real DNSMasq in
  the same image. The unique image tag is retained; test-owned containers,
  network, temporary credentials, and temporary files were cleaned by their
  scoped test cleanup.

At that preflight point, the host had no loaded WireGuard kernel support and
the host had no `wg` utility. The follow-up container-only interface probe
autoloaded the existing kernel module without host package installation or
`modprobe`; the host `wg` utility was not needed because the image contains
`wireguard-tools`. The isolated packet test below used only temporary test
configuration and generated test keys. It did not use an external endpoint,
production UDP port, production peer pool, production server address,
production resolver, production key path, or production peer.

### Isolated WireGuard packet test (2026-10-20)

The test ran against the current worktree based on revision
`15526f66870a7edf3cccea969da98a5cdfe954ce`, on Linux
`5.14.0-687.56.1.el9_8.x86_64` with rootful Podman `5.8.2`.

- Build command: `podman build --file gateway/development/Containerfile --tag localhost/gateway:wg-packet-fixed-20261020130059-54779 gateway/development`
- Image ID: `a78c2a8da03894295fc563a5ce4434994d3f4a0d622e064febdd8fe3f0586fde`.

- Container-only interface probe passed:
  ```sh
  podman run --rm --network none --cap-add=NET_ADMIN --cap-drop=NET_RAW \
    --entrypoint /bin/sh localhost/gateway:wg-packet-20261020125010-47241 \
    -c 'ip link add dev wg-probe type wireguard &&
    ip -brief link show dev wg-probe && ip link del dev wg-probe'
  ```
  WireGuard interface creation worked without a host WireGuard utility or host
  package change.
- The packet test used internal-only Podman networks `10.250.110.0/24`,
  `10.250.120.0/24`, and `10.250.130.0/24`. Temporary config used UDP port
  `51820`, loopback host bind `127.0.0.1`, private underlay endpoint
  `10.250.130.2`, peer pool `198.18.240.0/28`, server tunnel address
  `10.254.0.1`, and DNS server `10.250.110.2`. No host port was published.
- Generated test-only server/client keys and pre-approved public peer metadata
  established a real handshake. Both app containers returned HTTP 200 through
  the tunnel. Each app observed client source `198.18.240.1`; no SNAT occurred.
  DNSMasq resolved `echo.app.dev.anatel` to the test app. A routed app-A to
  app-B probe was dropped by Gateway forwarding policy.
- App return routes existed only inside the disposable app containers. No host
  return route was added. Host IPv4 routes and rules matched their exact
  pre-test snapshots after cleanup; host `net.ipv4.ip_forward` remained `1`.
  Test containers, networks, temporary credentials, and this task's image tags
  were removed. Pre-existing image tags were preserved.
- The test exposed a runtime defect: Linux rejected the approved peer route
  while `wg0` was down (`Device for nexthop is not up.`). Server activation now
  acquires the Gateway forwarding policy, raises `wg0`, then adds approved
  peers and their routes. The focused regression test checks this ordering.
- The passing packet test used pre-approved test-only public metadata. The
  PTY-based one-time profile CLI was not part of that run; a PTY harness
  attempt returned nonzero. CLI secret handling and peer lifecycle remain
  covered by unit tests.

Full-suite command:

```sh
UV_PYTHON=python3.14 UV_PYTHON_DOWNLOADS=never uv run --locked python -m pytest -q
```

It passed: 219 tests, 1 skipped. Target acceptance remains pending for Quadlet
service activation, host return routes, external endpoint reachability,
deployed firewall behavior, and real client OS behavior. This isolated packet
test does not establish production or full target-host acceptance.

### Follow-up WireGuard startup rollback regression (2026-10-20)

Review found that a forwarding-acquisition `ForwardingError` can occur after
`wg0` creation but before an ownership token returns. `_configure_server` now
deletes only that startup attempt's `wg0` and does not release an unacquired
forwarding lease. Unit tests verify unchanged peer inventory and report failed
interface deletion as critical without claiming cleanup.

The current worktree full-suite run passed: 221 tests, 1 skipped. Scoped Ruff
lint and format checks passed. No host runtime or integration test was run for
this follow-up; the packet acceptance evidence above remains unchanged.
