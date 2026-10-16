# Gateway Bootstrap

**Status:** Gateway implementation is in progress. Unrestricted routed remote access is not implemented, and host acceptance remains pending.
**Deployment authorization:** Disposable test host only. The attached VS Code environment is authorized for Podman tests; do not deploy to a live host.
**Qualification target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux disabled. No target acceptance is claimed yet.
**Observed host (2026-10-15):** RHEL 9.8 and rootful Podman 5.8.2 match. `getenforce` reports `Enforcing`, so this host does not meet the requested SELinux-disabled target. Do not change its security state; full host acceptance needs a disposable target already running with SELinux disabled.

## Decisions and Limits

- On 2026-10-08, the requester confirmed that the infrastructure owner approved Cockpit access through the rootful Podman socket. The approver's identity is not recorded here.
- On 2026-10-15, the requester selected SELinux disabled and unrestricted container egress through normal Podman host egress with masquerading. Disabling SELinux removes mandatory access controls; tests must verify the host is already disabled and must not change its security settings.
- Cockpit uses `/run/podman/podman.sock` at the same path inside the container. The bind mount is read-only, but the API still grants broad control over rootful containers. `gateway-admin` belongs to the container's root group to access that socket.
- Host deployment scripts require RHEL 9.8 and rootful Podman 5.8.2, with a working Quadlet generator and SELinux disabled. Podman's Quadlet feature floor is 4.4; it is not the supported host target. Verify package provenance and exact kernel/Quadlet behavior on the authorized disposable host.
- The image is Debian 13 `linux/amd64`, pinned to a base-image digest and Debian snapshot dated 2026-10-08. Package versions are pinned in the Containerfile. Update the snapshot, base digest, and package set together after security review.
- The container does not run systemd as PID 1. Bash supervises foreground OpenSSH, DNSMasq, and Cockpit websocket processes and forwards shutdown signals. Cockpit websocket standalone flags and the process lifecycle passed a local container smoke test.
- **Confirmed Layer 3 contract; not implemented:** the external OpenVPN server remains in place and allocates its client addresses; the Gateway will be an OpenVPN client. Multiple developers may keep simultaneous SSH TUN (`ssh -w`) sessions, each with a unique, non-overlapping interface and point-to-point address pair from a dedicated SSH pool. Both transports may coexist. This is full routed split-tunnel access to configured Podman CIDRs, not per-service forwarding. No VPN server, DHCP, TAP, or Ethernet bridging is planned.
- **Route contract; not implemented:** the external owner routes Podman CIDRs via the Gateway VPN client; Gateway reaches those CIDRs through connected Podman interfaces and returns each remote-client prefix through its owning tunnel. Container return traffic uses one deterministic host next hop per client prefix (or explicit tested policy tables), never conflicting same-prefix routes through every Podman network. Developer default routes, ordinary egress, and source addresses remain unchanged; developer access has no SNAT/DNAT, and app-to-app forwarding is denied.
- **Route lifecycle; not implemented:** validate pools/endpoints against Podman CIDRs and relevant host/developer-LAN/corporate routes, while allowing intended managed/connected routes and not blanket-rejecting defaults. OpenVPN pushed-route changes are candidate-validated on reconnect. SSH session hooks allocate/check/clean only their own addresses, interfaces, and routes. Ambiguous same-client-prefix ownership fails closed absent explicit policy. Route reconciliation is idempotent and rollback touches only candidate-owned state; no generic background watcher is planned.
- No extra Linux capabilities are currently requested; Quadlet drops unused `NET_RAW`. OpenVPN, SSH TUN, and routed remote access are not implemented. Tunnel-runtime checks must not block the container-independent, offline base Gateway bootstrap before tunnel activation is enabled. Record runtime acceptance as pending; test TUN device access, forwarding, routes, concurrent sessions, rollback, and the minimum capability set on the target host before changing privileges.
- The current [startup.sh](../../gateway/development/startup.sh) sets `PermitTunnel no`; it does not support the planned SSH TUN interface. Supporting SSH TUN requires an explicitly restricted tunnel account and target-host validation.
- **Current implementation gap:** `scripts/gateway/host_preflight.py` still requires configured containers and DNS targets to exist; its legacy Podman-state probe reports stopped containers as pending, but `scripts/deploy-gateway.sh --apply` asks permission to start stopped DNS targets. `scripts/gateway/dns_records.py` fails when a DNS target is absent or stopped. Gateway `--check` currently permits missing declared networks but does not report them as planned creation; `--apply` creates them. This is current behavior, not the approved plan: future Gateway `--check` must not probe containers and must mark each configured DNS declaration `pending readiness/unverified` from config alone. Later implementation must remove application-container prerequisites and start permissions, report planned network creation, and keep readiness-aware Podman inspection in the separate DNS refresh handoff. Gateway bootstrap must succeed without application containers and must never create, start, or otherwise operate them.
- The Gateway currently loads only gateway-login public keys from `/etc/gateway/authorized_keys`. Application destination keys remain unimplemented. The plan requires one root-managed `authorized_keys` file per container, allowing multiple public keys, read-only consumption, and installation for a dedicated non-root destination account. Host audit records file changes; PAM and operator-session controls remain external and are not revalidated here. Private keys must never be copied to the host or containers.
- The checked-in JSON declares `shared` (`192.168.7.0/24`) and `webApp` (`192.168.8.0/29`) in the top-level Podman application-network inventory. `shared` is a Podman bridge, not a physical/host interface, host network attachment, VPN route, or tunnel address pool. Gateway attaches to both, `nginx` uses `shared`, and the combined `webApp` plus `postgres` containers use both networks. This matches the all-networks Gateway contract. The approved order is Gateway bootstrap first, then application/NGINX deployment; the top-level declarations may precede those containers. Application deployment owns creating or updating app objects in the same versioned config, creating its containers, readiness, and reconciling the existing Gateway for newly declared networks; it must not create another Gateway or maintain a separate Gateway network list. Pending VPN/tunnel fields remain distinct under `gateway.remote_access`. Current host preflight still requires declared containers to exist, and current DNS generation treats absent/stopped targets as errors; this conflicts with the plan and must be changed later. Static Gateway address and HTTP proxy route validation are implemented; NGINX runtime deployment and target-host Quadlet acceptance remain pending. No services were deployed.
- Gateway SSH binds `0.0.0.0` for external forwarding; Cockpit stays on `127.0.0.1`. The perimeter controls SSH access. NGINX binds `0.0.0.0:8080` for the DHCP-assigned host address.

## Host Inputs and State

Provision Gateway-specific external inputs before `--check`. Application containers and DNS targets are not Gateway prerequisites in the approved design. The deployment never creates or overwrites external inputs.

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
| `/var/lib/gateway/dns/hosts` | `root:root`, `0644` | Replaceable DNSMasq hosts input generated from current Podman addresses. |
| `/etc/containers/systemd/gateway.container` | `root:root`, `0644` | Generated Quadlet definition. The deployment replaces it only when it matches the gateway-owned signature. |
| `/run/podman/podman.sock` | Rootful Podman socket | Host-managed endpoint. The deployment does not expose it over TCP or change host security policy. The target requires SELinux disabled. |
| Configured external OpenVPN client profile path | Root-managed, private, outside Git; mounted read-only | External server/client credentials and profile input. The external owner allocates client addresses and provisions routes to Podman CIDRs via the Gateway VPN client. The actual path/profile are deployment inputs. |
| Configured SSH TUN pool | Deployment input, distinct from Podman CIDRs and OpenVPN pool | Address source for unique point-to-point session pairs. Session/interface/route state is runtime-owned and cleaned on teardown; do not treat this pool as a Podman network. |

The generated config and DNS directories are mounted read-only. Atomic file replacement inside those directories remains visible to the running container, allowing DNSMasq to reload without retaining a bind mount to an old file inode.

Application data, volumes, secrets, and unrelated Podman resources are not owned by this deployment. The gateway never copies developer private keys or modifies application containers. Changes to the gateway public-key file, Cockpit password, or Cockpit TLS files update only non-secret metadata and trigger a restart so file bind mounts cannot keep using old inodes. A changed persistent SSH host-key fingerprint fails preflight; rotate that identity only through a separate approved procedure.

## Operator Workflow

Edit `config/host_config.json` with the real network names and non-overlapping IPv4 CIDRs. Example record:

```json
{
  "name": "backend.project-a.dev.internal",
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

Generic checks currently compare declared network subnets with existing Podman networks and inspect
containers listed in `containers` or `dns_records`; stopped containers are reported as pending.
They do not require gateway credentials, RHEL 9, or Quadlet. This current behavior is not the
approved Gateway bootstrap contract: a later implementation must scope Gateway preflight to Gateway
host/tools/credentials and network prerequisites, not application-container existence or lifecycle.
Read-only Gateway `--check` must report missing networks as planned creation without changing them.

On a disposable RHEL 9.8 host with rootful Podman 5.8.2, run read-only preflight, then apply only after it passes:

```bash
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
sudo ./scripts/deploy-gateway.sh --apply config/host_config.json
```

The current `--apply` creates missing declared networks and refreshes DNS, but it still enforces the older DNS-target presence/start behavior described above. It does not create tunnel interfaces, forwarding policy, or routes. Do not claim remote Layer 3 access is available. Base Gateway validation/bootstrap must remain container-independent and offline; lack of an OpenVPN profile or live SSH TUN runtime must not block base Gateway before tunnel activation is enabled. Runtime acceptance is pending.

The approved future handoff is revision-scoped: after its own readiness checks, application deployment requests DNS refresh; Gateway re-inspects Podman and publishes only a live, valid address for the declared network. Absent, stopped, or not-ready targets remain pending, are not started by Gateway, and have no record. Application lifecycle requests refresh after readiness, stop, and replacement. No generic background watcher is planned; protocol session lifecycle hooks are separate, narrowly scoped operations. Unexpected application crashes may leave a prior DNS record until explicit refresh or Gateway restart, but generated state must never fall back to that stale address.

Inspect and recover with:

```bash
sudo systemctl status gateway.service
sudo journalctl -u gateway.service
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
```

Apply does not delete application networks. In the approved design, Gateway apply never changes application containers; on a clean host it can bootstrap with none present. If activation or health checks fail, it restores the previous generated Quadlet, configuration, and DNS files, then attempts to restore the prior service and image tag. Newly created networks, image layers, and persistent host keys remain; failure output reports additive network changes. Inspect systemd and Podman state before retrying.

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

Validation on 2026-10-16 used repository revision `b70a962c54954911220eca48dac4b27b7d638013`.

### Local validation

- `podman build --pull=always --file gateway/development/Containerfile --tag localhost/gateway:1 gateway/development` passed.
- `bash tests/scripts/test-gateway-config.sh` passed.
- `bash tests/scripts/test-gateway-container.sh` passed, including isolated SSH, DNS refresh, Cockpit TLS, and clean shutdown checks.
- `python3 -m pytest -q` reported 56 passed and 4 failed. Failures: `test_validate_podman_state_accepts_valid_running_target`, `test_validate_podman_state_rejects_overlapping_existing_network`, `test_validate_podman_state_reports_stopped_target_as_pending`, and `test_validate_podman_state_checks_generic_container_networks`.
- `scripts/deploy-gateway.sh --validate-config` and `scripts/host-preflight.sh --validate-gateway-config` passed.
- `bash -n scripts/deploy-gateway.sh scripts/host-preflight.sh scripts/bootstrap-file-gateway.sh tests/scripts/test-gateway-config.sh tests/scripts/test-gateway-container.sh` passed.
- `scripts/deploy-gateway.sh --check` failed before further checks: `SELinux must remain Enforcing; found Disabled.`

The disposable host reports RHEL 9.8, rootful Podman 5.8.2, kernel `5.14.0-687.56.1.el9_8.x86_64`, SELinux `Disabled`, systemd 252, and the Podman Quadlet generator. The configured `shared` network (`192.168.7.0/24`) overlaps the host's connected `eth0` network (`192.168.7.0/24`). Do not apply this configuration on this host until the subnet conflict is resolved.

### Target-host acceptance

- [ ] Validate clean-host Gateway bootstrap without application containers, all-network attachment, lifecycle, reboot recovery, idempotence, persistence, and rollback.
- [ ] Validate OpenVPN profile mounting and connection, concurrent OpenVPN and SSH TUN sessions, route conflict checks, symmetric replies, full-protocol forwarding, and source-address preservation.
- [ ] Validate unrestricted container egress through host masquerading and forwarding isolation between application networks.
- [ ] Validate split DNS, readiness-scoped DNS publication, and DNS refresh after target replacement.
- [ ] Validate SSH ProxyJump, direct SSH through tunnels, and independent destination authentication.
- [ ] Validate Cockpit Podman operations through the Unix socket and the minimum required capabilities and TUN-device access.

No deployment or host-mutating acceptance test ran. The host preflight currently requires SELinux `Enforcing`, contrary to this contract's `Disabled` target. Required external Gateway credentials are also absent. Tunnel acceptance remains unimplemented and requires external VPN/session inputs. Resolve the preflight conflict, network overlap, external inputs, and failing tests before retrying host deployment. Local results do not establish target-host acceptance.

Host file-change auditing and PAM controls are assumed from the external security policy, not validated by the boilerplate. Do not claim target acceptance until the remaining gates pass on an authorized disposable RHEL 9.8 / Podman 5.8.2 system with SELinux already disabled.