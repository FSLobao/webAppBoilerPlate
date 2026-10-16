# Application Deployment and Operations Plan

**Status:** Design plan; application lifecycle is not implemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)
**Related plans:** [HTTP Proxy](http-proxy-plan.md), [Application Stack](application-stack-plan.md), [Gateway Bootstrap](gateway-plan.md)

## 1. Goal and Ownership

Define repeatable deployment and day-two operations for application services on the RHEL 9.8 / rootful Podman 5.8.2 qualification target with SELinux disabled by explicit decision. Host deployment scripts must verify this state and must not change host security settings. Keep application lifecycle separate from the shared Development Gateway lifecycle. The clean-host order is Gateway bootstrap first; application services and optional NGINX HTTP proxy deploy only after Gateway is healthy. Use maintained, efficient Linux images for the Gateway and application containers; prefer Debian or Alpine. This plan covers networks, service definitions, volumes, external secrets, image updates, health, rollback, backups, and handoffs to the Development Gateway and optional HTTP proxy.

The standalone Debian File Gateway recipe remains a reference for future containerized deployment. Its Debian host bootstrap is not for use on the RHEL host.

Use rootful Podman Quadlet for long-running application containers and the shared gateways. Keep host timers and one-shot maintenance jobs as explicit systemd units managed by the same deployment, rather than introducing Compose as a second lifecycle system.

## 2. Resource Ownership

| Resource | Owner | Required boundary |
|---|---|---|
| RHEL host, Podman, storage capacity, host security policy | Infrastructure | Developers do not need routine host administrator access. |
| Application containers, networks, database volumes and health state, destination SSH accounts and public keys | Application deployment | Do not delete or rewrite persistent state during ordinary updates. Preserve per-developer destination authentication. |
| Development Gateway, its SSH identity, and generated DNSMasq records | Development Gateway deployment | Application deployment must use a documented handoff; it must not edit Gateway-owned files directly. |
| Public HTTP routes | Application deployment through optional HTTP proxy | Current v1 requires explicit `listen_address` and `http_port` when `http_proxy` is enabled; selected values are `0.0.0.0` and `8080`. The external perimeter provides TLS, public DNS, user authentication, and forwarding. |
| Published non-HTTP services | Application/service deployment | Explicit host bind address, protocol, and published port; service authentication and perimeter controls remain required. Developer reachability through the Development Gateway does not require host publication. |
| Secret values and backup destination | Infrastructure/application owners | Keep outside Git and images; mount only into required consumers. |

Keep `config/host_config.json` as the source of truth for every Podman application and database network. The top-level `networks` array contains only these Podman networks, not VPN routes/address pools, host interfaces, or physical/host network attachments. Require `schema_version: 1`; keep feature sections optional and backward-compatible. The minimum config contains host settings and the Development Gateway. Add optional sections for `http_proxy`, applications, PostgreSQL, TUS file transfer, NGINX file sharing, direct non-HTTP service publication, and backups. Create only resources declared by enabled sections. Shared preflight always validates the full Podman network inventory; service-specific preflight and apply run only for declared/enabled sections. Do not create duplicate network sources of truth.

The shared Development Gateway attaches to every network in the top-level inventory, including database networks. There is no separate per-service approval workflow for Gateway reachability. This makes the Gateway a trusted, multi-network administrative component; Podman network isolation does not protect an application from a compromised Gateway. Keep application credentials separate and rely on service authentication as well as the external perimeter. The Podman network `shared` is a bridge for its attached containers, not a physical/host interface or a VPN route/pool. Gateway preflight and apply must not require or operate application containers; declared app resources may be absent during Gateway bootstrap.

### Requested initial topology

The current config declares `shared` (`192.168.9.0/24`) and `webApp` (`192.168.8.0/29`) as Podman networks. Gateway attaches to both networks; NGINX uses `shared`; the combined `webApp` container and PostgreSQL use both networks. This matches the all-networks Gateway contract. The requester accepts direct communication among shared-network members and relies on service authentication.

Application deployment owns creating each unique app network. It updates the shared top-level `networks` inventory and reconciles the existing Gateway, which attaches to every declared network. It must not maintain a second Gateway network list or create another Gateway. Future app deployments must find and reuse the healthy Gateway and compatible existing networks. Gateway host preflight now checks networks without requiring declared containers to exist, and Gateway apply never starts application or DNS-target containers. The readiness-scoped DNS refresh handoff and NGINX runtime deployment are not implemented yet.

The v1 validator accepts `http_proxy` routes and static `gateway_address` fields. The approved initial addresses are `192.168.9.2` and `192.168.8.2`. An enabled `http_proxy` section means that NGINX/routes are desired and statically validated; it does not mean NGINX or its upstreams are deployed or runtime-ready. NGINX runtime deployment and target-host Quadlet acceptance remain unimplemented.

### Clean-host deployment sequence

1. Validate the complete versioned host config. Malformed schema, invalid values, duplicate declarations, and references to undeclared networks or containers are hard errors, even if the referenced service is not yet deployed.
2. Deploy and verify the shared Development Gateway using Gateway-scoped host/tool/credential prerequisites and the complete declared Podman network inventory. Missing declared networks are reported as planned creation in read-only check and created during apply. Existing networks must match config; an incompatible or overlapping network fails before mutation. Gateway must not require, create, start, or inspect `nginx`, `webApp`, PostgreSQL, or DNS-target containers.
3. After Gateway readiness, application deployment stages any application changes to the same host config, including networks, containers, routes, and DNS declarations. Validate the complete staged config and existing network compatibility before an atomic replacement. Preserve unrelated sections, operator inputs, secrets, and other objects byte-for-byte where untouched; do not overwrite concurrent edits. Create missing declared networks and reconcile the existing Gateway for any added network before creating/starting application workloads.
4. Application deployment owns creation, dependency ordering, startup, health/readiness, and rollback for application containers and NGINX. Do not publish public routes or development DNS just because `http_proxy.enabled` or a DNS declaration exists.
5. After each configured target passes its application-owned readiness checks, send the active config revision and ready target identities through the narrow Gateway DNS handoff. Gateway re-inspects Podman and publishes only the current valid address on the declared network. Absent, stopped, unhealthy, unattached, or otherwise not-ready targets remain pending and have no published record; Gateway never starts them.

When Gateway reconciliation or an application operation fails, restore the prior active host-config version and managed service/Gateway state where safe, and report additive networks, volumes, images, or data that remain. A mismatch in an already existing declared network is detected before config commit or other mutation. Preserve and report the last known-good app routes and DNS on invalid candidates only if their targets remain current and ready; never retain a stale address as fallback. Repeat apply must converge without unnecessary restarts. On reboot, Gateway starts independently of app targets; application Quadlet units start only after Gateway/network prerequisites, and successful app readiness triggers the same DNS handoff. App stop/failure/replacement must request refresh so managed DNS records are updated or removed; there is no background watcher, so an unexpected crash can leave a record until refresh/restart.

## 3. Desired-State Declaration

Use structured, versioned configuration rather than shell-sourced files or ad hoc text parsing. Candidate fields:

- schema version and application identity;
- image references and immutable version/digest policy;
- service names, internal ports, health checks, and network membership;
- application and database network CIDRs, with overlap validation;
- persistent volume names and mount paths;
- secret file references, required owners/modes, and consuming services;
- developer public-key references and the application destinations authorized to accept them;
- public routes and development DNS/SSH exposure declarations;
- optional NGINX listener address and published host port (both required by current v1 when `http_proxy` is present; selected values are `0.0.0.0:8080`, mapped to container port `80`), plus the initial `webApp` `/app/` SPA and `/app/api/` routes to the same `webApp:8000` listener;
- explicit host bind address, protocol, and published port for each end-user non-HTTP service; developer access through the Gateway does not require these host publications;
- DNS records for containers and Gateway DNS addresses for each Podman network, with remote split-DNS suffixes;
- PostgreSQL major version (default `18`), configurable per instance;
- optional TUS and NGINX file-sharing routes, with a default 1 GB maximum uploaded file size and no NGINX rate limit;
- one root-managed public `authorized_keys` file path per SSH-enabled application container and its dedicated non-root destination account;
- eventually, a `database_backups` entry per PostgreSQL instance with separate working-repository volume and completed-export host mount, plus full and incremental schedules. Proposed fields are documentation-only and unsupported by the current runtime validator.

Configuration contains references and metadata, not secret values or permanent container IPs. The optional HTTP proxy and application services are absent unless their optional config sections are enabled.

Example configuration for the selected initial `webApp` HTTP application; additional HTTP applications may declare their own upstreams and ports. The actual top-level `networks` array must list every Podman network used by the host. The backup configuration shape appears in the Application Stack Plan as a planning-only proposal and is not accepted by the current runtime validator:

```json
{
	"http_proxy": {
		"enabled": true,
		"listen_address": "0.0.0.0",
		"http_port": 8080,
		"routes": [
			{
				"prefix": "/app",
				"frontend": "webApp",
				"frontend_port": 8000,
				"api_prefix": "/app/api/",
				"backend": "webApp",
				"backend_port": 8000
			}
		]
	},
	"postgres_major": 18
}
```

The existing nested route shape retains the frontend/backend upstream fields for the selected initial application, but both resolve to the same combined `webApp:8000` FastAPI listener. FastAPI serves the built SPA at `/app/` and API routes at `/app/api/`; there are no separate frontend/API listeners or unresolved port inputs for this initial stack. Other HTTP applications may configure their own upstreams and ports; `webApp:8000` is not a global proxy restriction.

### HTTP identity and access trust

The external perimeter authenticates end users, removes or replaces client-supplied identity fields,
and injects the trusted `X-USER` identity fields. The application uses those fields to authorize
protected operations; NGINX only proxies and is not a login/authentication engine. The application
must reject missing or untrusted identity on protected endpoints. No runtime authentication or
authorization implementation is claimed here.

Because the selected NGINX host listener binds `0.0.0.0:8080` and the Development Gateway permits
direct service access, deployment must gate protected HTTP routes on either effective ingress
restriction to the trusted perimeter or verified perimeter-to-application identity provenance.
Neither network CIDR nor an unverified raw `X-USER` value proves authentication. The exact
`X-USER`-field allowlist and provenance mechanism remain unresolved implementation prerequisites;
do not invent additional identity header names.

## 4. Lifecycle Contract

### Preflight

- Validate schema, resource names, configured CIDR overlap, image references, application-phase host prerequisites including SELinux disabled, secret paths/permissions, storage paths, port binds, and existing resource compatibility before mutation. Application lifecycle checks apply only in this phase; they are not prerequisites for Gateway bootstrap.
- Fail on an existing network, volume, or service whose observed identity/configuration conflicts with the declaration. Do not silently recreate or take ownership.
- Check that required secrets exist without printing their contents.
- Keep a snapshot of service definitions and active state needed for rollback.

### Apply

- Starting only after a healthy Gateway is present, build or pull pinned images, create only missing declared networks and volumes, install service definitions atomically, and start dependencies in an explicit order. Reuse the existing Gateway; do not deploy a duplicate.
- Wait for dependency readiness and application health before publishing routes or development DNS records. Config declarations alone are not readiness.
- Update HTTP proxy routes through its supported deployment interface only after route targets pass readiness. The flag `http_proxy.enabled` expresses desired declaration and validation, not implemented or successful runtime deployment.
- Configure containers to use the Development Gateway DNS address on their network. Publish split-DNS rules for configured container domains to remote OpenVPN and SSH TUN clients.
- Notify the Development Gateway after a declared development target is ready and its current network address is known. The handoff carries the active config revision and ready target identities; Gateway independently re-inspects Podman, rejects stale revisions/undeclared references, and emits records only for current valid addresses. Missing, stopped, unhealthy, or not-ready targets stay pending with no record and are never started by Gateway. Do not edit Gateway-owned DNS files directly.
- On stop, failed readiness, or replacement, invoke DNS refresh after the application's state transition so obsolete records are removed or updated. No background watcher is assumed; document the window in which an unannounced crash may leave DNS stale until an explicit refresh or Gateway restart.
- Load destination `authorized_keys` inputs from root-managed public-key files outside Git. Default to `/etc/gateway/application-keys/<container>/authorized_keys`, with one file per SSH-enabled container and multiple public keys per file. Mount each file read-only at `/home/<account>/.ssh/authorized_keys` for a dedicated non-root destination account. Validate owner, mode, file type, and key format before apply. Never copy private keys to the host or containers.
- Host audit records changes to the root-managed public-key files. PAM authentication and operator-session logging are provided by the host security layer and are not managed or tested by this deployment.
- Backups are an external host-operated feature, not a host job inside a backup server. The planned host systemd full/incremental timers invoke one fixed, root-managed local entrypoint; it uses constrained `podman exec` to run the version-pinned pgBackRest installed in the PostgreSQL image as OS account `postgres`. Do not expose the rootful Podman socket/API to a remote backup server or collector.
- Use three distinct storage responsibilities: live `PGDATA`, a writable working-repository volume, and a writable host-mounted completed-export volume. The working repository must be separate from `PGDATA` and the completed export. PostgreSQL-side backup/publication steps write to the working repo and completed-export mount; there is no read-only completed-backup mount and no local fallback.
- Default to monthly full and weekly incremental schedules, serialized under one lock with bounded timeout and no overlap/double-run. A coinciding full replaces that run's incremental. A missing/wrong mount, insufficient space, source-volume full condition, or permission failure is fatal and observable.
- Before publication, require successful backup completion and a supported consistent repository-generation snapshot that excludes concurrent pgBackRest backup/archive writers and includes the selected backup chain, metadata/manifests, and required consistency WAL. The working-repository/snapshot staging volume is distinct from completed exports. Copy a full repository generation to a separate hidden, transient transfer-staging directory on the completed-export filesystem, verify it, flush as supported, then atomically rename within that filesystem under a unique generation identity or write a completion marker after verification. This destination-local staging area is not the working repository. Cross-volume rename is not atomic; collectors consume only completed names/markers. Published generations are immutable and never overwritten or edited. Never manually prune, edit, or rename live repository components.
- Keep prior publications and source chain on failed backup/copy; cleanup is limited to the current run's failed staging directory. Do not delete repository sources until external acknowledgement and dependency-aware retention permit it. Set encrypted collector transport/storage, scoped credentials and destination path, retention/acknowledgement, logging, and failure alerts. Checksums are not a restore test. Full-repository snapshot exports trade simple safe dependency preservation for potentially high storage and transfer use; they do not promise incremental transfers.
- There is no planned continuous WAL publication or PITR guarantee. Scheduled full/incremental jobs provide weekly recovery points if successful. pgBackRest-required consistency WAL is included in each publication; optional PITR/WAL export requires a separate explicit decision.
- Restore remains manual, private, and pgBackRest-based; validate published generations with restore drills into disposable targets, including parent-chain recovery. `pg_dumpall` may be retained as an optional logical portability/manual export, not the primary incremental backup/restore path. No automatic restore during deployment.

### Failure and rollback

- Preserve the last known-good service configuration and image reference until health checks pass.
- On failure, restore service definitions and image versions where safe. Do not restore a backup over a live volume automatically.
- Report additive resources that remain after a failed apply. Do not claim full rollback if networks, volumes, images, or data changed.
- If config, network, route, service, or DNS activation fails, keep or restore the previous active version and known-good app/Gateway state where possible. Do not roll back unrelated operator inputs. A newly created network may remain after failure and must be reported; never delete an app network merely to simulate rollback.
- Never prune unrelated Podman resources or delete application data, secrets, Gateway state, or host SSH keys.

### Remove and decommission

- Separate service removal from network/volume/data deletion.
- Require explicit operator approval and owner confirmation before deleting persistent volumes or backups.
- Remove only resources bearing the application's exact declared identity; preserve shared Gateway resources.

## 5. Secrets, Storage, and Recovery

- Keep secret and public-key source files outside Git with documented owner, group, mode, rotation process, and consumer. Store app keys under `/etc/gateway/application-keys/<container>/authorized_keys` by default, with one file per SSH-enabled container and multiple public keys per file. Mount each file read-only at `/home/<account>/.ssh/authorized_keys`. Require root-controlled key-file writes; reject unexpected symlinks or ownership/mode changes and never overwrite source files. Host audit records key-file changes; PAM controls remain external to this plan.
- Mount secrets read-only and only into services that use them. Do not copy them into images, generated public configs, or logs.
- Document the purpose, owner, mount path, backup method, collector acknowledgement/retention, and manual restore procedure for each of `PGDATA`, the working repository, and completed exports.
- Test recovery from a published generation into a disposable volume before production acceptance. A successful backup command or checksum alone is not proof of recoverability.

## 6. Operations and Observability

- Provide operator-visible service status, logs, health state, image identity, and recent deployment outcome.
- Define log destination, retention, rotation, and redaction. Never log secret contents or credentials embedded in connection strings.
- Define image update cadence, vulnerability review, pinning, and rollback ownership.
- Define service restart and reboot behavior through Quadlet. Define both backup timer schedules, mount dependencies, lock/overlap handling, hidden publication staging, collector completion/acknowledgement, log retention, and failure alerting.
- Keep advanced metrics/tracing optional unless an operational owner and retention target exist.

## 7. Implementation Phases

1. Resolve the backup publication/snapshot mechanism, deployment ownership, distinct working/completed host paths, secret policy, collector acknowledgement, retention, and database recovery objectives.
2. Define a versioned app manifest and read-only preflight with failure-before-change tests.
3. Implement network, volume, and service lifecycle after the shared Gateway is healthy, with idempotence and explicit ownership checks. Add/update networks, containers, routes, and DNS in the shared versioned host config through staged validation and atomic replacement; preserve unrelated objects and operator inputs.
4. Reconcile the existing Gateway for newly declared networks before starting app workloads. Integrate readiness, health checks, route publication, and backup scheduling.
5. Integrate HTTP proxy route updates and revision-scoped Development Gateway DNS refresh without direct edits to their owned state.
6. Validate update, failure rollback, reboot, backup/restore, secret preservation, and isolation on the authorized disposable RHEL 9.8 / Podman 5.8.2 host with SELinux disabled. Do not change host security settings.

## 8. Acceptance Checks

- Repeated apply is idempotent and does not restart unchanged services unnecessarily.
- Invalid configuration or missing secrets fail before host/service mutation.
- Network and volume identities, database sentinels, secret bytes, and permissions survive app-container replacement.
- A newly recreated development target gets a fresh DNS address only after readiness; stale records are removed according to the Gateway contract.
- On a pristine host, Gateway `--check` is read-only, reports missing networks as planned creation, and marks configured DNS declarations pending readiness/unverified from configuration alone without probing containers; Gateway apply creates networks and reaches readiness without any application containers or app operations. Readiness-aware DNS status and publication occur only through the separate post-readiness handoff.
- After Gateway is healthy, application and optional NGINX deployment creates and readies its own containers, atomically updates the shared config while preserving unrelated inputs, and reconciles the existing Gateway for added networks. A malformed staged update or incompatible existing network fails before mutation.
- `http_proxy.enabled` validates desired NGINX/routes only. It never counts as runtime deployment or readiness; public routes appear only after NGINX and upstream readiness.
- Reboot starts Gateway without app DNS targets, then application services independently satisfy their dependencies/readiness and refresh DNS. Stop, failure, and replacement handoffs remove/update managed DNS without retaining old addresses.
- VS Code ProxyJump reaches the declared application destination, and that destination accepts or rejects the developer key independently of Gateway authentication.
- Public routes become active only after application health passes.
- Failure during service start, route update, DNS refresh/routing handoff, backup, or publication has documented recovery without overwriting live database data or losing prior published generations/source chains.
- Backup restore and decommission procedures are proven against disposable resources.
- Host full/incremental timers invoke only the controlled local operator entrypoint; a shared lock prevents overlap/double-run. Missing/full storage fails without fallback. Failed publication cannot appear in collector-visible completed generations, and prior publications/source chains remain intact.
- Collector acceptance consumes only verified final generation names/completion markers, acknowledges retained data, and uses encrypted transport/storage with scoped credentials. Checksums are supplemented by a successful restore drill from a published full-plus-incremental chain.
- No application update exposes the Podman API, changes host SELinux state, or removes unrelated resources.

## 9. Remaining Implementation Inputs

- Name the authorized production deployment operators and their audit path.
- Supply actual Podman network names, CIDRs, Gateway interface/DNS addresses, and configured container domains. Runtime tunnel routes must be discoverable and must not overlap these networks.
- Select non-root UID/GID values and writable paths for each image. The qualification host requires SELinux disabled; deployment must not change that state.
- Preserve the selected HTTP proxy bind `0.0.0.0:8080`; serve the SPA and API from the single `webApp:8000` listener. Keep database credentials readable only by the FastAPI process.
- Specify and validate three distinct PostgreSQL storage responsibilities (live `PGDATA`, working repository volume, completed-export host mount), with required capacity and write permissions. Keep the pgBackRest working repository on a volume distinct from completed exports; use a separate hidden, destination-local transfer staging directory only for atomic publication. Missing or full mounts/volumes must fail without a local fallback.
- Implement and test a narrow Development Gateway DNS refresh handoff. Do not edit Gateway-owned DNS files directly.
- Select the supported Node.js build version and TUS account/storage details. Keep the default 1 GB file limit configurable.
