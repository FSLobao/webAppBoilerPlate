# Development Gateway Bootstrap

**Status:** Source implementation and local Debian 13 smoke tests complete; RHEL 9 acceptance pending.
**Deployment authorization:** Isolated test host only. Do not deploy to a live host.

## Decisions and Limits

- On 2026-10-08, the requester confirmed that the infrastructure owner approved Cockpit access through the rootful Podman socket. The approver's identity is not recorded here.
- Cockpit uses `/run/podman/podman.sock` at the same path inside the container. The bind mount is read-only, but the API still grants broad control over rootful containers. `gateway-admin` belongs to the container's root group to access that socket.
- The host script requires RHEL 9, rootful Podman 4.4 or newer, a working Quadlet generator, and SELinux enforcing. Podman 4.4 is the feature floor, not a RHEL compatibility claim. Qualify exact RHEL minor, Podman, Quadlet, kernel, and SELinux behavior on a disposable host.
- The image is Debian 13 `linux/amd64`, pinned to a base-image digest and Debian snapshot dated 2026-10-08. Package versions are pinned in the Containerfile. Update the snapshot, base digest, and package set together after security review.
- The container does not run systemd as PID 1. Bash supervises foreground OpenSSH, DNSMasq, and Cockpit websocket processes and forwards shutdown signals. Cockpit websocket standalone flags and the process lifecycle passed a local container smoke test.
- No extra Linux capabilities are requested; Quadlet drops unused `NET_RAW`. The exact required capability set remains untested. In particular, routing and NAT are not implemented until `CAP_NET_ADMIN` and the required RHEL 9 process model are demonstrated. Do not add capabilities speculatively.
- Missing or stopped DNS targets are reported as pending and omitted from generated DNS. An apply replaces gateway-owned records, so a stale address is not retained. A running target attached to the wrong network is a hard preflight failure.
- The gateway installs only gateway-login public keys. Application deployment owns destination accounts and their `authorized_keys`; it must provision developer public keys there. This repository has no application deployment pipeline yet, so destination-key provisioning and end-to-end ProxyJump authentication remain acceptance work.
- The sample JSON has empty network and DNS arrays. Add real application network/CIDR and service declarations before host preflight or apply. Add a record only for a service intended for development access.
- The default management bind address is loopback. Remote access requires an infrastructure-approved host address and perimeter rule in the JSON configuration.

## Host Inputs and State

Provision external inputs before `--check`. The deployment never creates or overwrites them.

| Path | Owner and mode | Purpose and responsibility |
|---|---|---|
| `/etc/development-gateway/authorized_keys` | `root`; no group/world write | OpenSSH `authorized_keys` format. Public keys for gateway login only. Infrastructure owns updates and backup. |
| `/etc/development-gateway/cockpit-password` | `root:root`, `0600` | One-line password for the container's `gateway-admin` Cockpit account. Keep outside Git; infrastructure owns rotation and backup. |
| `/etc/development-gateway/tls/development-gateway.cert` | `root:root`, commonly `0644` | Cockpit TLS certificate supplied by infrastructure. |
| `/etc/development-gateway/tls/development-gateway.key` | `root:root`, `0600` | Matching Cockpit TLS private key. Keep outside Git; infrastructure owns backup and rotation. |
| `/var/lib/development-gateway/ssh_host_keys/` | `root:root`, `0700`; private key `0600` | Persistent Ed25519 SSH host identity, created only when both key files are absent. Infrastructure owns backup and restore. |
| `/var/lib/development-gateway/generated/config.json` | `root:root`, `0644` | Replaceable copy of the selected versioned configuration. |
| `/var/lib/development-gateway/generated/inputs.json` | `root:root`, `0644` | Non-secret file metadata and the SSH host-key public fingerprint. Detects credential/certificate replacement and avoids storing secret hashes or contents. |
| `/var/lib/development-gateway/dns/hosts` | `root:root`, `0644` | Replaceable DNSMasq hosts input generated from current Podman addresses. |
| `/etc/containers/systemd/development-gateway.container` | `root:root`, `0644` | Generated Quadlet definition. The deployment replaces it only when it matches the gateway-owned signature. |
| `/run/podman/podman.sock` | Rootful Podman socket | Host-managed endpoint. The deployment does not expose it over TCP or relabel it. SELinux may deny container access; do not disable SELinux or apply a broad relabel workaround. |

The generated config and DNS directories are mounted read-only. Atomic file replacement inside those directories remains visible to the running container, allowing DNSMasq to reload without retaining a bind mount to an old file inode.

Application data, volumes, secrets, and unrelated Podman resources are not owned by this deployment. The gateway never copies developer private keys or modifies application containers. Changes to the gateway public-key file, Cockpit password, or Cockpit TLS files update only non-secret metadata and trigger a restart so file bind mounts cannot keep using old inodes. A changed persistent SSH host-key fingerprint fails preflight; rotate that identity only through a separate approved procedure.

## Operator Workflow

Edit `config/development-gateway.json` with the real network names and non-overlapping IPv4 CIDRs. Example record:

```json
{
  "name": "backend.project-a.dev.internal",
  "container": "project-a-backend",
  "network": "project-a-net"
}
```

Validate the versioned input without host access or writes:

```bash
./scripts/deploy-development-gateway.sh --validate-config config/development-gateway.json
```

On the isolated RHEL 9 test host, run read-only preflight, then apply only after it passes:

```bash
sudo ./scripts/deploy-development-gateway.sh --check config/development-gateway.json
sudo ./scripts/deploy-development-gateway.sh --apply config/development-gateway.json
```

After an application deployment creates or recreates a mapped container, run `--apply` again. The script reads the new address and reloads DNSMasq only when generated records change. No background watcher is installed.

Inspect and recover with:

```bash
sudo systemctl status development-gateway.service
sudo journalctl -u development-gateway.service
sudo ./scripts/deploy-development-gateway.sh --check config/development-gateway.json
```

Apply does not delete application networks. If activation or health checks fail, it restores the previous generated Quadlet, configuration, and DNS files, then attempts to restore the prior service and image tag. Newly created networks, image layers, and persistent host keys remain; failure output reports additive network changes. Inspect systemd and Podman state before retrying.

Decommissioning is a separate operator action. First stop and disable the gateway, then remove only its generated Quadlet and container. Keep application networks, host keys, secrets, and application data unless their owners separately approve removal:

```bash
sudo systemctl disable --now development-gateway.service
sudo rm -- /etc/containers/systemd/development-gateway.container
sudo systemctl daemon-reload
sudo podman rm development-gateway
```

## Local Checks

On an x86_64 development host with Podman, `jq`, `ssh-keygen`, and OpenSSL:

```bash
podman build --pull=always --file gateway/development/Containerfile \
  --tag localhost/development-gateway:1 gateway/development
bash tests/test-development-gateway-config.sh
bash tests/test-development-gateway-container.sh
```

The container test uses temporary keys and a self-signed certificate, creates no network attachment or published port, and removes its test container and temporary files on exit.

## Validation Status

Validated locally on Debian 13, x86_64: JSON validation cases, pinned image build, absence of image-baked SSH host keys, missing-mount diagnostics, foreground service startup/SIGTERM shutdown, DNS address reload after atomic replacement, `NET_RAW` removal, and Quadlet generator dry-run.

Not validated: rootful RHEL 9 apply, Quadlet lifecycle and reboot, SELinux socket access, Cockpit Podman operations through the rootful socket, SSH ProxyJump and destination authentication, runtime DNS address replacement, network isolation, rollback on the target host, or the minimum capabilities. The available environment is Debian 13 and has no authorized isolated RHEL 9 host. These remain release gates; do not claim RHEL 9 acceptance until they pass on a disposable RHEL 9 system.