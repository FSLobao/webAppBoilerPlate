# Application Deployment and Operations Plan

**Status:** Design plan; application lifecycle is not implemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)
**Related plans:** [Application Gateway](application-gateway-plan.md), [Application Stack](application-stack-plan.md), [Gateway Bootstrap](gateway-plan.md)

## 1. Goal and Ownership

Define repeatable deployment and day-two operations for application services on the RHEL 9.8 / rootful Podman 5.8.2 qualification target with SELinux disabled by explicit decision. Host deployment scripts must verify this state and must not change host security settings. Keep application lifecycle separate from the shared Development Gateway lifecycle. Use maintained, efficient Linux images for the Gateway and application containers; prefer Debian or Alpine. This plan covers networks, service definitions, volumes, external secrets, image updates, health, rollback, backups, and handoffs to the two gateways.

The standalone Debian File Gateway recipe remains a reference for future containerized deployment. Its Debian host bootstrap is not for use on the RHEL host.

Use rootful Podman Quadlet for long-running application containers and the shared gateways. Keep host timers and one-shot maintenance jobs as explicit systemd units managed by the same deployment, rather than introducing Compose as a second lifecycle system.

## 2. Resource Ownership

| Resource | Owner | Required boundary |
|---|---|---|
| RHEL host, Podman, storage capacity, host security policy | Infrastructure | Developers do not need routine host administrator access. |
| Application containers, networks, database volumes and health state, destination SSH accounts and public keys | Application deployment | Do not delete or rewrite persistent state during ordinary updates. Preserve per-developer destination authentication. |
| Development Gateway, its SSH identity, and generated DNSMasq records | Development Gateway deployment | Application deployment must use a documented handoff; it must not edit Gateway-owned files directly. |
| Public HTTP routes | Application Gateway deployment | NGINX listens on configured host port `8080` by default; the external perimeter provides TLS, public DNS, and forwarding. |
| Secret values and backup destination | Infrastructure/application owners | Keep outside Git and images; mount only into required consumers. |

Keep `config/host_config.json` as the host-wide source of truth for every application and database network. Require `schema_version: 1`; keep feature sections optional and backward-compatible. The minimum config contains host settings and the Development Gateway. Add optional sections for the Application Gateway, frontend, backend, PostgreSQL, TUS file transfer, NGINX file sharing, and backups. Create only resources declared by enabled sections. Shared preflight always validates the full network inventory; service-specific preflight and apply run only for declared/enabled sections. Do not create duplicate network sources of truth.

The shared Development Gateway attaches to every network in the top-level inventory, including database networks. There is no separate per-service approval workflow for Gateway reachability. This makes the Gateway a trusted, multi-network administrative component; Podman network isolation does not protect an application from a compromised Gateway. Keep application credentials separate and rely on service authentication as well as the external perimeter.

### Requested initial topology (contract conflict pending resolution)

The current config declares `shared` (`192.168.7.0/24`) and `webApp` (`192.168.8.0/29`). Gateway attaches to both networks; NGINX uses `shared`; the combined `webApp` container and PostgreSQL use both networks. This matches the all-networks Gateway contract. The requester accepts direct communication among shared-network members and relies on service authentication.

Application deployment owns creating each unique app network. It then adds the network to the global inventory and `gateway.networks`, and reconciles the existing Gateway rather than creating another one. Future app deployments must find and reuse the Gateway and existing networks. The host preflight requires declared networks and containers to exist before a full Gateway check can pass; application lifecycle and NGINX deployment are not implemented yet.

The v1 validator accepts `application_gateway` routes and static `gateway_address` fields. The approved initial addresses are `192.168.7.2` and `192.168.8.2`. NGINX runtime deployment and target-host Quadlet acceptance remain unimplemented.

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
- optional NGINX listener address and published host port (default `8080`, mapped to container port `80`), plus `/app` frontend and `/app/api/` backend routes;
- DNS records for containers and Gateway DNS addresses for each Podman network, with remote split-DNS suffixes;
- PostgreSQL major version (default `18`), configurable per instance;
- optional TUS and NGINX file-sharing routes, with a default 1 GB maximum uploaded file size and no NGINX rate limit;
- one root-managed public `authorized_keys` file path per SSH-enabled application container and its dedicated non-root destination account;
- a `database_backups` entry per PostgreSQL instance, with monthly default `schedule`, host-mounted `remote_mount`, and read-only `container_path` shared with PostgreSQL.

Configuration contains references and metadata, not secret values or permanent container IPs. The Application Gateway and application services are absent unless their optional config sections are enabled.

Example service configuration; the actual top-level `networks` array must list every Podman network used by the host:

```json
{
	"application_gateway": {
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
	"postgres_major": 18,
	"database_backups": [
		{
			"postgres_container": "project-a-postgres",
			"schedule": "monthly",
			"remote_mount": "/mnt/remote-backups/project-a",
			"container_path": "/backups"
		}
	]
}
```

`schedule` uses systemd `OnCalendar` syntax and defaults to `monthly`. `remote_mount` names host-mounted storage. Mount it read-only in PostgreSQL at `container_path`; the host backup job writes to the host path. Deployment logs an error and fails the backup job if the mount is unavailable.

The frontend and API route to the same `webApp` container. NGINX needs separate internal frontend and FastAPI ports; values remain unprovided.

## 4. Lifecycle Contract

### Preflight

- Validate schema, resource names, configured CIDR overlap, image references, host prerequisites including SELinux disabled, secret paths/permissions, storage paths, port binds, and existing resource compatibility before mutation.
- Fail on an existing network, volume, or service whose observed identity/configuration conflicts with the declaration. Do not silently recreate or take ownership.
- Check that required secrets exist without printing their contents.
- Keep a snapshot of service definitions and active state needed for rollback.

### Apply

- Build or pull pinned images, create only missing declared networks and volumes, install service definitions atomically, and start dependencies in an explicit order.
- Wait for dependency readiness and application health before publishing routes or development DNS records.
- Update Application Gateway routes through its supported deployment interface.
- Configure containers to use the Development Gateway DNS address on their network. Publish split-DNS rules for configured container domains to remote OpenVPN and SSH TUN clients.
- Notify the Development Gateway after a declared development target is ready and its current network address is known. Prefer a narrow DNS refresh operation. If the only available interface is full Gateway `--apply`, document and test its permissions, side effects, and restart behavior before using it as the handoff.
- Load destination `authorized_keys` inputs from root-managed public-key files outside Git. Default to `/etc/gateway/application-keys/<container>/authorized_keys`, with one file per SSH-enabled container and multiple public keys per file. Mount each file read-only at `/home/<account>/.ssh/authorized_keys` for a dedicated non-root destination account. Validate owner, mode, file type, and key format before apply. Never copy private keys to the host or containers.
- Host audit records changes to the root-managed public-key files. PAM authentication and operator-session logging are provided by the host security layer and are not managed or tested by this deployment.
- Generate a systemd timer from each `database_backups[].schedule` in JSON, defaulting to monthly. Run unfiltered `pg_dumpall` for PostgreSQL 18, write compressed SQL to its configured host-mounted path shared with PostgreSQL, verify a checksum, and publish atomically. Log an error and fail the backup job if the mount is unavailable; never fall back to local-only storage. Retention is owned by remote storage; deployment never restores automatically.

### Failure and rollback

- Preserve the last known-good service configuration and image reference until health checks pass.
- On failure, restore service definitions and image versions where safe. Do not restore a backup over a live volume automatically.
- Report additive resources that remain after a failed apply. Do not claim full rollback if networks, volumes, images, or data changed.
- Never prune unrelated Podman resources or delete application data, secrets, Gateway state, or host SSH keys.

### Remove and decommission

- Separate service removal from network/volume/data deletion.
- Require explicit operator approval and owner confirmation before deleting persistent volumes or backups.
- Remove only resources bearing the application's exact declared identity; preserve shared Gateway resources.

## 5. Secrets, Storage, and Recovery

- Keep secret and public-key source files outside Git with documented owner, group, mode, rotation process, and consumer. Store app keys under `/etc/gateway/application-keys/<container>/authorized_keys` by default, with one file per SSH-enabled container and multiple public keys per file. Mount each file read-only at `/home/<account>/.ssh/authorized_keys`. Require root-controlled key-file writes; reject unexpected symlinks or ownership/mode changes and never overwrite source files. Host audit records key-file changes; PAM controls remain external to this plan.
- Mount secrets read-only and only into services that use them. Do not copy them into images, generated public configs, or logs.
- Document each volume's purpose, owner, mount path, backup method, remote mount, and manual restore procedure. Remote storage owns retention.
- Test backup restoration into a disposable volume before production acceptance. A successful backup command alone is not proof of recoverability.

## 6. Operations and Observability

- Provide operator-visible service status, logs, health state, image identity, and recent deployment outcome.
- Define log destination, retention, rotation, and redaction. Never log secret contents or credentials embedded in connection strings.
- Define image update cadence, vulnerability review, pinning, and rollback ownership.
- Define service restart and reboot behavior through Quadlet. Define backup timer schedule, remote-mount dependency, lock/overlap handling, log retention, and failure alerting.
- Keep advanced metrics/tracing optional unless an operational owner and retention target exist.

## 7. Implementation Phases

1. Resolve the deployment mechanism, configuration ownership, host paths, secret policy, and database recovery objectives.
2. Define a versioned app manifest and read-only preflight with failure-before-change tests.
3. Implement network, volume, and service lifecycle with idempotence and explicit ownership checks.
4. Integrate readiness, health checks, route publication, and backup scheduling.
5. Integrate Application Gateway route updates and Development Gateway DNS refresh without direct edits to their owned state.
6. Validate update, failure rollback, reboot, backup/restore, secret preservation, and isolation on the authorized disposable RHEL 9.8 / Podman 5.8.2 host with SELinux disabled. Do not change host security settings.

## 8. Acceptance Checks

- Repeated apply is idempotent and does not restart unchanged services unnecessarily.
- Invalid configuration or missing secrets fail before host/service mutation.
- Network and volume identities, database sentinels, secret bytes, and permissions survive app-container replacement.
- A newly recreated development target gets a fresh DNS address only after readiness; stale records are removed according to the Gateway contract.
- VS Code ProxyJump reaches the declared application destination, and that destination accepts or rejects the developer key independently of Gateway authentication.
- Public routes become active only after application health passes.
- Failure during service start, route update, DNS refresh/routing handoff, or backup job has documented recovery without overwriting live database data.
- Backup restore and decommission procedures are proven against disposable resources.
- No application update exposes the Podman API, changes host SELinux state, or removes unrelated resources.

## 9. Remaining Implementation Inputs

- Name the authorized production deployment operators and their audit path.
- Supply actual Podman network names, CIDRs, Gateway interface/DNS addresses, and configured container domains. Runtime tunnel routes must be discoverable and must not overlap these networks.
- Select non-root UID/GID values and writable paths for each image. The qualification host requires SELinux disabled; deployment must not change that state.
- Set the Application Gateway bind address and the frontend/FastAPI ports within the combined `webApp` container. Keep database credentials readable only by the FastAPI process.
- Set the host-mounted remote backup path and confirm its protocol and write access. The path is shared with PostgreSQL; backup jobs log errors and fail if it is unavailable.
- Implement and test a narrow Development Gateway DNS refresh handoff. Do not edit Gateway-owned DNS files directly.
- Select the supported Node.js build version and TUS account/storage details. Keep the default 1 GB file limit configurable.
