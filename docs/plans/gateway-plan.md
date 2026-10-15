# Gateway Bootstrap Plan

**Status:** Gateway implementation is in progress; NAT-based remote service forwarding is not implemented. Host acceptance remains pending.
**Scope:** Shared Gateway bootstrap on RHEL 9.8 with rootful Podman 5.8.2
**Acceptance target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux enforcing. Verify the installed package source and support status on the disposable target host.
**Deployment target:** Isolated test host only during implementation; no live-host deployment is authorized by this plan.

## 1. Goal

Implement a reproducible bootstrap for the shared Gateway. Run host deployment scripts only on RHEL 9.8 with rootful Podman 5.8.2. Keep host deployment and container startup as separate responsibilities. Use a maintained, efficient Linux distribution for the Gateway and application images, preferably Debian or Alpine. Select container bases independently from the host distribution.

The deployment must be repeatable without deleting application data, volumes, secrets, SSH host keys, or unrelated Podman resources. It must fail validation before changing the host or the running gateway.

## 2. Scope

In scope:

- A Bash host deployment script for an authorized infrastructure operator.
- A Quadlet-managed, rootful Podman Gateway container.
- A Debian image built from a repository `Containerfile`.
- A separate Bash startup/validation script inside the image.
- Versioned declarations for application networks, CIDRs, and development DNS mappings.
- Runtime DNS generation from current container addresses.
- NAT-based remote TCP access to explicitly declared container services, with DNSMasq records resolving to the reachable Gateway address.
- Bootstrap of individual public SSH keys without copying private keys.
- Cockpit and cockpit-podman access through the local rootful Podman Unix socket.
- Failure, idempotence, persistence, DNS, SSH, reboot, Cockpit, and RHEL 9 capability validation.

Out of scope:

- Application Gateway implementation or application/backend/database deployment.
- External firewall, VPN, corporate authentication, DNS, or TLS policy.
- Live-host deployment or changes to a production RHEL host.
- Podman API exposure over TCP.
- `--privileged`, broad host filesystem mounts, or disabling SELinux.
- A custom authorization service, secret manager, or automated network watcher.

## 3. Architecture Contract

Implementation must preserve these invariants:

- One shared Gateway serves multiple isolated application networks.
- The shared Gateway has one Podman interface for every network in the global top-level `networks` array in `config/host_config.json`, including database networks. It has no per-service network allowlist.
- Each application retains its own Podman network. No global network joins applications.
- The Gateway is not the Application Gateway and does not serve user traffic.
- DNSMasq runs in the Gateway. Deployment generates remote-access records for the reachable Gateway address and NAT target mappings from current container addresses. Direct container-address records are valid only when clients have routes to those Podman CIDRs.
- Published addresses and ports are defined in JSON. A configured remote endpoint is active desired state; there is no separate per-service approval workflow. The external security perimeter controls who can reach it.
- DNS records and remote ports exist only when declared in JSON; the shared Gateway itself can reach every network-attached service, including PostgreSQL. The Application Gateway does not publish PostgreSQL by default.
- SSH forwarding does not replace destination authentication. Developers authenticate to the target container with their individual keys. Access to the gateway itself has separate authentication.
- Podman access uses a local Unix socket. No Podman API listener is exposed over TCP.
- Secrets and private keys stay outside Git and outside the image. Secret mounts are read-only and limited to consumers that need them.
- Rootful Podman and Quadlet manage the container lifecycle. The gateway does not require `--privileged`.
- Normal deployment must not prune containers, images, networks, volumes, secrets, or data.

### 3.1 Explicit security tension

Cockpit administration of rootful Podman through its Unix socket grants broad control over rootful containers. Podman's rootful socket does not provide a narrow per-operation authorization policy. A read-only bind mount does not make API operations read-only.

The infrastructure owner's approval is recorded in [gateway-implementation.md](gateway-implementation.md). RHEL 9 socket access under SELinux enforcing remains an acceptance gate. Do not resolve this tension by exposing the API over TCP, using `--privileged`, or disabling SELinux. This plan does not silently change the architecture.


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
- A required `networks` array containing every Podman network on the host, with exact name and expected CIDR. This is the global inventory; the Development Gateway attaches to every listed network.
- Optional service-specific sections such as `gateway`, `application_gateway`, and per-application declarations. Each section selects networks and defines only that service's ports, paths, credentials, and host checks.
- An optional array of containers and their expected networks for generic host preflight checks.
- An optional `gateway` section with identity, published management and NAT ports, the networks to attach, DNS records, and remote service exposures.
- An optional `gateway` section with identity, bind address, published management/NAT ports, remote-client CIDRs used for return routes, DNS records, and remote service exposures. Do not use it to select only some top-level networks.
- Optional development DNS records and TCP NAT exposure declarations. Each exposure names its protocol, reachable host address/port, target container, target network, target port, and any approved source-CIDR restriction.
- Optional development DNS records and TCP NAT exposure declarations. Each exposure names its protocol, reachable host address/port, target container, target network, and target port. The config itself activates the mapping; external authorization remains at the security perimeter.
- Host paths for public `authorized_keys` files. Private-key paths are forbidden.

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
    "remote_client_cidrs": ["198.51.100.0/24"]
  },
  "networks": [
    {
      "name": "project-a-net",
      "subnet": "10.89.1.0/24"
    }
  ],
  "containers": [
    { "name": "project-a-backend", "networks": ["project-a-net"] }
  ],
  "remote_exposures": [
    {
      "dns_name": "backend.project-a.dev.internal",
      "protocol": "tcp",
      "host_address": "192.0.2.10",
      "host_port": 2223,
      "target_container": "project-a-backend",
      "target_network": "project-a-net",
      "target_port": 22
    }
  ]
}
```
Public SSH keys must be supplied from root-managed host files outside Git, separated by Gateway login and application destination. Deployment validates file ownership/mode and key syntax, then consumes or renders only public keys. Private developer keys remain on developer workstations. Host audit records changes to these files; PAM and operator-session controls are managed outside this host deployment and are not revalidated by it.

For each path, document owner, mode, SELinux label expectations, mount mode, and backup/restore responsibility.

Validation must reject unsupported schema versions, duplicate network names, duplicate DNS names, malformed names/CIDRs, overlapping CIDRs, records referencing undeclared networks, and mappings to a container outside the declared network. Existing Podman networks must match their declared subnet; never silently recreate or mutate a mismatched network.

The configuration contains logical identities, not permanent container IPs. The deployment queries Podman for each target's current address on the declared network every time it generates DNS. An absent declared target is a hard preflight error. Read-only `--check` reports stopped targets without starting them; `--apply` asks before starting each stopped target, then reruns preflight. If a later apply step fails, restore the stopped state of targets started by that apply. Never publish a stale address.

For NAT exposure, the remote DNS A record points to the Gateway's externally reachable address; the declared host port maps to the current target address and container port. DNS does not carry a port, so multiple services on one address require unique host ports unless an HTTP reverse proxy or routed container CIDR is used. Do not publish a database or other internal service without an explicit exposure declaration.

## 6. Host and Container Responsibilities

### 6.1 Host deployment: Bash plus Quadlet

The host script should:

1. Require rootful Podman access and qualify the configured RHEL 9.8 / Podman 5.8.2 / Quadlet target. Verify package provenance and compatibility; do not install packages or alter host security policy implicitly.
2. Run a read-only preflight before any host mutation. Validate configuration, tools, paths, permissions, port availability, existing network definitions, key inputs, Podman socket availability, SELinux mode, and current service state.
3. Offer a validation-only mode that performs no writes, image builds, network changes, service restarts, or file creation. Any invalid input or unmet hard prerequisite must exit non-zero before mutation.
4. Build the Debian image from the checked-out repository `Containerfile`, with an explicitly versioned/pinned base image and reproducible package inputs. Never bake secrets or public-key data into image layers.
5. Create only missing networks in the global inventory, or verify existing Podman networks match their declared CIDRs. Do not connect application networks to one another.
6. Stage generated DNS and Quadlet files in temporary files on the same filesystem, validate them, and install them atomically. Keep generated host state in dedicated paths, separate from operator-managed secrets and data.
7. Install/update the rootful Quadlet definition under the supported system location, reload systemd, and enable/start the generated service. Avoid restarting or recreating the gateway when desired configuration and image are unchanged.
8. Attach the Gateway to every network in the global `networks` array. Do not create links or routing between those networks; never delete an application network as part of normal deployment.
9. Mount the Podman Unix socket only at the path Cockpit Podman actually uses. Do not claim that a read-only socket mount restricts API authority. Do not disable SELinux or relabel the host socket broadly to make access work.
10. Regenerate DNS and NAT targets after an exposed application container is created or recreated. The application deployment handoff must run after service readiness; no background watcher is in scope.
11. Verify readiness, remote DNS answers, NAT port forwarding and return traffic, SSH target authentication, Cockpit/Podman visibility, one interface per configured network, and service state. On failed checks, restore prior Quadlet, DNS, and NAT state where feasible.
12. Print a concise result with changed resources, pending DNS targets, service status, and recovery instructions. Never print secret contents.

The deployment must not use `podman system prune`, `podman volume prune`, blanket `rm -rf`, or equivalent cleanup. It must not overwrite existing host keys, secret files, application data, or unrelated Quadlet units.

### 6.2 Container startup: Bash inside Debian image

The startup script should:

- Validate required read-only mounts and configuration before starting services.
- Fail with actionable diagnostics when a required file, key, directory, or permission is invalid.
- Start and supervise SSH, DNSMasq, and Cockpit using a process model supported by the chosen Debian packages. Prefer the minimum mechanism compatible with Cockpit's service activation; do not add a custom supervisor without demonstrated need.
- Start and supervise SSH, DNSMasq, and Cockpit using a process model supported by the chosen Debian packages. Apply only validated, generated NAT rules before enabling remote service listeners. Prefer the minimum mechanism compatible with Cockpit's service activation; do not add a custom supervisor without demonstrated need.
- Run as PID 1 or hand off to the selected init/process manager with `exec`, so signals and shutdown reach child services.
- Keep generated DNS configuration and persistent SSH host keys outside the image. Preserve host identity across container replacement using a host-managed persistent secret path with restrictive permissions.
- Never generate replacement host keys over existing keys during a rerun.
- Avoid startup-time mutation of application networks or host Podman state.

Confirm whether the image needs systemd as PID 1 for Cockpit and whether Quadlet/Podman on supported RHEL 9 releases handles that mode without `--privileged`. Record the tested options and exact capability set rather than assuming them.

## 7. Host State, Secrets, and Persistence

Standardize host paths during implementation. Keep these categories separate:

- Versioned source: scripts, Containerfile, Quadlet source, and JSON configuration in Git.
- Generated state: DNSMasq records and installed Quadlet artifacts, replaceable from source.
- Persistent identity: SSH host private keys, created once with restrictive ownership and permissions, never committed, and preserved on reruns.
- External credentials: any required secret files and developer public-key inputs, stored outside Git. Mount only to their consumers and read-only where applicable.
- Application data: owned by application/database deployment, never removed or rewritten by gateway deployment.

For each path, document owner, mode, SELinux label expectations, mount mode, and backup/restore responsibility. A missing secret or invalid permission must fail before service changes. Existing secret contents must remain byte-for-byte unchanged after repeated deployment.

## 8. Implementation Phases

### Phase 0: Resolve prerequisites and security gate

- Confirm the infrastructure owner's acceptance of the rootful Podman socket authority described in section 3.1.
- Record the qualification baseline as RHEL 9.8, rootful Podman 5.8.2, Quadlet, SELinux enforcing, required host packages, and image base digest. Verify the exact installed build and repository/vendor support.
- Confirm management bind addresses/ports, host key storage, public-key input format, and whether Cockpit is reachable only through the external management perimeter.
- Confirm the in-container service/process model and initial capability hypothesis.
- Stop implementation if a decision requires changing an architecture invariant; document the conflict for explicit approval first.

### Phase 1: Configuration and read-only preflight

- Add the versioned JSON schema and representative non-secret configuration.
- Implement strict schema/value validation and human-readable errors.
- Add shared read-only checks for the RHEL 9.8 / Podman 5.8.2 baseline, Quadlet, `jq`, source tree, every declared network/CIDR, Podman socket, and host-wide prerequisites. Run service-specific checks only for enabled config sections.
- Prove invalid configuration, missing required files, occupied ports, and mismatched existing networks fail before any state changes.

### Phase 2: Debian image and container startup

- Add the repository-built Debian image with pinned base and explicit package list: OpenSSH, DNSMasq, Cockpit, cockpit-podman, and only required network diagnostics.
- Add startup validation and the selected service-management units/scripts.
- Keep public-key and DNS inputs as runtime mounts; keep private host keys in persistent host storage.
- Build and run the image in an isolated test environment with SELinux enforcing where available.
- Prove startup, shutdown, signal handling, service failure reporting, and replacement without loss of host identity.

### Phase 3: Quadlet lifecycle and network attachment

- Add the rootful Quadlet container definition and any network units needed for deterministic boot ordering.
- Use Bash to render/install only configuration that cannot be expressed safely as a static Quadlet file.
- Create or verify declared networks without joining application networks together.
- Enable the generated systemd service and prove a second deployment produces no unnecessary container replacement or service restart.
- Prove adding/removing a declared gateway attachment does not delete the underlying application network or volume.
- Prove every configured network receives a Gateway interface, while removing a network from the global inventory never deletes the underlying network or volume.

### Phase 4: DNS generation, NAT, and remote service access

- Resolve container addresses with Podman network inspection, scoped to each configured network.
- Verify that the shared Gateway has one interface on every network in the global top-level `networks` inventory; never bridge those networks together.
- Define each configured remote exposure by protocol, reachable host address/port, and target container/network/port. The JSON config activates the mapping without a separate service-approval workflow. Reject duplicate listener tuples, undeclared targets, and loopback binds for remote listeners.
- Implement IPv4 forwarding and DNAT-only rules for configured TCP services so the target receives the original client source address. Do not apply SNAT. Add UDP only for a concrete requirement. Grant only capabilities proven necessary on RHEL 9.8 / Podman 5.8.2.
- Configure routes for every declared remote-client CIDR through the Gateway interface on each target network so replies return through the DNAT/conntrack path. Confirm the host forwarding path is symmetric. If source-preserving return routes cannot be implemented, stop and report the conflict; do not silently enable SNAT.
- Generate DNSMasq records for NAT-published names using the client-reachable Gateway address. Retain container addresses as NAT targets, not as remote DNS answers. Use direct container-address answers only where client routes to the Podman CIDRs are confirmed.
- Validate the candidate config before atomic install; preserve the last known-good file when validation fails.
- Install NAT rules atomically or through a validated ruleset replacement; remove only Gateway-owned rules and preserve the last known-good ruleset on failure.
- Reload DNSMasq and NAT rules only when generated content changes. Remove stale records and mappings by replacing only Gateway-owned generated state.
- Test from a remote client in a declared CIDR: resolve the name, connect to the configured host port, verify the target observes the actual client IP, authenticate at the target, and confirm replies work. Recreate the target, refresh, and verify the stable endpoint reaches its new address without changing the DNS answer.

### Phase 5: SSH, Cockpit, and socket integration

- Load gateway and destination public keys from separate root-managed host files outside Git. Validate permissions and key format; make consuming mounts read-only. Application deployment owns destination account provisioning and key revocation.
- Configure SSH forwarding so a VS Code Remote-SSH/ProxyJump path reaches the destination and destination authentication remains authoritative.
- Verify gateway authentication does not substitute for or bypass target authentication.
- Configure Cockpit and cockpit-podman against the local rootful Podman Unix socket.
- Verify the gateway can see/manage intended rootful containers while Podman has no TCP listener and SELinux remains enforcing.
- Document the socket authority, exposed management ports, external perimeter assumptions, and operator-only recovery path.

### Phase 6: RHEL 9.8 / Podman 5.8.2 acceptance and handover

- Run the complete matrix in section 9 on a disposable RHEL 9.8 system using rootful Podman 5.8.2 and SELinux enforcing. Do not use a live host.
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
| DNS initial state | Query each NAT-published name from an approved remote client and inspect its exposure mapping. Query an undeclared database name. | DNS resolves to the reachable Gateway address; the declared host port maps to the current target IP/port. Undeclared services are absent. |
| DNS/NAT update | Recreate a mapped application container with a different address and run the documented refresh. Query DNS and connect to the stable host endpoint before and after. | DNS remains mapped to the reachable Gateway address; NAT targets the new container address. Stale rules are absent and invalid candidates leave the last good state active. |
| Gateway all-network access | Inspect one Gateway interface per entry in the top-level network inventory. Test connectivity to declared SSH, HTTP/80, and database endpoints from the Gateway. | Gateway can reach every configured Podman network and its services. The Gateway is treated as a trusted administrative component, not an isolation boundary. |
| Network isolation | Attempt direct app-to-app traffic without an explicit connection, excluding traffic initiated by the multi-homed Gateway. | Application networks remain separate and do not gain direct peer connectivity merely because the Gateway attaches to both. |
| Remote NAT forwarding | From a client in a configured remote CIDR, connect to each configured address/port. Verify the target observes the client's original IP and replies work. Test an undeclared host port. | DNAT-only forwards to the configured target, source IP remains unchanged, return routes are symmetric, and undeclared ports fail. No SNAT rule is used. |
| SSH forwarding | Connect using the documented VS Code Remote-SSH/ProxyJump configuration. Use separate gateway and destination keys. Attempt access with a valid gateway key but invalid destination key, then with valid destination credentials. | Forwarding succeeds. Target accepts/rejects based on its own credentials. Private keys remain on the developer workstation. Gateway public-key setup is distinct. |
| SSH forwarding policy | Test allowed destination ports and an unrelated host/network. Inspect effective `sshd` settings. | Only documented forwarding behavior is enabled. No unintended agent, tunnel, or gateway-port exposure is introduced. |
| Reboot recovery | Reboot the disposable RHEL 9.8 host with Podman 5.8.2, declared networks, Quadlet, DNS, and NAT exposures. | Quadlet restores every declared Gateway interface; DNSMasq and NAT rules recover without manual container entry. Persistent keys and application data survive. |
| Cockpit Podman access | Through Cockpit, inspect and perform a controlled lifecycle operation on a disposable rootful test container. Inspect host listening sockets and socket mounts. | cockpit-podman accesses the intended rootful Podman service through the Unix socket. No Podman API listens on TCP. Socket authority is documented. |
| Capabilities | On RHEL 9.8 with rootful Podman 5.8.2, test each required feature with a minimal capability baseline, then add candidate capabilities one at a time. Inspect effective capabilities and test routing, forwarding/NAT, diagnostics, low ports, systemd, SSH, and Cockpit. | Exact required capabilities are recorded. No `--privileged`, `CAP_SYS_ADMIN`, or other broad capability is retained without evidence and explicit approval. Removing a required capability causes a specific test failure. |
| SELinux | Run the same lifecycle, socket, mount, and DNS tests with SELinux enforcing. Inspect AVC denials. | No global SELinux disable or broad relabel workaround is required. Any narrow policy or labeling requirement is documented and reviewed. |
| Quadlet behavior | Validate generated systemd units, dependencies, start/stop/restart behavior, and reboot enablement on RHEL 9.8 / Podman 5.8.2. | Quadlet owns the Gateway lifecycle; deployment does not leave unmanaged duplicate containers or stale units. |

For the capability test, treat `CAP_NET_ADMIN` as a candidate for in-container forwarding/NAT, not as an assumed final answer. Test `CAP_NET_RAW` only for diagnostics that require it. Test whether Cockpit/systemd needs additional capabilities on the actual supported Podman version. Do not grant capabilities speculatively.

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

1. Does the RHEL 9.8 / Podman 5.8.2 target pass vendor/package support and all lifecycle tests? Record the exact kernel, Quadlet generator, package source, and SELinux policy versions.
2. Can Cockpit access the approved rootful Podman socket while SELinux remains enforcing, without broad relabeling or policy changes?
3. Which exact capabilities and routes are required to use DNAT without SNAT while returning traffic through the Gateway from every configured Podman network?
| Persistence | Seed a database/application volume and external secret/key files. Rebuild/recreate the Gateway and rerun deployment. | Volume identity/data, secret bytes, SSH host keys, and permissions remain intact. Gateway image replacement does not own or delete app data. |
4. Which SSH forwarding policy, management bind addresses, and ports pass the infrastructure perimeter requirements?
5. Do reboot recovery, DNS refresh after container recreation, failure rollback, and health checks pass on the target platform?

Do not treat resolved configuration details, such as stopped-target handling or key-file paths, as open decisions. Do not claim a test passed unless it ran on the stated target.

## 12. Completion Criteria

The bootstrap is ready for review when:

- Host deployment and container startup are separate Bash-owned responsibilities.
- Quadlet controls the rootful Gateway lifecycle on RHEL 9.8 with rootful Podman 5.8.2.
- The Debian image builds from repository sources and contains no secrets.
- Network and DNS declarations come from versioned JSON configuration.
- Runtime DNS reflects current container addresses after recreation.
- NAT forwards only configured remote service endpoints to their current target addresses, with validated return traffic and no unintended cross-network access.
- NAT preserves original client addresses through DNAT-only rules and validated return routes; deployment does not apply SNAT.
- DNSMasq returns the reachable Gateway address for NAT-published services; direct container addresses are used only for clients with confirmed Podman-CIDR routes.
- Invalid input fails before host or service changes.
- Repeated deployment preserves application data, secrets, SSH host identity, and volumes.
- SSH forwarding preserves destination authentication.
- Cockpit Podman works over the Unix socket with no TCP API and no `--privileged`.
- Reboot recovery and exact required capabilities are proven on a disposable RHEL 9.8 / Podman 5.8.2 host.
- NAT, DNS, Quadlet lifecycle, and SELinux behavior are proven on disposable RHEL 9.8 with rootful Podman 5.8.2.
- Security tension, open decisions, test environment, and operator recovery steps are recorded.

## 13. Current Status

The Gateway implementation remains in progress, and no RHEL 9.8 / Podman 5.8.2 host acceptance is claimed. NAT-based remote service access is a required missing implementation phase; the Gateway is not complete until declared external endpoints reach the correct current container targets. SELinux socket access, exact capabilities, NAT/return-path behavior, reboot recovery, and end-to-end SSH remain acceptance gates. Use [gateway-implementation.md](gateway-implementation.md) for the current operator workflow and validation record. Do not deploy to a live host.