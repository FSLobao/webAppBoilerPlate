# Development Gateway Bootstrap Plan

**Status:** Implementation plan derived from the approved architecture baseline
**Scope:** Shared Development Gateway bootstrap on RHEL 9 with rootful Podman
**Deployment target:** Isolated test host only during implementation; no live-host deployment is authorized by this plan.

## 1. Goal

Implement a reproducible bootstrap for the shared Development Gateway. Keep host deployment and container startup as separate responsibilities. Build the Debian image from repository sources. Read application network declarations and development DNS mappings from versioned configuration.

The deployment must be repeatable without deleting application data, volumes, secrets, SSH host keys, or unrelated Podman resources. It must fail validation before changing the host or the running gateway.

## 2. Scope

In scope:

- A Bash host deployment script for an authorized infrastructure operator.
- A Quadlet-managed, rootful Podman Development Gateway container.
- A Debian image built from a repository `Containerfile`.
- A separate Bash startup/validation script inside the image.
- Versioned declarations for application networks, CIDRs, and development DNS mappings.
- Runtime DNS generation from current container addresses.
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

- One shared Development Gateway serves multiple isolated application networks.
- Each application retains its own Podman network. No global network joins applications.
- The Development Gateway is not the Application Gateway and does not serve user traffic.
- DNSMasq runs in the Development Gateway. Deployment generates records from the current addresses of declared containers.
- Only services requiring development access receive DNS records. Databases remain unpublished by default.
- SSH forwarding does not replace destination authentication. Developers authenticate to the target container with their individual keys. Access to the gateway itself has separate authentication.
- Podman access uses a local Unix socket. No Podman API listener is exposed over TCP.
- Secrets and private keys stay outside Git and outside the image. Secret mounts are read-only and limited to consumers that need them.
- Rootful Podman and Quadlet manage the container lifecycle. The gateway does not require `--privileged`.
- Normal deployment must not prune containers, images, networks, volumes, secrets, or data.

### 3.1 Explicit security tension

Cockpit administration of rootful Podman through its Unix socket grants broad control over rootful containers. Podman's rootful socket does not provide a narrow per-operation authorization policy. A read-only bind mount does not make API operations read-only.

Before implementation, the infrastructure owner must accept this authority boundary and the exact socket mount, or revise the architecture contract. Do not resolve this tension by exposing the API over TCP, using `--privileged`, or disabling SELinux. This plan does not silently change the architecture.

### 3.2 Subagent assessment

No subagent is required for this plan-only change. The implementation steps share a single lifecycle contract and should have one owner. Add no agent-role files. During implementation, use focused human review and the validation gates below; reconsider delegation only if a separate, independent RHEL 9 compatibility investigation becomes necessary.

## 4. Proposed Repository Artifacts

Keep source-controlled inputs separate from generated host state:

```text
config/development-gateway.json
gateway/development/Containerfile
gateway/development/startup.sh
gateway/development/systemd/
deploy/quadlet/development-gateway.container
scripts/deploy-development-gateway.sh
```

Use existing repository conventions if implementation reveals an established location. Do not commit generated DNS files, host-specific Quadlet output, SSH private keys, secrets, or runtime state.

The host deployment script owns host prerequisites, image build, network checks, generated Quadlet installation, DNS record generation, service activation, and health verification. The container startup script owns in-container validation and service startup only. Neither script should source the other's configuration as executable shell.

## 5. Versioned Configuration Contract

Use JSON for the versioned configuration and `jq` for structured parsing. Do not parse nested configuration with `grep`, `sed`, `eval`, or shell word splitting. Declare `jq` as a host prerequisite and fail during read-only preflight if it is unavailable.

The initial schema should contain:

- `schema_version`, initially `1`.
- Gateway identity and explicitly configured published management ports.
- An array of application networks. Each entry declares the exact Podman network name and expected non-overlapping CIDR.
- An array of development DNS records. Each entry declares a fully qualified internal name, target container, and application network.
- Public-key source paths or identifiers for gateway access and application destinations. Private-key paths are forbidden.

Illustrative shape; finalize field names and requiredness before implementation:

```json
{
  "schema_version": 1,
  "gateway": {
    "name": "development-gateway",
    "ssh_port": 2222,
    "cockpit_port": 9090
  },
  "networks": [
    {
      "name": "project-a-net",
      "subnet": "10.89.1.0/24"
    }
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

Validation must reject unsupported schema versions, duplicate network names, duplicate DNS names, malformed names/CIDRs, overlapping CIDRs, records referencing undeclared networks, and mappings to a container outside the declared network. Existing Podman networks must match their declared subnet; never silently recreate or mutate a mismatched network.

The configuration contains logical identities, not permanent container IPs. The deployment queries Podman for each target's current address on the declared network every time it generates DNS. When a declared target is not running, report it clearly and do not publish a stale address. Decide whether absent targets are warnings or fatal preflight errors before coding; either policy must leave the active DNS configuration and gateway untouched on failure.

## 6. Host and Container Responsibilities

### 6.1 Host deployment: Bash plus Quadlet

The host script should:

1. Require rootful Podman access and an explicitly supported RHEL 9/Podman/Quadlet version. It must not install packages or alter host security policy implicitly.
2. Run a read-only preflight before any host mutation. Validate configuration, tools, paths, permissions, port availability, existing network definitions, key inputs, Podman socket availability, SELinux mode, and current service state.
3. Offer a validation-only mode that performs no writes, image builds, network changes, service restarts, or file creation. Any invalid input or unmet hard prerequisite must exit non-zero before mutation.
4. Build the Debian image from the checked-out repository `Containerfile`, with an explicitly versioned/pinned base image and reproducible package inputs. Never bake secrets or public-key data into image layers.
5. Create only missing declared application networks, or verify existing ones match configuration. Do not connect application networks to one another.
6. Stage generated DNS and Quadlet files in temporary files on the same filesystem, validate them, and install them atomically. Keep generated host state in dedicated paths, separate from operator-managed secrets and data.
7. Install/update the rootful Quadlet definition under the supported system location, reload systemd, and enable/start the generated service. Avoid restarting or recreating the gateway when desired configuration and image are unchanged.
8. Ensure the gateway joins only declared application networks. Apply removals only to gateway attachments after validating the complete new configuration; never delete an application network as part of normal deployment.
9. Mount the Podman Unix socket only at the path Cockpit Podman actually uses. Do not claim that a read-only socket mount restricts API authority. Do not disable SELinux or relabel the host socket broadly to make access work.
10. Regenerate DNS after an application container is created or recreated. The application deployment handoff must invoke the gateway DNS/deployment update after its service is ready; no background watcher is in scope.
11. Verify readiness, DNS answers, SSH forwarding, Cockpit/Podman visibility, network attachments, and service state. On failed health checks, restore the previous generated Quadlet/DNS files and previous working service configuration where feasible.
12. Print a concise result with changed resources, pending DNS targets, service status, and recovery instructions. Never print secret contents.

The deployment must not use `podman system prune`, `podman volume prune`, blanket `rm -rf`, or equivalent cleanup. It must not overwrite existing host keys, secret files, application data, or unrelated Quadlet units.

### 6.2 Container startup: Bash inside Debian image

The startup script should:

- Validate required read-only mounts and configuration before starting services.
- Fail with actionable diagnostics when a required file, key, directory, or permission is invalid.
- Start and supervise SSH, DNSMasq, and Cockpit using a process model supported by the chosen Debian packages. Prefer the minimum mechanism compatible with Cockpit's service activation; do not add a custom supervisor without demonstrated need.
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
- Record the supported RHEL 9 and Podman versions, rootful Quadlet locations, required host packages, and image base digest.
- Confirm management bind addresses/ports, host key storage, public-key input format, and whether Cockpit is reachable only through the external management perimeter.
- Confirm the in-container service/process model and initial capability hypothesis.
- Stop implementation if a decision requires changing an architecture invariant; document the conflict for explicit approval first.

### Phase 1: Configuration and read-only preflight

- Add the versioned JSON schema and representative non-secret configuration.
- Implement strict schema/value validation and human-readable errors.
- Add read-only checks for RHEL, Podman, Quadlet, `jq`, source tree, ports, network/CIDR conflicts, Podman socket, key files, paths, and permissions.
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

### Phase 4: DNS generation and update contract

- Resolve container addresses with Podman network inspection, scoped to each configured network.
- Generate a dedicated DNSMasq include file from versioned DNS mappings and current addresses.
- Validate the candidate config before atomic install; preserve the last known-good file when validation fails.
- Reload DNSMasq only when generated content changes. Remove stale records by replacing only the gateway-owned generated include.
- Test the application deployment handoff: recreate a target with a different IP, rerun the update, and prove the same logical name resolves to the new address.

### Phase 5: SSH, Cockpit, and socket integration

- Configure individual public keys separately for gateway login and application destinations.
- Configure SSH forwarding so a VS Code Remote-SSH/ProxyJump path reaches the destination and destination authentication remains authoritative.
- Verify gateway authentication does not substitute for or bypass target authentication.
- Configure Cockpit and cockpit-podman against the local rootful Podman Unix socket.
- Verify the gateway can see/manage intended rootful containers while Podman has no TCP listener and SELinux remains enforcing.
- Document the socket authority, exposed management ports, external perimeter assumptions, and operator-only recovery path.

### Phase 6: RHEL 9 acceptance and handover

- Run the complete matrix in section 9 on a disposable RHEL 9 system using rootful Podman. Do not use a live host.
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
| DNS initial state | Query each configured name through DNSMasq and compare answer with the target's current address on its declared network. Query an undeclared database name. | Declared names resolve correctly. Undeclared/internal-only services are not published. |
| DNS update | Recreate a mapped application container with a different address and run the documented DNS update. Query before and after, including after DNS cache expiry or reload. | The logical name returns the new address; stale address is absent. Invalid candidate config leaves prior good records active. |
| Network isolation | Inspect gateway attachments and application network membership; attempt app-to-app traffic without an explicit connection. | Gateway attaches only to declared networks. App networks remain separate and app-to-app traffic remains blocked by default. |
| SSH forwarding | Connect using the documented VS Code Remote-SSH/ProxyJump configuration. Use separate gateway and destination keys. Attempt access with a valid gateway key but invalid destination key, then with valid destination credentials. | Forwarding succeeds. Target accepts/rejects based on its own credentials. Private keys remain on the developer workstation. Gateway public-key setup is distinct. |
| SSH forwarding policy | Test allowed destination ports and an unrelated host/network. Inspect effective `sshd` settings. | Only documented forwarding behavior is enabled. No unintended agent, tunnel, or gateway-port exposure is introduced. |
| Reboot recovery | Reboot the disposable RHEL 9 host with declared networks, gateway unit, Podman socket activation, and DNS mappings configured. | Quadlet recreates/starts the gateway after network dependencies are ready; DNSMasq, SSH, Cockpit, and Podman socket access recover without manual container entry. Persistent keys and application data survive. |
| Cockpit Podman access | Through Cockpit, inspect and perform a controlled lifecycle operation on a disposable rootful test container. Inspect host listening sockets and socket mounts. | cockpit-podman accesses the intended rootful Podman service through the Unix socket. No Podman API listens on TCP. Socket authority is documented. |
| Capabilities | On RHEL 9, test each required feature with a minimal capability baseline, then add candidate capabilities one at a time. Inspect effective capabilities and test routing, forwarding/NAT, diagnostics, low ports, systemd, SSH, and Cockpit. | Exact required capabilities are recorded. No `--privileged`, `CAP_SYS_ADMIN`, or other broad capability is retained without evidence and explicit approval. Removing a required capability causes a specific test failure. |
| SELinux | Run the same lifecycle, socket, mount, and DNS tests with SELinux enforcing. Inspect AVC denials. | No global SELinux disable or broad relabel workaround is required. Any narrow policy or labeling requirement is documented and reviewed. |
| Quadlet behavior | Validate generated systemd units, dependencies, start/stop/restart behavior, and reboot enablement on the supported RHEL 9 Podman version. | Quadlet owns the gateway lifecycle; deployment does not leave unmanaged duplicate containers or stale units. |

For the capability test, treat `CAP_NET_ADMIN` as a candidate for in-container forwarding/NAT, not as an assumed final answer. Test `CAP_NET_RAW` only for diagnostics that require it. Test whether Cockpit/systemd needs additional capabilities on the actual supported Podman version. Do not grant capabilities speculatively.

## 10. Operational and Failure Behavior

- Validation failures must happen before mutation. The script must identify the failing input and the resource it would have affected.
- Build or candidate-config failures must leave the active Quadlet, DNS config, and running gateway unchanged.
- Install generated files atomically. Keep the previous known-good copies until the new service passes health checks.
- If activation fails, restore the previous generated files and service definition where feasible, then report both the original and rollback errors.
- Never remove volumes, secret files, host keys, application data, unrelated containers, or unrelated systemd/Quadlet units during apply or rollback.
- Normal apply may create missing declared networks and attach the gateway. It must not delete networks. Network decommissioning and persistent-data deletion require separate, explicit operator procedures.
- When a configured DNS target is absent, follow the requiredness policy fixed in Phase 0. Never retain or publish a stale IP as a fallback.
- Keep logs free of secret content. Do not put secret values in command-line arguments, generated unit files, build arguments, or image history.
- Report partial additive changes, such as a newly created network, if later activation fails. Do not present rollback as complete when host state remains changed.

## 11. Open Decisions Before Implementation

Resolve and record these items without changing the architecture contract:

1. Exact supported RHEL 9/Podman/Quadlet versions and Quadlet network-unit strategy.
2. Rootful Podman socket authority acceptance, mount path, Cockpit integration behavior, and SELinux constraints.
3. Exact public-key input format and host-managed SSH host-key path.
4. Whether missing mapped containers are fatal during apply or reported as pending; either behavior must avoid stale DNS.
5. Management bind addresses and ports, and the external perimeter restriction for SSH/Cockpit.
6. Debian release/base-image digest and package update policy.
7. Exact minimal Linux capability set established by the RHEL 9 tests.
8. Health check commands and the recovery behavior if DNS, SSH, or Cockpit fails independently.

## 12. Completion Criteria

The bootstrap is ready for review when:

- Host deployment and container startup are separate Bash-owned responsibilities.
- Quadlet controls the rootful gateway lifecycle on the supported RHEL 9/Podman version.
- The Debian image builds from repository sources and contains no secrets.
- Network and DNS declarations come from versioned JSON configuration.
- Runtime DNS reflects current container addresses after recreation.
- Invalid input fails before host or service changes.
- Repeated deployment preserves application data, secrets, SSH host identity, and volumes.
- SSH forwarding preserves destination authentication.
- Cockpit Podman works over the Unix socket with no TCP API and no `--privileged`.
- Reboot recovery and exact required capabilities are proven on a disposable RHEL 9 host.
- Security tension, open decisions, test environment, and operator recovery steps are recorded.

## 13. Implementation Handover Prompt

Use this prompt to start the implementation in a new coding session:

```text
Implement the Development Gateway bootstrap in this repository.

Read `docs/plans/WEB_APP_BOILERPLATE_ARCHITECTURE.md` first. Then read
`docs/plans/development-gateway-bootstrap-plan.md` in full. Treat the architecture
document as the contract and the bootstrap plan as the implementation and test
specification. Read and follow applicable repository instructions.

Before editing, inspect the relevant repository state and identify the smallest
implementation slice. Start with Phase 0 in the plan. Confirm whether the
infrastructure owner has accepted Cockpit's broad rootful Podman socket
authority. Do not assume approval. If approval or another decision required by
the plan is missing, report the exact blocker before implementing any dependent
integration. Do not change architectural scope without explicit approval.

Keep host deployment and container startup separate. Use Bash and rootful
Podman Quadlet. Build the Debian image from repository sources. Read declared
application networks and development DNS mappings from versioned structured
configuration. Generate DNS records from current container addresses.

Preserve the plan's invariants:
- Keep each application on its own Podman network.
- Preserve destination-side SSH authentication when forwarding connections.
- Use the local Podman Unix socket only; never expose the Podman API over TCP.
- Do not use `--privileged`, disable SELinux, or add broad capabilities as a
  workaround.
- Keep secrets and private keys out of Git and images. Never overwrite existing
  secrets, SSH host keys, application data, or volumes on rerun.
- Make validation fail before host or service mutation. Do not prune resources.

Implement in small, reviewable steps. Add focused tests for the changed slice.
Cover malformed configuration and failure-before-change behavior, idempotence,
data and secret preservation, DNS address updates, SSH forwarding and target
authentication, reboot recovery, Cockpit access through the Unix socket, and
the minimum capabilities required on RHEL 9 with Podman. Keep host integration
tests isolated and destructive tests limited to disposable resources.

Do not deploy to a live host. Do not claim RHEL 9 behavior is validated unless
the required tests ran on a disposable RHEL 9 system. If that environment is
unavailable, finish safe local validation and list the remaining host tests.

Use subagents only when a separate, bounded investigation materially helps;
do not create agent-role files by default. Report changed files, validation
results, unresolved owner decisions, and any work blocked by the RHEL 9 gate.
```