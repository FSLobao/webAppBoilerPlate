# Gateway Bootstrap

**Status:** Gateway implementation is in progress. Required NAT-based remote service forwarding is not implemented, and host acceptance remains pending.
**Deployment authorization:** Isolated test host only. Do not deploy to a live host.
**Qualification target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux enforcing. This target has not been tested here.

## Decisions and Limits

- On 2026-10-08, the requester confirmed that the infrastructure owner approved Cockpit access through the rootful Podman socket. The approver's identity is not recorded here.
- Cockpit uses `/run/podman/podman.sock` at the same path inside the container. The bind mount is read-only, but the API still grants broad control over rootful containers. `gateway-admin` belongs to the container's root group to access that socket.
- Host deployment scripts require RHEL 9.8 and rootful Podman 5.8.2, with a working Quadlet generator and SELinux enforcing. Podman's Quadlet feature floor is 4.4; it is not the supported host target. Verify package provenance and exact kernel/Quadlet behavior on a disposable host.
- The image is Debian 13 `linux/amd64`, pinned to a base-image digest and Debian snapshot dated 2026-10-08. Package versions are pinned in the Containerfile. Update the snapshot, base digest, and package set together after security review.
- The container does not run systemd as PID 1. Bash supervises foreground OpenSSH, DNSMasq, and Cockpit websocket processes and forwards shutdown signals. Cockpit websocket standalone flags and the process lifecycle passed a local container smoke test.
- No extra Linux capabilities are requested; Quadlet drops unused `NET_RAW`. NAT and remote service forwarding are not implemented. Test the minimum capability set, including `CAP_NET_ADMIN` only as a candidate, on the target host before adding it.
- Missing DNS targets are hard preflight errors. Read-only `--check` reports stopped targets without starting them. `--apply` asks before starting stopped targets, reruns preflight, and restores their stopped state if a later apply step fails. A running target attached to the wrong network is a hard preflight failure.
- The Gateway currently loads only gateway-login public keys from `/etc/gateway/authorized_keys`. Application destination keys remain unimplemented. The plan requires separate root-managed host public-key files, read-only consumption, and permission checks. Host audit records file changes; PAM and operator-session controls remain external and are not revalidated here. Private keys must never be copied to the host or containers.
- The checked-in JSON has empty top-level and `gateway.networks` arrays. The current deployer treats an explicit empty `gateway.networks` as no Gateway attachments; it does not yet implement the all-network contract. Updating the config schema and deployer is a required future implementation step. No code changed in this plan revision.
- The default management bind address is loopback. Remote service exposures need separately declared, infrastructure-approved host addresses and ports; do not expose SSH or Cockpit on wildcard addresses to enable NAT.

## Host Inputs and State

Provision external inputs before `--check`. The deployment never creates or overwrites them.

| Path | Owner and mode | Purpose and responsibility |
|---|---|---|
| `/etc/gateway/authorized_keys` | `root`; no group/world write | OpenSSH `authorized_keys` format. Public keys for gateway login only. Infrastructure owns updates and backup. |
| `/etc/gateway/cockpit-password` | `root:root`, `0600` | One-line password for the container's `gateway-admin` Cockpit account. Keep outside Git; infrastructure owns rotation and backup. |
| `/etc/gateway/tls/gateway.cert` | `root:root`, commonly `0644` | Cockpit TLS certificate supplied by infrastructure. |
| `/etc/gateway/tls/gateway.key` | `root:root`, `0600` | Matching Cockpit TLS private key. Keep outside Git; infrastructure owns backup and rotation. |
| `/var/lib/gateway/ssh_host_keys/` | `root:root`, `0700`; private key `0600` | Persistent Ed25519 SSH host identity, created only when both key files are absent. Infrastructure owns backup and restore. |
| `/var/lib/gateway/generated/config.json` | `root:root`, `0644` | Replaceable copy of the selected versioned configuration. |
| `/var/lib/gateway/generated/inputs.json` | `root:root`, `0644` | Non-secret file metadata and the SSH host-key public fingerprint. Detects credential/certificate replacement and avoids storing secret hashes or contents. |
| `/var/lib/gateway/dns/hosts` | `root:root`, `0644` | Replaceable DNSMasq hosts input generated from current Podman addresses. |
| `/etc/containers/systemd/gateway.container` | `root:root`, `0644` | Generated Quadlet definition. The deployment replaces it only when it matches the gateway-owned signature. |
| `/run/podman/podman.sock` | Rootful Podman socket | Host-managed endpoint. The deployment does not expose it over TCP or relabel it. SELinux may deny container access; do not disable SELinux or apply a broad relabel workaround. |

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

Generic checks compare declared network subnets with existing Podman networks and inspect only
containers listed in `containers` or `dns_records`. Stopped containers are reported as pending.
They do not require gateway credentials, RHEL 9, or Quadlet. The gateway deployment commands below
retain those stricter checks.

On a disposable RHEL 9.8 host with rootful Podman 5.8.2, run read-only preflight, then apply only after it passes:

```bash
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
sudo ./scripts/deploy-gateway.sh --apply config/host_config.json
```

The current `--apply` refreshes DNS only; it does not install NAT forwarding rules. Do not claim remote NAT access is available. After NAT is implemented, application deployment must refresh both target mappings and DNS after the target is healthy; no background watcher is currently installed.

Inspect and recover with:

```bash
sudo systemctl status gateway.service
sudo journalctl -u gateway.service
sudo ./scripts/deploy-gateway.sh --check config/host_config.json
```

Apply does not delete application networks. If activation or health checks fail, it restores the previous generated Quadlet, configuration, and DNS files, then attempts to restore the prior service and image tag. Newly created networks, image layers, and persistent host keys remain; failure output reports additive network changes. Inspect systemd and Podman state before retrying.

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

No RHEL 9.8 / Podman 5.8.2 host acceptance has been recorded. NAT-based remote service forwarding, DNAT-only source preservation and return routes, host apply, Quadlet lifecycle and reboot, SELinux socket/key-file access, Cockpit Podman operations, SSH ProxyJump and destination authentication, DNS/NAT refresh after target replacement, all-network attachment, peer network isolation, rollback, and minimum capabilities remain unvalidated. Host file-change auditing and PAM controls are assumed from the external security policy, not validated by the boilerplate. Do not claim target acceptance until the remaining gates pass on a disposable RHEL 9.8 / Podman 5.8.2 system.