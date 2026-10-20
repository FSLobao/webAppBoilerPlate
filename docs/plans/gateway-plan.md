# Gateway Bootstrap Plan

**Status:** Base Gateway bootstrap, readiness-scoped DNS handoff, opt-in OpenVPN client, SSH TUN, and additive IPv4-only WireGuard server/peer CLI are implemented. All remote-access services remain disabled in checked-in config. Isolated WireGuard container-only packet tests passed on 2026-10-20; kernel support does not block starting or rerunning isolated functional tests. Production/deployed remote-client acceptance remains blocked on explicit transport configuration, external routes and return paths, and human/client prerequisites. OS-specific split-DNS recipes exist but require validation on each client OS. No application lifecycle caller is included. RHEL 9.8 / Podman 5.8.2 qualification and target-host acceptance remain pending. The approved deployment order is Gateway first, then application services and NGINX.
**Scope:** Shared Gateway bootstrap on RHEL 9.8 with rootful Podman 5.8.2
**Acceptance target:** RHEL 9.8, rootful Podman 5.8.2, Quadlet, and SELinux disabled. Disabling SELinux removes mandatory access controls; preflight must verify the requested state and must not change host security settings.
**Deployment target:** Isolated test host only during implementation; no live-host deployment is authorized by this plan.

## 1. Goal

Implement a reproducible bootstrap for the shared Gateway. Run host deployment scripts only on RHEL 9.8 with rootful Podman 5.8.2. Keep host deployment and container startup as separate responsibilities. Use a maintained, efficient Linux distribution for the Gateway and application images, preferably Debian or Alpine. Select container bases independently from the host distribution.

The deployment must provide authorized remote developers symmetric, routed IPv4 Layer 3 access to every configured container IPv4 network. Developers may initiate traffic using any IPv4 protocol and port. The deployment must also allow containers to initiate traffic to externally routable destinations through normal rootful Podman host egress, using host masquerading. Neither path may forward traffic between application networks. The deployment must remain repeatable without deleting application data, volumes, secrets, SSH host keys, or unrelated Podman resources. It must fail validation before changing the host or the running gateway.

The Gateway remote-access contract is IPv4-only: developer destinations, WireGuard/OpenVPN/SSH TUN pools, point-to-point session pairs, host return routes, and generated DNS records use IPv4; DNS generation emits A records, not AAAA records. This does not disable IPv6 on the host, Gateway, or client systems. The outer SSH transport is not forced to IPv4 by the Gateway runtime; clients that require an IPv4 outer connection must use `ssh -4`.

## 2. Scope

In scope:

- A Bash host deployment script for an authorized infrastructure operator.
- A Quadlet-managed, rootful Podman Gateway container.
- A Debian image built from a repository `Containerfile`.
- A separate Bash startup/validation script inside the image.
- Versioned declarations for application networks, CIDRs, and development DNS mappings.
- Runtime DNS generation from current container addresses.
- Full routed Layer 3 split-tunnel access from developer clients to every configured Podman CIDR through the additive Gateway WireGuard server, Gateway OpenVPN client, and OpenSSH TUN sessions. Multiple SSH TUN developers and all transports may be active concurrently; transport pools are distinct.
- Additive Gateway WireGuard server for approved peers, with IPv4 split routes to every configured top-level Podman network and OS-specific split DNS for `dev.anatel`.
- Root-only peer approval, inventory, expiry, revocation, and one-time `/dev/tty` delivery of client private keys generated inside Gateway. No public admin HTTP/API exists; users with Gateway-container administrative privilege are trusted to grant all-network access.
- Host publication of the Gateway WireGuard UDP listener through Quadlet. Endpoint and port are deployment inputs; publication is not evidence that an endpoint is reachable.
- Unrestricted container-initiated egress to externally routable destinations through the host's normal Podman egress path.
- Runtime DNS generation from current container addresses and instructions for remote clients to query DNSMasq through a tunnel.
- Client setup documentation for OpenVPN and OpenSSH TUN, including routes and DNS configuration.
- Bootstrap of individual public SSH keys without copying private keys.
- Cockpit and cockpit-podman access through the local rootful Podman Unix socket.
- Failure, idempotence, persistence, DNS, SSH, reboot, Cockpit, and RHEL 9 capability validation.

Out of scope:

- HTTP proxy implementation or application/backend/database deployment.
- Deployment/provisioning of the external OpenVPN server. That server remains externally managed and allocates OpenVPN client addresses; this project retains only the Gateway's OpenVPN client.
- External firewall/perimeter changes, corporate authentication, public DNS, or TLS policy. The external OpenVPN owner provisions routes for Podman CIDRs via the Gateway's OpenVPN client and distributes its split routes.
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
- The Development Gateway is not an end-user HTTP proxy. It provides developer access to all configured service ports without publishing those service ports on the host. The WireGuard server listener is a separate UDP host-port publication.
- DNSMasq runs in the Gateway and returns current container addresses only for readiness-confirmed declared targets. An unavailable or not-ready target is pending and has no published record. Remote clients can use the Gateway DNS service through active WireGuard, OpenVPN, or SSH TUN interfaces and must have routes to every configured Podman CIDR.
- The Gateway routes developer-initiated traffic across tunnel interfaces to every configured container network without protocol or port filtering. Stateful replies are allowed. New container-initiated egress uses normal Podman host egress and host masquerading.
- The shared Gateway can reach every network-attached service, including PostgreSQL. Remote developers also gain access to every configured network and service, including database services. WireGuard peer approval and transport authentication govern peer access; each service still requires its own credentials.
- The Gateway forwards traffic between each tunnel interface and each configured application network, but never between application networks. Containers do not gain direct peer connectivity merely because the Gateway attaches to both.
- The additive Gateway WireGuard server, OpenVPN client, and OpenSSH TUN can coexist after conflict checks. The OpenVPN profile is an external file referenced from JSON and mounted read-only. The external OpenVPN server remains out of scope; the WireGuard server runs in Gateway.
- Every approved WireGuard peer receives `AllowedIPs` containing exactly every CIDR in top-level `networks`, including PostgreSQL networks. The resolver is a Gateway address within those CIDRs. No default route is routed through Gateway.
- WireGuard uses IPv4 only for this data plane. It adds no NAT, DNAT/SNAT, inter-application forwarding, or per-service authorization. Services retain their own authentication.
- Internal DNS suffix is exactly `dev.anatel` and is not public. Host schema accepts this suffix; DNS emits A records only. Current `dns_records` is empty, and the generic DNS generator uses declared names without a fixed suffix. Older `.dev.internal` examples have been migrated. WireGuard profiles do not push DNS; client split DNS uses the platform-specific recipes.
- WireGuard does not push routes or DNS. Windows 11 uses an NRPT suffix rule; Linux uses systemd-resolved routing-only domain `~dev.anatel` and a per-link resolver; macOS uses `/etc/resolver/dev.anatel` or another approved resolver configuration. Preserve global DNS and default routes.
- Host publishes the WireGuard UDP container port through Quadlet. The UDP port and endpoint are not approved. `51820/UDP` is only a suggested default, not a decision. No external firewall or perimeter change is a plan requirement.
- Gateway-container administrators can perform all peer operations and can reach every configured service, including PostgreSQL. Treat these administrators as trusted network administrators; service credentials remain separately required.
- Server private key is root-owned, external to Git, and available only to the WireGuard consumer. Peer private keys are generated inside Gateway, delivered once to verified foreground `/dev/tty`, and never persisted or logged. Plaintext exists transiently in memory. TTY checks cannot detect external recording; operators must use a trusted non-recording terminal.
- Keep pushed-domain options with the external OpenVPN server/profile; do not repurpose them for WireGuard. Protocol, port, and topology also belong to the external server/profile, while `client_to_client` is server-side. Do not duplicate these settings in Gateway JSON.
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

### 3.2 Routed remote-access contract (confirmed; both runtimes opt-in)

This is full routed Layer 3 split-tunnel access, not per-service forwarding. Gateway runs an additive WireGuard **server**, retains the externally provisioned OpenVPN **client**, and retains OpenSSH point-to-point TUN (`ssh -w`). SSH supports multiple simultaneous developers on unique, non-overlapping session interfaces and address pairs from a separate SSH TUN pool. All three transports may coexist after route and pool conflict validation. This project does not deploy the external OpenVPN server. No DHCP, Ethernet bridging, TAP, or per-service forwarding is required.

Route direction and ownership are explicit:

- The external OpenVPN owner configures routes for each Podman application CIDR toward the Gateway's OpenVPN client. Developer clients receive split routes only for configured Podman destinations; their normal default route, unrelated container egress, and source addresses remain unchanged.
- WireGuard peers receive `AllowedIPs` for every configured Podman CIDR. WireGuard does not push client routes or DNS. The host publishes its UDP listener through the Gateway Quadlet unit; no claim of public reachability follows from host publication alone.
- OpenVPN client addresses are allocated by the external server from its dedicated remote-client pool. The external owner provisions and maintains the server-side route to each Podman CIDR via the Gateway VPN client.
- On the Gateway, each configured Podman CIDR is reached over its already-connected Podman interface. Do **not** route an application CIDR back through either developer tunnel. For each remote client prefix, install/retain a route through the tunnel that owns that prefix/session.
- Containers reply through their normal Podman path to the host. The host return route for each remote client prefix uses one deterministic Gateway next hop/interface, not conflicting copies of that same prefix via every Podman network. If target-host tests prove policy routing is necessary, use explicit, separately owned policy tables/rules with deterministic selection; do not silently install competing routes.
- Each active tunnel forwards IPv4 only between its own peer/client interface and configured Podman interfaces, with stateful replies. No transport forwards between application interfaces or adds NAT. Ordinary container-initiated egress continues through normal rootful Podman host egress/masquerading, not through a developer tunnel. All runtimes remain opt-in; isolated WireGuard packet testing passed; formal target-host acceptance and OpenVPN/SSH TUN functional acceptance remain pending.

The Gateway preserves client IPv4 source addresses and uses no DNAT or SNAT for developer access. Split routes are limited to explicitly configured Podman IPv4 destinations; they do not replace or hijack the developer's default route. Static configured routes and connected Podman routes are allowed when they are the intended managed routes. Reject address/prefix overlap between OpenVPN and SSH pools/endpoints, Podman ranges, and relevant host, developer-LAN, or corporate routes. Do not blanket-reject default routes or necessary connected tunnel ranges. Validate active route/address data before mutation; if the information needed for a symmetric return path is unavailable or ambiguous, fail closed.

SSH TUN uses OpenSSH point-to-point tunnel devices (`ssh -w`) and provides routed IPv4 connectivity. Its opt-in runtime requires the fixed `gateway-tunnel` account, a restricted `PermitTunnel` policy, TUN device access, session address assignment, and client routes. ProxyJump and `ssh -L`, `ssh -R`, and `ssh -D` remain TCP-only access paths; they do not provide general routed access or client DNS. Keep the SSH outer connection family separate from the IPv4 TUN payload.

Each SSH TUN session must receive a unique interface and non-overlapping point-to-point address pair from the dedicated SSH pool. A restricted tunnel account and session setup/teardown mechanism own allocation, route installation, collision checks, and cleanup on normal exit and failed/disconnected sessions. Reject duplicate or ambiguous client prefixes across transports unless an explicit policy defines ownership; do not invent automatic multihoming or select a tunnel based on metrics. Do not add a generic background watcher. Protocol lifecycle hooks may reconcile only the session they own and must be documented separately from Gateway bootstrap.

The OpenVPN profile path is declared in `config/host_config.json` and refers to a root-managed, private file outside Git, uniquely assigned to this Gateway. Host preflight checks only file type, owner, mode, and path; it never opens or parses contents. Quadlet mounts the profile read-only only when OpenVPN is enabled. Enablement also requires `profile_reviewed: true`, an operator attestation that the opaque profile uses the approved client, endpoint, plugin/script, and external-file policy. OpenVPN alone consumes the profile; runtime logs are reduced to fixed sanitized diagnostics. OpenVPN's standard inline certificate/key blocks may appear inside the profile. The external production profile has not been reviewed or activated. The runtime supports IPv4 only, blocks IPv6 traffic, and rejects pushed IPv6 configuration. Local IPv6 directives are unsupported and require human profile review before the `profile_reviewed: true` gate can be satisfied.

The opt-in client starts with `--ifconfig-noexec` and `--route-noexec`. Its `up` hook validates the server-assigned IPv4 address and subnet against the configured client pool before assigning the address to `tun0`. Its `route-up` hook rejects every pushed or profile route candidate: configured Podman networks are already connected, and no other tunnel route is approved. Reconnects repeat these hooks. The OpenVPN pool return route is installed on the host via one deterministic configured Gateway address and carries reserved route protocol `186`; Quadlet start/stop hooks add and remove only that exact destination/next-hop/protocol. Host preflight recognizes only the exact tagged route as Gateway-owned. This implementation does not inspect or mutate profile contents.

The assigned address and pool are validated before tunnel-interface address installation; OpenVPN route changes are disabled before candidate hooks run. A synthetic route candidate is rejected, leaving forwarding and route state unchanged. Target-host behavior of Quadlet service hooks, kernel netfilter, the host Podman masquerade path, and real OpenVPN reconnect remains unverified.

DNSMasq must listen on each configured Gateway network address and active tunnel address. Containers use their Gateway network address for DNS; DNSMasq forwards other queries to the host's configured upstream resolvers. WireGuard, OpenVPN, and SSH TUN clients use split-DNS rules for `dev.anatel`. WireGuard itself does not push DNS configuration. ProxyJump alone cannot carry DNS queries. If split DNS is unavailable, static client `hosts` entries are a limited fallback and require refresh after container recreation.

Route state has explicit ownership and reconciliation rules: compute and validate a complete candidate before installation; modify only routes/rules tagged or otherwise unambiguously owned by this Gateway/session; make repeated reconciliation idempotent; retain unrelated administrator routes; and roll back only candidate-owned changes if activation fails. The current OpenVPN runtime rejects all tunnel route candidates, scopes forwarding to its private network namespace, and owns one host pool route tagged `proto 186`. SSH session allocation, TUN/address lifecycle, and the SSH pool return route are implemented; target-host route behavior and OpenVPN coexistence acceptance remain pending. Invalid OpenVPN route/address candidates do not install forwarding or candidate routes. Reconcile routes on protocol lifecycle events, not through an unrelated generic watcher. A repeated client prefix observed on two transports is rejected by default and fails closed unless a separately approved explicit policy resolves ownership.

### 3.3 Alternatives considered

- **Host-managed OpenVPN client:** Potentially simpler than running OpenVPN inside the Gateway because it avoids passing `/dev/net/tun` and `CAP_NET_ADMIN` into the container. It requires host-level VPN credentials and routes, increasing host-level trust and changing the deployment boundary. This is not the selected design.
- **Existing site-to-site or developer VPN routes:** Simplest if infrastructure can route developer CIDRs and every Podman CIDR directly through the host. It avoids an OpenVPN process in the Gateway, but depends on external route and firewall changes. This is not the selected design.
- **WireGuard client:** A smaller tunnel implementation may reduce Gateway package and process complexity. It requires a compatible external server and a new server-side decision, so it is not selected.
- **SSH local, remote, or dynamic forwarding:** Easier for individual TCP services, but cannot provide unrestricted IP protocol and port access. It does not meet this plan's acceptance target. SSH TUN (`ssh -w`) remains the supported SSH option.

### 3.4 Selected initial network layout

The selected [host configuration](../../config/host_config.json) declares. The requester confirmed on 2026-10-19 that `192.168.9.0/24` is available and approved for use; this confirmation is not a host route-table measurement:

| Podman network | Subnet | Gateway address | Requested members |
|---|---|---|---|
| `shared` | `192.168.9.0/24` | `192.168.9.2` | Gateway, NGINX, `webApp`, and `postgres` |
| `webApp` | `192.168.8.0/29` | `192.168.8.2` | `webApp` and `postgres` |

The Gateway is configured on both declared networks, matching the existing all-networks contract. Each app container also joins `shared`; direct connectivity between shared-network members is accepted and authentication belongs to each service. This still means “no routing between app networks” does not isolate services attached to `shared`.

Deployment inputs and implementation gates (not architecture decisions):

1. Validate Quadlet assignment of `192.168.9.2` and `192.168.8.2` on the target host.
2. Implement application deployment so it creates each unique Podman app network, adds it only to the global top-level `networks` inventory, then reconciles the existing Gateway, which attaches to every declared network. Do not create a second Gateway or maintain a separate Gateway network list.
3. Have the infrastructure owner review the opaque production OpenVPN profile, any external file references, assigned client address/push behavior, the SSH TUN pool and restricted-account/session policy, client OS details, and server-side Podman routes. Do not inspect the profile in this project or invent missing production values.
4. Validate configured Podman, tunnel, host, developer-LAN, and corporate route ranges on the target before installation.


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
- A required top-level `networks` array containing every Podman network declared for applications and their services, with exact name, expected CIDR, and non-overlapping Gateway interface address. This is the global application-network inventory; the Development Gateway attaches to every listed network. Do not include unrelated host interfaces/attachments, external VPN routes, or tunnel address pools here.
- Optional service-specific sections such as `gateway`, `http_proxy`, direct service-publication declarations, and per-application declarations. Feature sections are optional and backward-compatible under required `schema_version: 1`. For compatibility, schema-v1 OpenVPN configs may still contain the retired `protocol`, `port`, `device`, `topology`, `client_to_client`, `auth`, `cipher`, or `push_domains` fields; validators warn and ignore them. Remove these fields from canonical configs. Other unknown OpenVPN fields remain invalid.
- An optional array of containers and their expected networks for generic host preflight checks.
- An optional `gateway` section with identity and separate SSH/Cockpit bind addresses and ports. Keep `bind_address` as the backward-compatible fallback for both listeners; Gateway attachment is derived from the top-level `networks` inventory, not a Gateway-specific network list.
- `gateway.remote_access.openvpn` settings reference the external, private client profile. The external OpenVPN server allocates remote client addresses; validate pushed routes and session addresses without adding external routes/pools to the Podman network inventory.
- `gateway.remote_access.ssh_tun` uses `enabled`, `account`, `address_pool`, `authorized_keys_path`, and `max_sessions` when enabled. It identifies the dedicated SSH tunnel account and SSH TUN address pool. Allocate a unique point-to-point address pair and interface per session. The pool is not a Podman network declaration.
- OpenVPN client and multiple SSH TUN sessions may be active concurrently. Validate candidate routes/addresses against Podman CIDRs, other tunnel pools/endpoints, and relevant host/developer/corporate routes before installing state. Exact real profiles and CIDRs remain deployment inputs.
- Optional DNS records that map names to a target container and declared network. DNS records contain no protocol or port exposure declarations.
- Host paths for public `authorized_keys` files, including one file per application container. Private-key paths are forbidden.

Generic validation always validates the complete top-level Podman network inventory and all declared configuration relationships. It rejects malformed schema, invalid values, and references to undeclared networks or containers even when the referenced service is not yet deployed. Gateway host preflight is service-scoped: it checks Gateway host tools, credentials, host settings, declared Podman network prerequisites, and conflicting IPv4 host routes. Route checks include all routing tables and local-address routes, ignore default routes, and allow only exact connected routes or bridge-local addresses demonstrably matching inspected declared Podman networks. They do not require, inspect, start, or otherwise operate application containers or DNS targets. A service section must not silently install host packages or weaken host security policy.

Read-only Gateway `--check` validates configuration, Gateway prerequisites, and Podman network state only. It may list each configured DNS declaration as `pending readiness/unverified` based on configuration alone; it must not probe container existence, state, health, attachment, or addresses, and must not imply that a target is absent. Readiness-aware DNS refresh is a separate handoff after application deployment has checked service readiness; only that refresh may re-inspect Podman and publish current target addresses.

Representative shape; replace all deployment inputs and keep both existing runtimes disabled until their operator gates and target acceptance pass. The `remote_access` fields below match the current schema. The `dev.anatel` record shows the approved future suffix; `dns_records` is currently empty, and no WireGuard split-DNS integration exists.

```json
{
  "schema_version": 1,
  "gateway": {
    "name": "gateway",
    "bind_address": "127.0.0.1",
    "ssh_bind_address": "0.0.0.0",
    "cockpit_bind_address": "127.0.0.1",
    "ssh_port": 2222,
    "cockpit_port": 9090,
    "authorized_keys_path": "/etc/gateway/authorized_keys",
    "remote_access": {
      "openvpn": {
        "enabled": false,
        "profile_path": "/etc/gateway/openvpn/ERMXDF02.ovpn",
        "client_pool": "172.24.0.0/21",
        "profile_reviewed": false
      },
      "ssh_tun": {
        "enabled": false,
        "account": "gateway-tunnel",
        "address_pool": "198.18.0.0/24",
        "authorized_keys_path": "/etc/gateway/ssh_tun/authorized_keys",
        "max_sessions": 8
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
      "name": "backend.project-a.dev.anatel",
      "container": "project-a-backend",
      "network": "project-a-net"
    }
  ]
}
```
The `198.18.0.0/24` pool and `max_sessions: 8` above are illustrative test values, not production values; replace the pool after route-overlap review. Enabling SSH TUN requires all five fields: `enabled`, `account`, `address_pool`, `authorized_keys_path`, and `max_sessions`. The account must be `gateway-tunnel`; the key path is absolute, root-managed, outside Git, and read-only mounted at `/run/gateway/ssh_tun/authorized_keys`. Keep this allow-list separate from `gateway.authorized_keys_path` for Gateway login and from each application destination account's keys.

Public SSH keys must be supplied from root-managed host files outside Git, separated by Gateway login, SSH TUN, and application destination. Each application container may load multiple public keys from its configured `authorized_keys` file into a dedicated non-root destination account. Mount the file read-only. Deployment validates file ownership/mode and key syntax, then consumes or renders only public keys. Private developer keys remain on developer workstations. Host audit records changes to these files; PAM and operator-session controls are managed outside this host deployment and are not revalidated by it.

For each path, document owner, mode, mount mode, and backup/restore responsibility. SELinux is expected to be disabled by host policy; deployment must not change that policy.

`schema_version` is required and remains `1`; optional service sections and feature fields must remain backward-compatible. Validation must reject unsupported schema versions, duplicate network names, duplicate DNS names, malformed names/CIDRs, overlapping configured Podman networks, tunnel pools/endpoints or discovered routes that conflict with Podman or relevant host/developer/corporate routes, records referencing undeclared networks, and DNS records for a container outside the declared network. Permit intended exact managed routes and the connected Podman/tunnel routes needed for operation; do not reject default routes or necessary connected tunnel ranges wholesale. Existing Podman networks must match their declared subnet; never silently recreate or mutate a mismatched network. A missing declared Podman network is valid before apply and is reported as planned creation by read-only `--check`; apply creates it only after complete validation. An existing incompatible network or overlap with another Podman network is a hard error before any mutation. Validate the external OpenVPN profile path, ownership, mode, client configuration, assigned address, and candidate pushed routes before activation or reconnect.

The configuration contains logical identities, not permanent container IPs. Gateway bootstrap and preflight do not require DNS targets to exist or be running. At DNS publication or refresh, application deployment first confirms service readiness; the Gateway then re-inspects Podman and uses only a current address on the declared network. A configured target that is absent, stopped, or not ready is reported as pending, contributes no DNS record, and is never started by Gateway deployment. A running target without a valid address on the declared network also remains unpublished until application deployment resolves readiness. Invalid configuration and undeclared references remain hard errors. Never retain a previous address as a fallback.

## 5.1 Clean-host order and readiness-scoped handoff

The supported clean-host sequence is:

1. Validate and apply the shared Gateway using the versioned host configuration. The host may have no application containers at all, including no `nginx`, `webApp`, PostgreSQL, or DNS-target containers. Optional application container, route, and DNS declarations may already be present in that configuration; they are desired declarations, not runtime prerequisites.
2. The Gateway validates only Gateway host/tools/credential prerequisites and the complete declared Podman network inventory. Existing declared networks must exactly match their configured subnets. Missing networks are shown as planned creation by read-only `--check` and created during apply. The Gateway attaches to every declared network and never creates, starts, inspects, or changes application containers.
3. After Gateway health is established, application deployment stages an update to the same versioned host configuration and validates the complete staged file and existing network compatibility before mutation. It atomically installs that version while preserving unrelated objects and operator inputs, creates missing declared networks, and reconciles the existing Gateway to attach any newly declared networks. Only after Gateway reconciliation does application deployment create/start its application containers and NGINX. An incompatible existing network or invalid staged reference fails before config commit or other mutation.
4. Application deployment owns creation, startup, health/readiness, and failure handling for application containers and NGINX. Only after a target passes its declared readiness checks does application deployment request DNS publication for the active configuration revision and ready target identities.
5. The Gateway DNS refresh independently re-inspects the named containers and publishes only their current valid addresses on the declared networks. Absent, stopped, unhealthy, unattached, or otherwise not-ready targets remain pending and have no A record. DNS publication is staged, validated, and atomically replaced; it never fabricates an address or retains an old one as fallback.

The handoff is revision-scoped: application deployment identifies the exact active host-configuration revision and the targets it has independently confirmed ready. The Gateway rejects stale revisions and undeclared target/network references as configuration errors, but a declared target that is absent or not ready is pending rather than a bootstrap failure. The Gateway's own apply may succeed with pending DNS targets. App start/stop/replacement and readiness transitions must request refreshes so records are removed or updated. No background watcher is part of this plan: an unannounced runtime crash may leave a record until the next explicit refresh or Gateway restart, but no later generated DNS state may preserve that stale address. The status output must distinguish pending DNS from successful service readiness.

When application configuration changes add networks, the complete staged configuration is validated before commit; its atomic update preserves other sections and operator-owned inputs. Gateway reconciliation precedes application-container startup, so the Gateway is not duplicated and no application workload is started by Gateway code. If reconciliation or application activation fails, restore the prior managed configuration and generated Gateway state where feasible, report additive networks/resources that remain, and do not claim full rollback. A subsequent apply with the same desired state must converge without unnecessary restarts.

Version 1 generates only DNS A records, pointing directly to current target IPv4 addresses on their declared container networks. It does not generate AAAA records; IPv6 configuration and validation are out of scope for v1. Each network's configured Gateway address serves DNS to attached containers and tunnel clients. Tunnel clients must have routes to those network CIDRs. Developer-to-container access uses no service port mapping, DNAT, or SNAT. Developers with tunnel access can reach every service on every configured network, including databases.

## 6. Host and Container Responsibilities

### 6.1 Host deployment: Bash plus Quadlet

The host script should:

1. Require rootful Podman access and qualify the configured RHEL 9.8 / Podman 5.8.2 / Quadlet target. Verify package provenance and compatibility; do not install packages or alter host security policy implicitly.
2. Run a read-only preflight before any host mutation. Validate configuration, Gateway tools, paths, permissions, management-port availability, existing network definitions, conflicting IPv4 host routes, key inputs, Podman socket availability, SELinux mode, and Gateway service state. The route check includes all tables and local addresses, ignores default routes, and permits only exact managed connected routes or matching bridge-local addresses. Tunnel profile/session, route-allocation, and TUN-device checks are activation-scoped: they do not block the container-independent, offline base Gateway before tunnel activation is enabled.
3. Offer a validation-only mode that performs no writes, image builds, network changes, service restarts, or file creation. Any invalid input or unmet hard prerequisite must exit non-zero before mutation.
4. Build the Debian image from the checked-out repository `Containerfile`, with an explicitly versioned/pinned base image and reproducible package inputs. Never bake secrets or public-key data into image layers.
5. Create only missing networks in the global Podman inventory during apply, or verify existing Podman networks match their declared CIDRs before mutation. Read-only `--check` reports missing networks as planned creation. Do not connect application networks to one another.
6. Stage generated DNS, route, firewall, and Quadlet state in temporary files on the same filesystem, validate them, and install them atomically. Keep generated host state in dedicated paths, separate from operator-managed secrets and data.
7. Install/update the rootful Quadlet definition under the supported system location, reload systemd, and enable/start the generated service. Avoid restarting or recreating the gateway when desired configuration and image are unchanged.
8. Attach the Gateway to every network in the global `networks` array. Do not create links or routing between those networks; never delete an application network as part of normal deployment.
9. Mount the Podman Unix socket only at the path Cockpit Podman actually uses. Do not claim that a read-only socket mount restricts API authority. Verify SELinux is disabled; do not change its state or relabel the host socket.
10. Start and supervise each explicitly enabled tunnel. Use connected Podman routes for application CIDRs, routes through each owning tunnel for remote client prefixes, and a single deterministic host return next hop per prefix (or explicit tested policy tables). Preserve client source addresses and split routes; never forward between application networks. Provide a revision-scoped DNS refresh interface for the application deployment handoff after readiness; no generic background watcher is in scope.
11. Verify tunnel readiness only when activated, DNS syntax and current ready-target answers when targets are available, protocol- and port-independent forwarding, source-address preservation, symmetric replies, deterministic return routing, host-masqueraded container egress, SSH target authentication, Cockpit/Podman visibility, one interface per configured network, and Gateway service state. Missing application targets or pending tunnel runtime do not fail base Gateway bootstrap. On failed checks, restore prior Quadlet, DNS, route, and forwarding state where feasible.
12. Print a concise result with changed resources, planned network creations during check, pending DNS targets, Gateway service status, and recovery instructions. Never print secret contents or report pending application readiness as success.

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

### Phase 0: Confirm prerequisites and security gate

- Confirm the infrastructure owner's acceptance of the rootful Podman socket authority described in section 3.1.
- Record the requester's approval for unrestricted protocol/port access to every configured network, including databases. Authentication remains service-owned; external perimeter controls are assumed.
- Record the qualification baseline as RHEL 9.8, rootful Podman 5.8.2, Quadlet, SELinux disabled, required host packages, and image base digest. Verify the installed build and repository/vendor support without changing host security settings.
- The Layer 3 transport decisions are confirmed in section 3.2. Obtain deployment inputs: external OpenVPN profile and allocated client pool/routes, SSH TUN pool and restricted account/session policy, WireGuard pool/server address/endpoint/UDP bind/port/resolver, and supported client OS. The peer-admin workflow is implemented as a root-only Gateway CLI. The external OpenVPN server remains out of scope; WireGuard server runs in Gateway.
- Verify that active sessions expose enough addresses/routes for candidate validation and symmetric replies. Confirm whether the external profile uses inline certificate/key blocks, host-key storage, public-key input format, and whether perimeter rules restrict SSH bound to `0.0.0.0`. Cockpit remains loopback-only.
- Confirm the in-container service/process model and initial capability hypothesis.
- Stop implementation if a decision requires changing an architecture invariant; document the conflict for explicit approval first.

### Phase 1: Configuration and read-only preflight

- Add the versioned JSON schema and representative non-secret configuration.
- Host schema accepts only declared `dev.anatel` DNS names; `dns_records` remains empty. OpenVPN pushed-domain options belong to the external server/profile, not Gateway JSON. Schema version 1 accepts the retired OpenVPN JSON fields for compatibility, warns that they are ignored, and recommends removal; other unknown fields remain rejected.
- When deployment inputs are supplied, validate WireGuard server address/pool, endpoint, UDP port, resolver reachability, every top-level Podman CIDR, and overlap against host, Podman, LAN, and corporate routes before mutation.
- Implement strict schema/value validation and human-readable errors.
- Add shared read-only checks for the RHEL 9.8 / Podman 5.8.2 baseline, Quadlet, `jq`, source tree, every declared network/CIDR, disabled SELinux state, tunnel profile/session candidates, discovered routes, TUN device, route ownership, Podman socket, and host-wide prerequisites. Do not make pending tunnel-runtime checks block base Gateway bootstrap before a tunnel is enabled for activation.
- Prove invalid configuration, missing required files, occupied ports, conflicting route candidates, and mismatched existing networks fail before any state changes.

### Phase 2: Debian image and container startup

- Add the repository-built Debian image with pinned base and explicit package list: OpenSSH, DNSMasq, Cockpit, cockpit-podman, `iproute2`, WireGuard tools, and only required network diagnostics. Install the OpenVPN client when enabled.
- Add startup validation and the selected service-management units/scripts.
- Grant only capabilities proven necessary for WireGuard routing and packet forwarding; use `CAP_NET_ADMIN` only if target tests require it. Never use `--privileged`.
- Keep the OpenVPN profile, public-key, DNS, and server-private-key inputs as read-only runtime mounts; keep the WireGuard server private key root-owned outside Git and visible only to the WireGuard consumer.
- Generate peer private keys inside Gateway. Keep them only in memory for one-time delivery to a verified direct foreground `/dev/tty`; never persist or log them. If output fails, identify the pending peer by ID/public fingerprint and revoke it. Never retry or recover a generated private key.
- Build and run the image in the authorized disposable test environment with SELinux disabled and TUN support where available.
- Prove startup, shutdown, signal handling, tunnel failure reporting, DNS service, and replacement without loss of host identity.

### Phase 3: Quadlet lifecycle and network attachment

- Add the rootful Quadlet container definition and any network units needed for deterministic boot ordering.
- Publish only the configured WireGuard UDP listener on the explicit host bind/port, mapped to the same container port. No external firewall change is required by this plan; host port publication alone does not prove endpoint reachability.
- Use Bash to render/install only configuration that cannot be expressed safely as a static Quadlet file.
- Create or verify declared networks without joining application networks together.
- Enable the generated systemd service and prove a second deployment produces no unnecessary container replacement or service restart.
- Install one deterministic host return route per remote client prefix via a single selected Gateway next hop/interface; do not install conflicting copies of the same prefix via every application network. Preserve unrelated routes and roll back only route state owned by the Gateway/session. Validate whether policy tables are required on the target before adopting them.
- Prove adding/removing a declared gateway attachment does not delete the underlying application network or volume.
- Prove every configured network receives a Gateway interface, while removing a network from the global inventory never deletes the underlying network or volume.

### Phase 4: Routed developer access and DNS

- Resolve each configured target address with Podman network inspection, scoped to its declared network.
- Verify one Gateway interface exists on every network in the global top-level `networks` inventory. Never bridge application networks together.
- Connect the OpenVPN client to the externally managed server using the configured read-only profile. Do not change or install OpenVPN server configuration.
- Run the Gateway as an OpenVPN client of the externally owned server. The server allocates OpenVPN client addresses from its dedicated pool and the external owner routes each application CIDR to the Gateway VPN client.
- Support multiple simultaneous OpenSSH point-to-point TUN (`ssh -w`) sessions alongside OpenVPN. Restrict tunnel creation to a dedicated account. A session lifecycle hook allocates a unique interface/address pair, checks collisions, installs only that session's routes, and cleans up on disconnect/exit. Ordinary Gateway accounts cannot create tunnels.
- Enable forwarding from active remote tunnels to each configured application CIDR and stateful replies only. Podman-connected routes deliver application CIDRs over the attached Podman interfaces; route each remote-client prefix back through its owning tunnel. Permit every IP protocol and port, preserve client source addresses, and do not add DNAT/SNAT or application-to-application forwarding.
- Give developers split routes only for configured Podman destinations; preserve their normal default route, unrelated egress, and source address. Install a deterministic host return path via one Gateway next hop per client prefix. If target testing requires policy routing, use explicit owned policy tables/rules rather than conflicting same-prefix host routes via every Podman network.
- Reject overlaps among tunnel pools/endpoints, Podman CIDRs, and relevant host, developer-LAN, or corporate routes, while allowing intended exact managed routes and connected Podman/tunnel routes. Do not blanket-reject default routes or necessary connected tunnel ranges. Reject ambiguous client-prefix ownership across transports unless a separately approved explicit policy exists; do not auto-multihome.
- Validate OpenVPN pushed route/address changes on reconnect as a candidate before activation. Invalid candidates cause no route, forwarding, DNS, or service mutation and leave the last valid active state intact.
- Require the external owner to route every application CIDR via the Gateway VPN client. Stop acceptance if those routes are absent.
- Implemented: additive Gateway WireGuard server alongside OpenVPN client and SSH TUN. Configure all peers with `AllowedIPs` containing exactly every top-level Podman CIDR, including database networks. The resolver is a Gateway address within those routes. Never install a client default route.
- Install and own only the Gateway-side IPv4 address, routes, and forwarding state required for approved WireGuard peers. Preserve source addresses; add no NAT, DNAT/SNAT, inter-application forwarding, or per-service allowlist. Every configured peer must reach all configured Podman networks, including PostgreSQL; service credentials remain required.
- Peer inventory and lifecycle operations are implemented for peer public keys, explicit approval, active configuration, expiry, listing, and revocation. The CLI runs as container root. Every Gateway-container administrator is trusted for full network access. Isolated container WireGuard handshake and packet-forwarding test passed with kernel support; formal RHEL 9.8 / Podman 5.8.2 target-host acceptance remains pending.
- Keep the server private key root-owned, outside Git, persistent across restart, and mounted read-only only to the WireGuard consumer. Never log private material. Generate each peer private key inside Gateway and deliver it once to a verified direct foreground terminal. If delivery fails, revoke the pending peer and generate a replacement; never recover a stored copy.
- Do not expose a public admin HTTP/API. The admin CLI, approval reference, expiry, audit metadata, and one-time delivery behavior are implemented. TTY checks cannot prove that external terminal recording is absent; operators must use a trusted non-recording terminal.
- Permit new container-initiated egress to externally routable destinations through the normal Podman host route and masquerading. Verify external targets see the host egress address; do not route ordinary egress through the Development Gateway VPN.
- Generate DNSMasq A records only from current target IPv4 addresses. Listen for container and remote DNS queries on configured Gateway network and tunnel IPv4 addresses. Configure attached containers to use Gateway DNS and clients to use split DNS for declared container domains.
- Use exactly `dev.anatel` as the internal-only, non-public namespace. Add no AAAA records. Split DNS is OS-specific: Windows 11 NRPT rule; Linux systemd-resolved routing-only `~dev.anatel` with per-link resolver; macOS `/etc/resolver/dev.anatel` or an approved resolver configuration. WireGuard does not push DNS. Preserve other domains, default route, and global resolver behavior.
- Validate complete candidate DNS, route, forwarding, and session-allocation state before atomic installation. Preserve the last known-good state when validation fails; rollback only Gateway/session-owned state and retain unrelated administrator routes.
- Reconcile state idempotently on explicit apply and protocol lifecycle events. Do not install a generic background watcher. Do not tear down routes owned by another session or transport.
- On the authorized target, test two or more simultaneous SSH TUN developers, each with unique interfaces/IPv4 address pairs, while OpenVPN is connected; test each transport separately and both concurrently. Verify one session's exit cleans only its own allocation/routes. Resolve declared names using split DNS, reach arbitrary IPv4 protocols/ports, preserve source addresses, and receive symmetric replies. Test ProxyJump separately as TCP-only. From containers, test normal external egress and host masquerading. Inspect app-to-app isolation, route selection, no L4 filters, and no source NAT. Recreate a target and verify DNS updates without changing route ownership.
- Test WireGuard peers alone, alongside the OpenVPN client, and alongside SSH TUN. Verify approved-peer-only handshake, all-network IPv4 reachability, source preservation, no NAT/inter-network forwarding, correct DNS answers, host UDP publication, revoke/rotation, server-key persistence, restart/reboot recovery, and stale-state cleanup.

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

### Phase 7: WireGuard peer onboarding and split DNS

- Implemented: strict opt-in configuration, deployment preflight, conditional Quadlet UDP publication and read-only server-key mount, `NET_ADMIN` only when remote access is enabled, and root-only `gateway-wireguard peer` lifecycle CLI. Runtime remains disabled until deployment provides explicit values.
- Implemented: pending-peer generation, public metadata inventory, separate approval with reference and UTC expiry, listing, revocation, and sanitized public audit. Any Gateway-container administrator is trusted to grant peers access to every declared Podman network; no public admin HTTP/API exists.
- Implemented: peer private key generation inside Gateway and one-time direct-terminal delivery only when foreground stdin/stdout match `/dev/tty`. Pipes fail closed. If terminal output fails, identify and revoke the pending peer; never retry or recover its private key. Terminal TTY detection cannot prove that external recording is absent; operators must use a trusted non-recording terminal.
- Implemented: root-owned, persistent server key supplied by an explicit outside-Git path and mounted read-only to the Gateway. The implementation does not generate or default a production key path.
- Implemented: IPv4 pool/server/resolver validation, required deployment inputs, and overlap checks against declared Podman networks and other remote-access pools. Host routes and endpoint bind state are checked in preflight. No production values are selected.
- Implemented: conditional UDP host publication through Quadlet. External firewall/perimeter changes remain out of scope; publication does not prove reachability.
- Implemented: profiles include every declared Podman IPv4 CIDR, no default route, and a resolver comment for split DNS. WireGuard itself does not push DNS; OS configuration remains separate.
- Implemented: Windows 11 NRPT, Linux systemd-resolved routing-only `~dev.anatel`, and macOS `/etc/resolver/dev.anatel` recipes. Recipes preserve global DNS and default routes. Validate them on their respective operating systems.
- Pending acceptance: formal target-host acceptance for kernel tunnel and packet forwarding; concurrent transport tests, host return-routing behavior, reboot/revocation recovery, DNS resolution, and per-OS profile operation on the supported target. Isolated packet tests passed with the host WireGuard kernel module loaded; formal acceptance on the RHEL 9.8 / Podman target remains pending. Host `wg` binary absence is not a blocker; the image includes WireGuard tools.

#### Pending operator-design inputs

| Input | Status |
|---|---|
| WireGuard server address and dedicated peer IPv4 pool | Required preflight; no values approved |
| Public endpoint and host-published UDP port | Required; no values approved. `51820/UDP` is an unapproved suggestion only |
| DNS resolver IPv4 address and DNS service binding | Required; unset |
| Admin operation | Root-only CLI through Gateway container exec; no public HTTP/API. Any container administrator is trusted with all-network access. |
| Approval, audit, expiry, revocation | Implemented: explicit approval reference, UTC expiry, public metadata/audit, and peer-scoped revocation. Validate in runtime acceptance. |
| One-time private-key delivery | Implemented through a verified foreground `/dev/tty`; external terminal recording cannot be ruled out by TTY checks. Use only a trusted non-recording terminal. |
| Host UDP bind and Quadlet mapping | Required deployment input; explicit bind and port, no default. |

Recipes: [Windows 11](../recipes/wireguard-windows-11.md), [Linux](../recipes/wireguard-linux.md), and [macOS](../recipes/wireguard-macos.md).

## 9. Acceptance and Validation Matrix

| Area | Test | Pass condition |
|---|---|---|
| Pristine-host Gateway first | On a disposable clean host with no application containers or DNS target containers, use valid config that may include optional app container, route, and DNS declarations. Run `--check`, then Gateway `--apply`. | Check is read-only, reports each absent declared network as planned creation, and marks configured DNS declarations pending readiness/unverified from config alone; it performs no container probes. Apply creates missing declared networks and starts only the Gateway; it does not inspect, create, or start `nginx`, `webApp`, PostgreSQL, or any DNS target. Gateway service reaches healthy status with no fabricated DNS answers. |
| Missing networks | Declare valid Podman networks that do not yet exist, with no application containers present. Run `--check`, snapshot host/network state, then apply. | Check changes nothing and reports planned network creation. Apply creates each network with its declared subnet and attaches Gateway. A second check/apply is idempotent. An existing same-name incompatible network or overlapping Podman network fails before any mutation. |
| Failure before change | Snapshot service state, Quadlet files, DNS files, network definitions, volume IDs, key/secret hashes, and data sentinels. Run malformed config, duplicate names, undeclared references, overlapping CIDRs, missing required Gateway credentials, unavailable tools, occupied Gateway ports, and incompatible existing networks. | Each hard validation failure exits non-zero before modifying host files, networks, containers, service state, volume IDs, secrets, keys, or sentinels. Absent application targets alone are not a hard failure. |
| Validation-only mode | Run the documented check mode against valid and invalid configurations, including absent networks and declared DNS targets. | It performs no writes, builds, network changes, container existence/state/health/address probes, restarts, or file creation. It reports planned network creation and marks declared DNS records pending readiness/unverified without claiming target absence. |
| Offline base bootstrap | Run Gateway validation/bootstrap with tunnel activation disabled, no OpenVPN profile, no live TUN sessions, and no WireGuard secret. | Base Gateway checks remain container-independent and do not require network access or tunnel runtime state. Missing tunnel runtime prerequisites remain explicitly pending; they block only the corresponding tunnel activation, not base Gateway bootstrap. |
| Idempotence | Apply the same valid configuration twice. Compare container ID/start time, unit content, generated DNS content, network IDs, volume IDs, key/secret hashes, and data sentinels. | Second apply makes no unnecessary changes or restart. No persistent content changes. |
| Persistence | Seed a database/application volume and external secret/key files. Rebuild/recreate the gateway and rerun deployment. | Volume identity/data, secret bytes, SSH host keys, and permissions remain intact. Gateway image replacement does not own or delete app data. |
| Readiness-scoped DNS handoff | With optional DNS declarations present, run read-only `--check` before any app containers exist; then separately exercise the DNS refresh handoff with a target absent, stopped, or not ready, and after it passes app readiness. Include an undeclared name/network reference in a separate invalid configuration. | `--check` marks declarations pending readiness/unverified from config alone without probing containers. The separate refresh re-inspects actual Podman state, leaves absent/stopped/not-ready targets pending with no record, and publishes only the current valid network address after readiness. Gateway never starts a target. Invalid schema and undeclared references fail before mutation. |
| DNS refresh and stale records | Recreate a ready target with a different address, then stop/remove it and request refresh. Restart Gateway with the target absent. Query the managed DNS zone after each operation. | The record changes only to the current validated address and is removed when the target is no longer ready; no previous address is used as fallback on refresh or reboot. App lifecycle invokes refresh on readiness/stop/replacement. Unexpected crashes without a handoff may remain stale until explicit refresh or restart; no watcher is claimed. |
| Gateway all-network access | Inspect one Gateway interface per entry in the top-level Podman network inventory. Test that application service access occurs only after the app phase. | Gateway attaches to every configured Podman network. Its bootstrap does not require or operate application services. It is a trusted administrative component, not an isolation boundary. |
| Application and NGINX follow-up | After Gateway is healthy, deploy application stack and optional NGINX on a host config that adds a network, container, route, and DNS declaration. Validate a staged config update, then perform a second update with an invalid reference. | Valid changes preserve unrelated config objects, atomically update the active version, reconcile Gateway onto the added network before app startup, and deploy/readiness-check app and NGINX in their owning phase. Invalid changes fail before mutation. DNS/HTTP routes publish only after readiness. A second apply is idempotent. |
| Network isolation | Attempt direct app-to-app traffic without an explicit connection, excluding traffic initiated by the multi-homed Gateway. | Application networks remain separate and do not gain direct peer connectivity merely because the Gateway attaches to both. |
| Routed remote access | From clients on WireGuard, OpenVPN, and SSH TUN, reach services on every configured network using varied ports and IP protocols, including TCP, UDP, and ICMP. Inspect forwarding rules. | Any IPv4 protocol and port can pass from approved developer peers to all configured container CIDRs, including PostgreSQL networks. Reply traffic works. Rules contain no L4 protocol or port matches. Source addresses remain unchanged. There is no NAT, DNAT/SNAT, or application-to-application forwarding. |
| WireGuard peer lifecycle | Add, approve, rotate, revoke, restart, and reboot with multiple peers. Inspect server key ownership, peer inventory, logs, and active configuration. | Only approved public keys are active. Private peer keys are generated inside Gateway, delivered once through the approved authenticated channel, never persisted/logged, and not recoverable. Server private key is root-owned, outside Git, persistent, and visible only to WireGuard. Revoked peers cannot reconnect; restart/reboot does not restore revoked peers. Admin identity and actions are auditable. |
| WireGuard host listener | Inspect the generated Quadlet port mapping and test the configured endpoint from an authorized network. | The selected UDP port is published by the host to the WireGuard container. Port and endpoint match operator-approved inputs. No external firewall/perimeter change is required by this plan; report reachability only if measured. |
| WireGuard split DNS | On Windows 11, Linux systemd-resolved, and macOS, resolve approved names under `dev.anatel`, then query a public name and inspect routes. | OS-specific NRPT, routing-only `~dev.anatel`, or `/etc/resolver/dev.anatel` points only this suffix to the approved resolver. Internal answers are current A records with no AAAA. Public DNS and default routes remain unchanged. Cleanup removes only the recipe-owned rule. |
| Flow direction | From each remote transport, initiate flows to containers. Test replies for supported IP protocols. From containers, initiate flows to external targets. | Remote-initiated flows preserve source addresses and receive replies. Container egress works through host masquerading; external targets see the host address. |
| Route direction and symmetry | Inspect routes on Gateway, host, external OpenVPN server, developer clients, and target container return paths. Trace packets in both directions. | The external server routes Podman CIDRs to the Gateway OpenVPN client; OpenVPN developers receive those split routes through the server, while SSH TUN developers route them through their assigned SSH session. Gateway uses connected Podman routes for application CIDRs and routes each remote client prefix through its owning tunnel. The host has one deterministic return next hop per client prefix (or explicitly tested policy tables), with no duplicate conflicting same-prefix routes via every Podman network. No SNAT/DNAT is present. |
| Concurrent SSH TUN allocation | Keep at least two SSH TUN developers connected simultaneously and connect/disconnect sessions in varying orders while OpenVPN is active. Inspect interfaces, point-to-point pairs, and routes before and after each lifecycle event. | Each session receives unique non-overlapping addresses/interfaces and owns only its routes. Collision checks fail closed. Teardown removes that session's state only, including abnormal disconnect handling; other SSH sessions and OpenVPN remain usable. |
| Route/pool conflict rejection | Present candidate overlaps between WireGuard, OpenVPN, and SSH pools/endpoints, a Podman CIDR, and relevant host/developer-LAN/corporate routes. Also test intended exact managed routes, connected tunnel/Podman routes, and default routes. | Conflicting candidates are rejected before mutation. Intended exact managed/connected routes and default routes are not blanket-rejected. Existing unrelated routes are preserved. |
| OpenVPN reconnect candidate | Reconnect with unchanged routes, then with a changed valid pushed route, and finally with an overlapping/ambiguous pushed route. | Unchanged and valid candidates reconcile idempotently. The invalid candidate does not activate or alter current routes, forwarding, DNS, or service state; the last valid session remains in place or the tunnel fails closed without publishing unsafe routes. |
| Invalid route candidate rollback | Snapshot route tables, policy rules, forwarding rules, DNS, and active sessions; submit malformed, overlapping, or ambiguously owned route candidates. | Candidate validation occurs before any mutation. Rollback removes only candidate-owned changes and leaves unrelated administrator routes and other sessions unchanged. |
| Application-network isolation | Attempt direct forwarding between two application networks through the Gateway. | Gateway does not forward application-to-application traffic. Remote developer clients retain access to every configured network. |
| SSH forwarding | Connect using the documented VS Code Remote-SSH/ProxyJump configuration. Use separate gateway and destination keys. Attempt access with a valid gateway key but invalid destination key, then with valid destination credentials. | Forwarding succeeds. Target accepts/rejects based on its own credentials. Private keys remain on the developer workstation. Gateway public-key setup is distinct. |
| SSH TUN policy | Establish concurrent `ssh -w` tunnels with the dedicated account. Attempt tunnel setup with an ordinary gateway account and inspect effective `sshd` settings. | Only the dedicated tunnel account can create TUN sessions. Each client has a unique allocation, routes, and split DNS; ordinary Gateway login cannot create tunnels. No unintended agent, tunnel, or gateway-management exposure is introduced. |
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
- Compute and validate each tunnel/session candidate before changing routes or forwarding. Invalid candidates perform no route, forwarding, DNS, or service mutation; activation failures roll back only candidate-owned state and keep unrelated/admin routes and other sessions.
- Maintain explicit ownership for OpenVPN configuration/routes, each SSH TUN session's interface/address/routes, and the single deterministic host return route (or explicitly designed policy table). Repeated reconciliation is idempotent. A session teardown removes only that session's state; it must not remove another SSH client's or OpenVPN's routes.
- Do not add a generic background route watcher. OpenVPN reconnect and SSH TUN setup/teardown hooks are protocol lifecycle events with narrowly scoped ownership and validation.
- An absent, stopped, or not-ready declared DNS target is pending, not a Gateway preflight/apply error, and Gateway must never start it. DNS refresh publishes only current ready-target addresses and removes records for unavailable targets; it never retains a previous address as fallback. Preserve last-known-good generated state on unrelated activation failure only for records whose targets are still current and ready.
- Keep logs free of secret content. Do not put secret values in command-line arguments, generated unit files, build arguments, or image history.
- Report partial additive changes, such as a newly created network, if later activation fails. Do not present rollback as complete when host state remains changed.

## 11. Remaining RHEL 9.8 / Podman 5.8.2 Acceptance Gates

Implementation decisions and locally validated behavior are recorded in [gateway-implementation.md](gateway-implementation.md). The following questions remain open; answer them with evidence from a disposable RHEL 9.8 host using rootful Podman 5.8.2 before claiming acceptance:

1. Does the RHEL 9.8 / Podman 5.8.2 target pass vendor/package support and lifecycle tests? Record the exact kernel, Quadlet generator, package source, and SELinux state. The current host has the WireGuard kernel module available and loaded, and isolated container packet testing passed; RHEL 9.8 / Podman 5.8.2 target-host acceptance remains pending.
2. Can Cockpit access the approved rootful Podman socket on the target with SELinux disabled?
3. Can the Gateway run as an OpenVPN client while multiple SSH TUN developer sessions operate concurrently, with the minimum required device access/capabilities?
4. Do active tunnel sessions expose enough addresses/routes for conflict checks, unique SSH allocations, deterministic host return routing, and cleanup?
5. Does the external owner route every Podman CIDR via the Gateway VPN client, with developer split routes limited to those destinations?
6. Does the target support a single deterministic host next hop for container return traffic, or is explicit policy routing required?
7. Does ordinary Podman host egress support unrestricted container egress with the expected host masquerading?
8. Do OpenVPN route changes/reconnect, multiple SSH session lifecycle events, WireGuard kernel/peer lifecycle, per-OS split DNS, DNS refresh after container recreation, failure rollback, and health checks pass on the target platform?

Do not treat resolved configuration details, such as stopped-target handling or key-file paths, as open decisions. Do not claim a test passed unless it ran on the stated target.

## 12. Completion Criteria

The bootstrap is ready for review when:

- Host deployment and container startup are separate Bash-owned responsibilities.
- Quadlet controls the rootful Gateway lifecycle on RHEL 9.8 with rootful Podman 5.8.2.
- The Debian image builds from repository sources and contains no secrets.
- Network and DNS declarations come from versioned JSON configuration.
- The external OpenVPN server remains externally managed and allocates its client addresses; the Gateway is an OpenVPN client. The Gateway also runs the additive WireGuard server. Multiple SSH TUN developers have unique simultaneous sessions from a separate pool. No external OpenVPN-server deployment, DHCP, TAP, Ethernet bridging, or per-service forwarding is introduced.
- WireGuard peers receive split IPv4 routes to every top-level Podman CIDR, including PostgreSQL. WireGuard server key storage, peer approval/audit, one-time private-key delivery, rotation, revocation, and recovery behavior pass review without persisting peer private keys.
- OpenVPN client, WireGuard server, and SSH TUN can operate concurrently after conflict checks. The OpenVPN profile is referenced from JSON and mounted read-only from outside Git. External routing directs Podman CIDRs to the Gateway VPN client; Gateway application routes use connected Podman interfaces, and remote client prefixes return through their owning tunnel.
- Host/container return routing is deterministic and does not install conflicting same-prefix routes via every Podman network. Any required policy tables are explicit, owned, and validated on the qualification host.
- Route pools/endpoints and relevant host/developer/corporate routes are conflict-checked. OpenVPN reconnect candidates are revalidated before activation. Per-session SSH allocation, route ownership, idempotent reconciliation, cleanup, and rollback are verified without a generic background watcher.
- Every configured developer CIDR has routed access to every configured container CIDR through the Gateway, for any IP protocol and port.
- Developer-initiated traffic receives symmetric replies with source addresses preserved. Container egress reaches externally routable destinations through host masquerading.
- Application networks remain isolated from each other; the Gateway does not forward between them.
- DNSMasq resolves declared `dev.anatel` names to current container addresses, and clients can query it through WireGuard, OpenVPN, or SSH TUN. DNS returns A records only. Windows 11, Linux, and macOS split DNS routes only this suffix and preserves public DNS.
- No DNAT, SNAT, or per-service port/protocol allowlist is used for remote developer access.
- Developer clients receive only configured Podman split destinations; their default route, normal container egress, and client source addresses remain unchanged. Ambiguous same-prefix ownership across transports fails closed unless an explicit approved policy exists.
- Invalid input fails before host or service changes.
- Repeated deployment preserves application data, secrets, SSH host identity, and volumes.
- SSH forwarding preserves destination authentication.
- Cockpit Podman works over the Unix socket with no TCP API and no `--privileged`.
- Reboot recovery and exact required capabilities are proven on a disposable RHEL 9.8 / Podman 5.8.2 host.
- Tunnel routing, full-protocol forwarding, DNS, Quadlet lifecycle, and the requested SELinux-disabled host state are proven on disposable RHEL 9.8 with rootful Podman 5.8.2.
- Security tension, open decisions, test environment, and operator recovery steps are recorded.

## 13. Current Status

All remote-access transports remain disabled in checked-in config. The current host probe reports kernel `5.14.0-687.56.1.el9_8.x86_64`, Podman `5.8.2`, Python `3.14.8`, `/sys/module/wireguard` present, an installed WireGuard module found by `modinfo`, and `/dev/net/tun` present. The host `wg` binary is unavailable, but is not required: the Gateway image includes `wireguard-tools`. Kernel support is no longer a blocker for container-only tests.

The isolated WireGuard container-only packet test on 2026-10-20 passed a real handshake, HTTP 200 responses from two test apps, DNS, client-source preservation, and inter-network blocking. It published no host UDP port and used no host return route or production inputs. This permits starting or rerunning isolated functional tests; it does not establish deployed remote-client or target-host acceptance.

### Pending blockers for production/deployed remote-client acceptance

- **OpenVPN:** Checked-in config has `enabled: false`, a profile path, and `client_pool`; endpoint is not configured, and `profile_reviewed: true` requires explicit configuration after human review. External route and return-path evidence is also required. No profile was opened or inspected.
- **SSH TUN:** Checked-in config has `enabled: false` and lacks required `account`, `address_pool`, `authorized_keys_path`, and `max_sessions`. Live peer authentication and client input are required.
- **WireGuard:** Checked-in config has `enabled: false` and lacks required `host_bind_address`, `listen_port`, `endpoint`, `address_pool`, `server_address`, `dns_server`, and `server_private_key_path`. These are required for deployed endpoint/client functional acceptance; isolated tests used test-only settings.
- **Routing and client acceptance:** Provide external route and return-path evidence, then validate remote-client routing, DNS, concurrent transports, and relevant client prerequisites. External firewall changes are not required by the approved plan.

Keep approved `192.168.9.0/24`; host network overlap is not an implementation blocker. Run read-only conflict preflight before any real apply. No profile access, deployment, or host mutation occurred. Use [gateway-implementation.md](gateway-implementation.md) for current implementation details.