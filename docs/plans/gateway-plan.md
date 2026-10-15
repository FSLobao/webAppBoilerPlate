# Gateway Bootstrap Plan

**Status:** Gateway implementation is in progress; unrestricted routed remote access is not implemented. Host acceptance remains pending.
**Scope:** Shared Gateway bootstrap on RHEL 9.8 with rootful Podman 5.8.2
**Acceptance target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux disabled. Disabling SELinux removes mandatory access controls; preflight must verify the requested state and must not change host security settings.
**Deployment target:** Isolated test host only during implementation; no live-host deployment is authorized by this plan.

## 1. Goal

Implement a reproducible bootstrap for the shared Gateway. Run host deployment scripts only on RHEL 9.8 with rootful Podman 5.8.2. Keep host deployment and container startup as separate responsibilities. Use a maintained, efficient Linux distribution for the Gateway and application images, preferably Debian or Alpine. Select container bases independently from the host distribution.

The deployment must provide authorized remote developers symmetric, routed Layer 3 access to every configured container network. Developers may initiate traffic using any IP protocol and port. The deployment must also allow containers to initiate traffic to externally routable destinations through normal rootful Podman host egress, using host masquerading. Neither path may forward traffic between application networks. The deployment must remain repeatable without deleting application data, volumes, secrets, SSH host keys, or unrelated Podman resources. It must fail validation before changing the host or the running gateway.

## 2. Scope

In scope:

- A Bash host deployment script for an authorized infrastructure operator.
- A Quadlet-managed, rootful Podman Gateway container.
- A Debian image built from a repository `Containerfile`.
- A separate Bash startup/validation script inside the image.
- Versioned declarations for application networks, CIDRs, and development DNS mappings.
- Runtime DNS generation from current container addresses.
- Unrestricted routed remote access from developer clients to every configured container network through OpenVPN client and OpenSSH TUN interfaces, with both interfaces allowed concurrently.
- Unrestricted container-initiated egress to externally routable destinations through the host's normal Podman egress path.
- Runtime DNS generation from current container addresses and instructions for remote clients to query DNSMasq through a tunnel.
- Client setup documentation for OpenVPN and OpenSSH TUN, including routes and DNS configuration.
- Bootstrap of individual public SSH keys without copying private keys.
- Cockpit and cockpit-podman access through the local rootful Podman Unix socket.
- Failure, idempotence, persistence, DNS, SSH, reboot, Cockpit, and RHEL 9 capability validation.

Out of scope:

- Application Gateway implementation or application/backend/database deployment.
- OpenVPN server provisioning or configuration. This project installs and configures only the Gateway's OpenVPN client.
- External firewall, VPN identity policy, corporate authentication, DNS, or TLS policy. External VPN routing and developer-client route distribution remain prerequisites.
- Live-host deployment or changes to a production RHEL host.
- Podman API exposure over TCP.
- `--privileged`, broad host filesystem mounts, or changing the host's SELinux mode during deployment.
- A custom authorization service, secret manager, or automated network watcher.
- Port-specific service exposure, DNAT/SNAT, or per-protocol/per-port access rules for developer-to-container traffic. Host masquerading is allowed for ordinary container egress.

## 3. Architecture Contract

Implementation must preserve these invariants:

- One shared Gateway serves multiple isolated application networks.
- The shared Gateway has one Podman interface for every network in the global top-level `networks` array in `config/host_config.json`, including database networks. It has no per-service network allowlist.
- Each application retains its own Podman network. No global network joins applications.
- The Gateway is not the Application Gateway and does not serve user traffic.
- DNSMasq runs in the Gateway and returns current container addresses for declared names. Remote clients can use the Gateway DNS service through either tunnel interface and must have routes to every configured Podman CIDR.
- The Gateway routes developer-initiated traffic across tunnel interfaces to every configured container network without protocol or port filtering. Stateful replies are allowed. New container-initiated egress uses normal Podman host egress and host masquerading.
- The shared Gateway can reach every network-attached service, including PostgreSQL. Remote developers also gain access to every configured network and service, including database services; the external VPN and security perimeter control who can connect.
- The Gateway forwards traffic between each tunnel interface and each configured application network, but never between application networks. Containers do not gain direct peer connectivity merely because the Gateway attaches to both.
- The OpenVPN client and OpenSSH TUN interface can operate concurrently. The OpenVPN profile is an external file referenced from JSON and mounted read-only. No OpenVPN server configuration is part of this project.
- Full-network SSH access uses OpenSSH TUN (`ssh -w`), not local, remote, or dynamic port forwarding. Port-forwarding modes do not satisfy unrestricted protocol access.
- Developer-to-container access preserves client source addresses and uses no DNAT or SNAT. Ordinary container egress may use Podman's host masquerading; external services see the host's egress address.
- SSH forwarding does not replace destination authentication. Developers authenticate to the target container with their individual keys. Access to the gateway itself has separate authentication.
- Podman access uses a local Unix socket. No Podman API listener is exposed over TCP.
- Secrets and private keys stay outside Git and outside the image. Secret mounts are read-only and limited to consumers that need them.
- Rootful Podman and Quadlet manage the container lifecycle. The gateway does not require `--privileged`.
- Normal deployment must not prune containers, images, networks, volumes, secrets, or data.

### 3.1 Explicit security tension

Cockpit administration of rootful Podman through its Unix socket grants broad control over rootful containers. Podman's rootful socket does not provide a narrow per-operation authorization policy. A read-only bind mount does not make API operations read-only.

The infrastructure owner's approval is recorded in [gateway-implementation.md](gateway-implementation.md). The requester selected SELinux disabled for this host. This removes SELinux mandatory access controls and weakens host confinement. Preflight must verify that the host is already disabled; deployment must not change its security mode. Do not resolve socket issues by exposing the API over TCP or using `--privileged`.

### 3.2 Routed remote-access contract

OpenVPN and SSH TUN are client-to-Gateway transports. The Gateway forwards packets between each active tunnel and every configured application network. It allows all IP protocols and ports from remote clients to configured container CIDRs, plus stateful reply traffic. It denies forwarding between application networks. New container-initiated egress uses the host's normal Podman egress path and masquerading.

The Gateway must preserve remote client source addresses and provide symmetric return routes. Discover client routes from the active OpenVPN profile/session and SSH TUN sessions. Before mutation, compare discovered routes and tunnel addresses with every configured Podman CIDR; reject overlaps. If the active tunnel does not expose enough route information to install symmetric return routes, fail preflight and keep acceptance blocked. The host must route discovered client ranges through the Gateway interface on each application network. The Gateway must route every application CIDR through each active tunnel. The external VPN must route application CIDRs to the Gateway and deliver remote-client traffic to that client. External route provisioning remains an infrastructure prerequisite.

SSH TUN uses OpenSSH point-to-point tunnel devices (`ssh -w`) and provides routed IP connectivity. It requires a dedicated tunnel account, a restricted `PermitTunnel` policy, TUN device access, session address assignment, and client routes. ProxyJump and `ssh -L`, `ssh -R`, and `ssh -D` remain TCP-only access paths; they do not provide general routed access or client DNS. Support both TUN and ProxyJump.

The OpenVPN profile path is declared in `config/host_config.json` and refers to a root-managed, private file outside Git, uniquely assigned to this Gateway. The profile is mounted read-only. OpenVPN's standard inline certificate/key blocks may appear inside that profile. Do not assume a Quadlet `InlineFile` directive; use a supported file mount and verify it on the qualification host.

DNSMasq must listen on each configured Gateway network address and active tunnel address. Containers use their Gateway network address for DNS; DNSMasq forwards other queries to the host's configured upstream resolvers. Remote VPN and SSH TUN clients use split-DNS rules for configured container domains. ProxyJump alone cannot carry DNS queries. If split DNS is unavailable, static client `hosts` entries are a limited fallback and require refresh after container recreation.

### 3.3 Alternatives considered

- **Host-managed OpenVPN client:** Potentially simpler than running OpenVPN inside the Gateway because it avoids passing `/dev/net/tun` and `CAP_NET_ADMIN` into the container. It requires host-level VPN credentials and routes, increasing host-level trust and changing the deployment boundary. This is not the selected design.
- **Existing site-to-site or developer VPN routes:** Simplest if infrastructure can route developer CIDRs and every Podman CIDR directly through the host. It avoids an OpenVPN process in the Gateway, but depends on external route and firewall changes. This is not the selected design.
- **WireGuard client:** A smaller tunnel implementation may reduce Gateway package and process complexity. It requires a compatible external server and a new server-side decision, so it is not selected.
- **SSH local, remote, or dynamic forwarding:** Easier for individual TCP services, but cannot provide unrestricted IP protocol and port access. It does not meet this plan's acceptance target. SSH TUN (`ssh -w`) remains the supported SSH option.


## 4. Proposed Repository Artifacts

Keep source-controlled inputs separate from generated host state:

```text
config/host_config.json
gateway/development/Containerfile
gateway/development/startup.sh
gateway/development/systemd/
deploy/quadlet/gateway.container
scripts/deploy-gateway.sh
scripts/host-preflight.sh
```

Use existing repository conventions if implementation reveals an established location. The generic
host preflight reads declared host networks and containers without requiring gateway credentials.
Gateway deployment adds its RHEL, credential, systemd, and Quadlet requirements. Do not commit
generated DNS files, host-specific Quadlet output, SSH private keys, secrets, or runtime state.

The host deployment script owns host prerequisites, image build, network checks, generated Quadlet installation, DNS record generation, service activation, and health verification. The container startup script owns in-container validation and service startup only. Neither script should source the other's configuration as executable shell.

## 5. Versioned Configuration Contract

Use JSON for the versioned configuration and `jq` for structured parsing. Do not parse nested configuration with `grep`, `sed`, `eval`, or shell word splitting. Declare `jq` as a host prerequisite and fail during read-only preflight if it is unavailable.

The host schema should contain:

- `schema_version`, initially `1`.
- A required `networks` array containing every Podman network on the host, with exact name, expected CIDR, and non-overlapping Gateway interface address. This is the global inventory; the Development Gateway attaches to every listed network.
- Optional service-specific sections such as `gateway`, `application_gateway`, and per-application declarations. Feature sections are optional and backward-compatible under required `schema_version: 1`.
- An optional array of containers and their expected networks for generic host preflight checks.
- An optional `gateway` section with identity, management bind address/ports, and tunnel settings. Do not use it to select only some top-level networks.
- Optional `gateway.remote_access.openvpn` settings with an enable flag and a host path to the external, private client profile. Discover pushed routes and client ranges from the active tunnel.
- Optional `gateway.remote_access.ssh_tun` settings with an enable flag, a configured tunnel address pool, and dedicated-account policy. Discover active session addresses at runtime.
- Both tunnel interfaces may be enabled concurrently. Validate discovered routes and addresses against configured Podman CIDRs before installing state.
- Optional DNS records that map names to a target container and declared network. DNS records contain no protocol or port exposure declarations.
- Host paths for public `authorized_keys` files, including one file per application container. Private-key paths are forbidden.

Generic preflight always validates the complete top-level network inventory. It runs Gateway-specific checks only when the `gateway` section is enabled, and applies only the selected services. A service section must not silently install host packages or weaken host security policy.

Illustrative shape; finalize field names and requiredness before implementation:

```json
{
  "schema_version": 1,
  "gateway": {
    "name": "gateway",
    "bind_address": "192.0.2.10",
    "ssh_port": 2222,
    "cockpit_port": 9090,
    "remote_access": {
      "openvpn": {
        "enabled": true,
        "profile_file": "/etc/gateway/openvpn/client.ovpn"
      },
      "ssh_tun": {
        "enabled": true,
        "address_pool": "10.253.0.0/24"
      }
    }
  },
  "networks": [
    {
      "name": "project-a-net",
      "subnet": "10.89.1.0/24",
      "gateway_address": "10.89.1.2"
    }
  ],
  "containers": [
    { "name": "project-a-backend", "networks": ["project-a-net"] }
  ],
  "dns_records": [
    {
      "name": "backend.project-a.dev.internal",
      "container": "project-a-backend",
      "network": "project-a-net"
    }
  ]
}
```
Public SSH keys must be supplied from root-managed host files outside Git, separated by Gateway login and application destination. Each application container may load multiple public keys from its configured `authorized_keys` file into a dedicated non-root destination account. Mount the file read-only. Deployment validates file ownership/mode and key syntax, then consumes or renders only public keys. Private developer keys remain on developer workstations. Host audit records changes to these files; PAM and operator-session controls are managed outside this host deployment and are not revalidated by it.

For each path, document owner, mode, mount mode, and backup/restore responsibility. SELinux is expected to be disabled by host policy; deployment must not change that policy.

`schema_version` is required and remains `1`; optional service sections and feature fields must remain backward-compatible. Validation must reject unsupported schema versions, duplicate network names, duplicate DNS names, malformed names/CIDRs, overlapping configured Podman networks, runtime tunnel routes or addresses that overlap those networks, records referencing undeclared networks, and DNS records for a container outside the declared network. Existing Podman networks must match their declared subnet; never silently recreate or mutate a mismatched network. If OpenVPN is enabled, validate the external profile path, ownership, mode, client configuration, and discoverable routes before mutation.

The configuration contains logical identities, not permanent container IPs. The deployment queries Podman for each target's current address on the declared network every time it generates DNS. An absent declared target is a hard preflight error. Read-only `--check` reports stopped targets without starting them; `--apply` asks before starting each stopped target, then reruns preflight. If a later apply step fails, restore the stopped state of targets started by that apply. Never publish a stale address.

DNS A/AAAA records point directly to current target addresses on their declared container networks. Each network's configured Gateway address serves DNS to attached containers and tunnel clients. Tunnel clients must have routes to those network CIDRs. Developer-to-container access uses no service port mapping, DNAT, or SNAT. Developers with tunnel access can reach every service on every configured network, including databases.

## 6. Host and Container Responsibilities

### 6.1 Host deployment: Bash plus Quadlet

The host script should:

1. Require rootful Podman access and qualify the configured RHEL 9.8 / Podman 5.8.2 / Quadlet target. Verify package provenance and compatibility; do not install packages or alter host security policy implicitly.
2. Run a read-only preflight before any host mutation. Validate configuration, tools, paths, permissions, management-port availability, tunnel CIDRs and routes, existing network definitions, OpenVPN profile and key inputs, TUN-device availability, Podman socket availability, SELinux mode, and current service state.
3. Offer a validation-only mode that performs no writes, image builds, network changes, service restarts, or file creation. Any invalid input or unmet hard prerequisite must exit non-zero before mutation.
4. Build the Debian image from the checked-out repository `Containerfile`, with an explicitly versioned/pinned base image and reproducible package inputs. Never bake secrets or public-key data into image layers.
5. Create only missing networks in the global inventory, or verify existing Podman networks match their declared CIDRs. Do not connect application networks to one another.
6. Stage generated DNS, route, firewall, and Quadlet state in temporary files on the same filesystem, validate them, and install them atomically. Keep generated host state in dedicated paths, separate from operator-managed secrets and data.
7. Install/update the rootful Quadlet definition under the supported system location, reload systemd, and enable/start the generated service. Avoid restarting or recreating the gateway when desired configuration and image are unchanged.
8. Attach the Gateway to every network in the global `networks` array. Do not create links or routing between those networks; never delete an application network as part of normal deployment.
9. Mount the Podman Unix socket only at the path Cockpit Podman actually uses. Do not claim that a read-only socket mount restricts API authority. Verify SELinux is disabled; do not change its state or relabel the host socket.
10. Start and supervise each enabled tunnel interface. Configure forwarding and symmetric routes between each active tunnel and every declared application network, without forwarding between application networks. The application deployment handoff must refresh DNS after service readiness; no background watcher is in scope.
11. Verify tunnel readiness, remote DNS answers, protocol- and port-independent routing, source-address preservation, symmetric replies, host-masqueraded container egress, SSH target authentication, Cockpit/Podman visibility, one interface per configured network, and service state. On failed checks, restore prior Quadlet, DNS, route, and firewall state where feasible.
12. Print a concise result with changed resources, pending DNS targets, service status, and recovery instructions. Never print secret contents.

The deployment must not use `podman system prune`, `podman volume prune`, blanket `rm -rf`, or equivalent cleanup. It must not overwrite existing host keys, secret files, application data, or unrelated Quadlet units.

### 6.2 Container startup: Bash inside Debian image

The startup script should:

- Validate required read-only mounts and configuration before starting services.
- Fail with actionable diagnostics when a required file, key, directory, or permission is invalid.
- Start and supervise SSH, DNSMasq, Cockpit, and any enabled OpenVPN client process using a process model supported by the chosen Debian packages. Prefer the minimum mechanism compatible with Cockpit's service activation; do not add a custom supervisor without demonstrated need.
- Validate the mounted OpenVPN profile before connecting. Apply only validated forwarding policy and routes; do not apply DNAT or SNAT.
- Run as PID 1 or hand off to the selected init/process manager with `exec`, so signals and shutdown reach child services.
- Keep generated DNS configuration and persistent SSH host keys outside the image. Preserve host identity across container replacement using a host-managed persistent secret path with restrictive permissions.
- Mount the external OpenVPN client profile read-only when OpenVPN is enabled. Do not copy profile contents into the image or versioned JSON.
- Support OpenSSH point-to-point TUN sessions only for a dedicated tunnel account. Keep tunnel setup separate from gateway login and application destination authentication.
- Enable forwarding between configured tunnel interfaces and declared application networks without forwarding between application networks. Preserve developer source addresses and allow stateful replies. Allow new container egress through the host's normal Podman route and masquerading.
- Never generate replacement host keys over existing keys during a rerun.
- Avoid startup-time mutation of application networks or host Podman state.

Confirm whether the image needs systemd as PID 1 for Cockpit and whether Quadlet/Podman on supported RHEL 9 releases handles that mode without `--privileged`. Record the tested options and exact capability set rather than assuming them.

## 7. Host State, Secrets, and Persistence

Standardize host paths during implementation. Keep these categories separate:

- Versioned source: scripts, Containerfile, Quadlet source, and JSON configuration in Git.
- Generated state: DNSMasq records and installed Quadlet artifacts, replaceable from source.
- Persistent identity: SSH host private keys, created once with restrictive ownership and permissions, never committed, and preserved on reruns.
- External credentials: any required secret files and developer public-key inputs, stored outside Git. Mount only to their consumers and read-only where applicable.
- OpenVPN client profile: a root-managed file outside Git, referenced by `gateway.remote_access.openvpn.profile_file` and mounted read-only. If the profile contains inline certificates or private keys, protect the whole profile as secret material.
- Application data: owned by application/database deployment, never removed or rewritten by gateway deployment.

For each path, document owner, mode, mount mode, and backup/restore responsibility. A missing secret or invalid permission must fail before service changes. Existing secret contents must remain byte-for-byte unchanged after repeated deployment.

## 8. Implementation Phases

### Phase 0: Resolve prerequisites and security gate

- Confirm the infrastructure owner's acceptance of the rootful Podman socket authority described in section 3.1.
- Record the requester's approval for unrestricted protocol/port access to every configured network, including databases. Authentication remains service-owned; external perimeter controls are assumed.
- Record the qualification baseline as RHEL 9.8, rootful Podman 5.8.2, Quadlet, SELinux disabled, required host packages, and image base digest. Verify the installed build and repository/vendor support without changing host security settings.
- Confirm that active OpenVPN and SSH TUN sessions expose routes and addresses needed for symmetric replies. The private OpenVPN profile and server routes remain externally managed.
- Confirm whether the OpenVPN profile uses inline certificate/key blocks, SSH TUN client address allocation, tunnel account policy, management bind addresses/ports, host key storage, public-key input format, and whether Cockpit is reachable only through the external management perimeter.
- Confirm the in-container service/process model and initial capability hypothesis.
- Stop implementation if a decision requires changing an architecture invariant; document the conflict for explicit approval first.

### Phase 1: Configuration and read-only preflight

- Add the versioned JSON schema and representative non-secret configuration.
- Implement strict schema/value validation and human-readable errors.
- Add shared read-only checks for the RHEL 9.8 / Podman 5.8.2 baseline, Quadlet, `jq`, source tree, every declared network/CIDR, disabled SELinux state, enabled tunnel profiles, discovered tunnel routes, TUN device, routes, Podman socket, and host-wide prerequisites. Run service-specific checks only for enabled config sections.
- Prove invalid configuration, missing required files, occupied ports, and mismatched existing networks fail before any state changes.

### Phase 2: Debian image and container startup

- Add the repository-built Debian image with pinned base and explicit package list: OpenSSH, DNSMasq, Cockpit, cockpit-podman, `iproute2`, and only required network diagnostics. Install the OpenVPN client when enabled.
- Add startup validation and the selected service-management units/scripts.
- Keep the OpenVPN profile, public-key, and DNS inputs as read-only runtime mounts; keep private host keys in persistent host storage.
- Build and run the image in the authorized disposable test environment with SELinux disabled and TUN support where available.
- Prove startup, shutdown, signal handling, tunnel failure reporting, DNS service, and replacement without loss of host identity.

### Phase 3: Quadlet lifecycle and network attachment

- Add the rootful Quadlet container definition and any network units needed for deterministic boot ordering.
- Use Bash to render/install only configuration that cannot be expressed safely as a static Quadlet file.
- Create or verify declared networks without joining application networks together.
- Enable the generated systemd service and prove a second deployment produces no unnecessary container replacement or service restart.
- Install host return routes for active tunnel client ranges through the Gateway interface on every configured application network. Preserve existing host routes and roll back only Gateway-owned routes.
- Prove adding/removing a declared gateway attachment does not delete the underlying application network or volume.
- Prove every configured network receives a Gateway interface, while removing a network from the global inventory never deletes the underlying network or volume.

### Phase 4: Routed developer access and DNS

- Resolve each configured target address with Podman network inspection, scoped to its declared network.
- Verify one Gateway interface exists on every network in the global top-level `networks` inventory. Never bridge application networks together.
- Connect the OpenVPN client to the externally managed server using the configured read-only profile. Do not change or install OpenVPN server configuration.
- Support OpenSSH TUN (`ssh -w`) concurrently with OpenVPN. Enable it only for the dedicated tunnel account and configure per-client tunnel addresses and routes. Do not treat `ssh -L`, `ssh -R`, or `ssh -D` as a substitute.
- Enable forwarding from each active tunnel to every configured application network and back. Permit any IP protocol and port for developer-initiated flows and their replies. Do not add protocol/port filters, DNAT, or SNAT on this path. Do not forward between application networks.
- Discover active client routes and session addresses, reject overlap with configured Podman CIDRs, and configure host return routes through the Gateway interface on each application network. Configure Gateway routes for every application CIDR through each active tunnel. Preserve developer source addresses.
- Require external VPN routing to deliver traffic for all application CIDRs to the Gateway client. Stop acceptance if required external routes are absent.
- Permit new container-initiated egress to externally routable destinations through the normal Podman host route and masquerading. Verify external targets see the host egress address; do not route ordinary egress through the Development Gateway VPN.
- Generate DNSMasq records from current target addresses. Listen for container and remote DNS queries on configured Gateway network and tunnel addresses. Configure attached containers to use Gateway DNS and clients to use split DNS for declared container domains.
- Validate the candidate DNS, route, and forwarding state before atomic installation. Preserve the last known-good state when validation fails.
- Install and replace only Gateway-owned routes and forwarding rules. Reload DNSMasq and apply tunnel routes only when generated content changes.
- Test from remote clients on OpenVPN and SSH TUN, including concurrent use. Resolve declared names through split DNS, connect using arbitrary ports and protocols, and verify source-address preservation and replies. Test ProxyJump separately as TCP-only destination SSH. From containers, test unrestricted external egress and confirm destinations see the host egress address. Inspect forwarding rules for app-to-app isolation and absence of L4 filters on developer access. Recreate a target and verify DNS updates without changing network routes.

### Phase 5: SSH, Cockpit, and socket integration

- Load gateway and destination public keys from separate root-managed host files outside Git. Validate permissions and key format; make consuming mounts read-only. Application deployment owns destination account provisioning and key revocation.
- Configure SSH forwarding so a VS Code Remote-SSH/ProxyJump path reaches the destination and destination authentication remains authoritative.
- Configure OpenSSH TUN (`ssh -w`) for a dedicated tunnel account, separate from gateway login and destination accounts. Document client tunnel setup, interface addressing, routes, and DNS.
- Verify gateway authentication does not substitute for or bypass target authentication.
- Configure Cockpit and cockpit-podman against the local rootful Podman Unix socket.
- Verify the gateway can see/manage intended rootful containers while Podman has no TCP listener and SELinux remains disabled.
- Document the socket authority, exposed management ports, external perimeter assumptions, and operator-only recovery path.

### Phase 6: RHEL 9.8 / Podman 5.8.2 acceptance and handover

- Run the complete matrix in section 9 on the authorized disposable RHEL 9.8 system using rootful Podman 5.8.2 and SELinux disabled. Do not use a live host.
- Record OS, Podman, Quadlet, kernel, SELinux, and capability results with test commands and expected output.
- Fix failures within the validated scope. If a fix requires broader privileges or changes an invariant, stop and obtain architecture approval.
- Document install, update, reboot, DNS refresh after app redeploy, status, logs, rollback, and explicit decommission steps.

## 9. Acceptance and Validation Matrix

| Area | Test | Pass condition |
|---|---|---|
| Failure before change | Snapshot service state, Quadlet files, DNS files, network definitions, volume IDs, key/secret hashes, and data sentinels. Run malformed config, duplicate names, overlapping CIDRs, missing required keys, unavailable tools, occupied ports, and incompatible existing networks. | Each hard validation failure exits non-zero before modifying host files, networks, containers, service state, volume IDs, secrets, keys, or sentinels. |
| Validation-only mode | Run the documented check mode against valid and invalid configurations. | It performs no writes, builds, network changes, restarts, or file creation. |
| Idempotence | Apply the same valid configuration twice. Compare container ID/start time, unit content, generated DNS content, network IDs, volume IDs, key/secret hashes, and data sentinels. | Second apply makes no unnecessary changes or restart. No persistent content changes. |
| Persistence | Seed a database/application volume and external secret/key files. Rebuild/recreate the gateway and rerun deployment. | Volume identity/data, secret bytes, SSH host keys, and permissions remain intact. Gateway image replacement does not own or delete app data. |
| DNS initial state | Query each declared name from an approved remote client using Gateway DNS. Query an undeclared database name. | DNS returns the current target address on its declared network. The client has routes to every declared container CIDR. Undeclared names are absent. |
| DNS refresh | Recreate a DNS target with a different address and run the documented refresh. Query DNS and connect before and after. | DNS changes to the new target address. Routes remain valid because they cover the configured network CIDR. Invalid candidates leave the last good DNS state active. |
| Gateway all-network access | Inspect one Gateway interface per entry in the top-level network inventory. Test connectivity to SSH, HTTP, database, and other declared services from the Gateway. | Gateway can reach every configured Podman network and service. It is a trusted administrative component, not an isolation boundary. |
| Network isolation | Attempt direct app-to-app traffic without an explicit connection, excluding traffic initiated by the multi-homed Gateway. | Application networks remain separate and do not gain direct peer connectivity merely because the Gateway attaches to both. |
| Routed remote access | From clients on OpenVPN and SSH TUN, reach services on every configured network using varied ports and IP protocols, including TCP, UDP, and ICMP. Inspect forwarding rules. | Any IP protocol and port can pass from developer clients to all configured container CIDRs. Reply traffic works. Rules contain no L4 protocol or port matches. Source addresses remain unchanged. |
| Flow direction | From each remote transport, initiate flows to containers. Test replies for supported IP protocols. From containers, initiate flows to external targets. | Remote-initiated flows preserve source addresses and receive replies. Container egress works through host masquerading; external targets see the host address. |
| Route symmetry | Inspect routes on Gateway, host, OpenVPN server, developer clients, and target container return paths. Trace packets in both directions. | Routes discovered from active tunnels reach every container network through the Gateway; replies return through the same tunnel path. No SNAT or DNAT is present on developer access. |
| Application-network isolation | Attempt direct forwarding between two application networks through the Gateway. | Gateway does not forward application-to-application traffic. Remote developer clients retain access to every configured network. |
| SSH forwarding | Connect using the documented VS Code Remote-SSH/ProxyJump configuration. Use separate gateway and destination keys. Attempt access with a valid gateway key but invalid destination key, then with valid destination credentials. | Forwarding succeeds. Target accepts/rejects based on its own credentials. Private keys remain on the developer workstation. Gateway public-key setup is distinct. |
| SSH TUN policy | Establish an `ssh -w` tunnel with the dedicated account. Attempt tunnel setup with an ordinary gateway account and inspect effective `sshd` settings. | Only the dedicated account can create TUN sessions. Client routes and DNS work. No unintended agent, tunnel, or gateway-management exposure is introduced. |
| Reboot recovery | Reboot the disposable RHEL 9.8 host with Podman 5.8.2, declared networks, Quadlet, DNS, and OpenVPN enabled. Reconnect SSH TUN clients. | Quadlet restores every declared Gateway interface. OpenVPN reconnects and restores only validated routes. SSH TUN clients can reconnect. DNS works after tunnel recovery. Persistent keys and application data survive. |
| Cockpit Podman access | Through Cockpit, inspect and perform a controlled lifecycle operation on a disposable rootful test container. Inspect host listening sockets and socket mounts. | cockpit-podman accesses the intended rootful Podman service through the Unix socket. No Podman API listens on TCP. Socket authority is documented. |
| Capabilities | On RHEL 9.8 with rootful Podman 5.8.2, test each required feature with a minimal capability baseline, then add candidates individually. Inspect effective capabilities and test routing, TUN, forwarding, diagnostics, low ports, systemd, SSH, and Cockpit. | Exact required capabilities and device access are recorded. No `--privileged`, `CAP_SYS_ADMIN`, or other broad capability remains without evidence and explicit approval. Removing a required capability causes a specific test failure. |
| SELinux | Verify host SELinux state before lifecycle, socket, tunnel-device, profile-mount, route, and DNS tests. | Host reports SELinux disabled as explicitly required. Deployment does not change SELinux state. Record that this removes SELinux mandatory access controls. |
| Quadlet behavior | Validate generated systemd units, dependencies, start/stop/restart behavior, and reboot enablement on RHEL 9.8 / Podman 5.8.2. | Quadlet owns the Gateway lifecycle; deployment does not leave unmanaged duplicate containers or stale units. |

For the capability test, treat `CAP_NET_ADMIN` and `/dev/net/tun` access as candidates for tunnel and routing support, not as assumed final answers. Test `CAP_NET_RAW` only for diagnostics that require it. Test whether Cockpit/systemd needs additional capabilities on the actual supported Podman version. Do not grant capabilities speculatively.

## 10. Operational and Failure Behavior

- Validation failures must happen before mutation. The script must identify the failing input and the resource it would have affected.
- Build or candidate-config failures must leave the active Quadlet, DNS config, and running gateway unchanged.
- Install generated files atomically. Keep the previous known-good copies until the new service passes health checks.
- If activation fails, restore the previous generated files and service definition where feasible, then report both the original and rollback errors.
- Never remove volumes, secret files, host keys, application data, unrelated containers, or unrelated systemd/Quadlet units during apply or rollback.
- Normal apply may create missing declared networks and attach the gateway. It must not delete networks. Network decommissioning and persistent-data deletion require separate, explicit operator procedures.
- A configured DNS target that is absent is a hard preflight error. Read-only `--check` must not start stopped targets. `--apply` may start a stopped target only after operator confirmation and must restore its prior stopped state if deployment fails. Never retain or publish a stale IP as a fallback.
- Keep logs free of secret content. Do not put secret values in command-line arguments, generated unit files, build arguments, or image history.
- Report partial additive changes, such as a newly created network, if later activation fails. Do not present rollback as complete when host state remains changed.

## 11. Remaining RHEL 9.8 / Podman 5.8.2 Acceptance Gates

Implementation decisions and locally validated behavior are recorded in [gateway-implementation.md](gateway-implementation.md). The following questions remain open; answer them with evidence from a disposable RHEL 9.8 host using rootful Podman 5.8.2 before claiming acceptance:

1. Does the RHEL 9.8 / Podman 5.8.2 target pass vendor/package support and lifecycle tests? Record the exact kernel, Quadlet generator, package source, and SELinux state.
2. Can Cockpit access the approved rootful Podman socket on the target with SELinux disabled?
3. Can the Gateway run OpenVPN and SSH TUN concurrently with the documented TUN device and minimum capabilities?
4. Do active tunnel sessions expose enough routes and addresses for conflict checks and symmetric return routing?
5. Do external VPN routes deliver traffic for every configured application CIDR to the Gateway client?
6. Does ordinary Podman host egress support unrestricted container egress with the expected host masquerading?
7. Do tunnel recovery, split DNS, DNS refresh after container recreation, failure rollback, and health checks pass on the target platform?

Do not treat resolved configuration details, such as stopped-target handling or key-file paths, as open decisions. Do not claim a test passed unless it ran on the stated target.

## 12. Completion Criteria

The bootstrap is ready for review when:

- Host deployment and container startup are separate Bash-owned responsibilities.
- Quadlet controls the rootful Gateway lifecycle on RHEL 9.8 with rootful Podman 5.8.2.
- The Debian image builds from repository sources and contains no secrets.
- Network and DNS declarations come from versioned JSON configuration.
- OpenVPN client and SSH TUN can operate concurrently. The OpenVPN profile is referenced from JSON and mounted read-only from outside Git.
- Every configured developer CIDR has routed access to every configured container CIDR through the Gateway, for any IP protocol and port.
- Developer-initiated traffic receives symmetric replies with source addresses preserved. Container egress reaches externally routable destinations through host masquerading.
- Application networks remain isolated from each other; the Gateway does not forward between them.
- DNSMasq resolves declared names to current container addresses, and clients can query it through either tunnel.
- No DNAT, SNAT, or per-service port/protocol allowlist is used for remote developer access.
- Invalid input fails before host or service changes.
- Repeated deployment preserves application data, secrets, SSH host identity, and volumes.
- SSH forwarding preserves destination authentication.
- Cockpit Podman works over the Unix socket with no TCP API and no `--privileged`.
- Reboot recovery and exact required capabilities are proven on a disposable RHEL 9.8 / Podman 5.8.2 host.
- Tunnel routing, full-protocol forwarding, DNS, Quadlet lifecycle, and the requested SELinux-disabled host state are proven on disposable RHEL 9.8 with rootful Podman 5.8.2.
- Security tension, open decisions, test environment, and operator recovery steps are recorded.

## 13. Current Status

The Gateway implementation remains in progress, and no RHEL 9.8 / Podman 5.8.2 host acceptance is claimed. Routed remote access is not implemented; the Gateway is incomplete until clients reach every configured container network over OpenVPN and SSH TUN with symmetric replies and no port or protocol restrictions. OpenVPN routes remain external prerequisites. Tunnel support, exact capabilities, route discovery, host egress, split DNS, DNS refresh, reboot recovery, and end-to-end SSH remain acceptance gates. The attached disposable host matches RHEL 9.8 / rootful Podman 5.8.2 but reports SELinux `Enforcing`; the target requires `Disabled`. Do not change host security settings. Use [gateway-implementation.md](gateway-implementation.md) for the operator workflow and validation record. Do not deploy to a live host.