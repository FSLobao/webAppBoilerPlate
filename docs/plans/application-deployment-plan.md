# Application Deployment and Operations Plan

**Status:** Design plan; application lifecycle is not implemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)
**Related plans:** [Application Gateway](application-gateway-plan.md), [Application Stack](application-stack-plan.md), [Gateway Bootstrap](gateway-bootstrap-plan.md)

## 1. Goal and Ownership

Define repeatable deployment and day-two operations for application services on the RHEL 9.8 / rootful Podman 5.8.2 qualification target. Keep application lifecycle separate from the shared Development Gateway lifecycle. This plan covers networks, service definitions, volumes, external secrets, image updates, health, rollback, backups, and handoffs to the two gateways.

Use rootful Podman Quadlet for long-running application containers and the shared gateways. Keep host timers and one-shot maintenance jobs as explicit systemd units managed by the same deployment, rather than introducing Compose as a second lifecycle system.

## 2. Resource Ownership

| Resource | Owner | Required boundary |
|---|---|---|
| RHEL host, Podman, storage capacity, host security policy | Infrastructure | Developers do not need routine host administrator access. |
| Application containers, networks, database volumes and health state, destination SSH accounts and public keys | Application deployment | Do not delete or rewrite persistent state during ordinary updates. Preserve per-developer destination authentication. |
| Development Gateway, its SSH identity, and generated DNSMasq records | Development Gateway deployment | Application deployment must use a documented handoff; it must not edit Gateway-owned files directly. |
| Public HTTP routes and TLS termination | Application Gateway and infrastructure, ownership to be decided | Keep user traffic separate from developer SSH/DNS access. |
| Secret values and backup destination | Infrastructure/application owners | Keep outside Git and images; mount only into required consumers. |

Keep `config/host_config.json` as the host-wide source of truth for every application and database network. Add optional service-specific sections such as `gateway`, `application_gateway`, and per-application services. Shared preflight always validates the full network inventory; service-specific preflight and apply run only for declared/enabled sections. Do not create duplicate network sources of truth.

The shared Development Gateway attaches to every network in the top-level inventory, including database networks. There is no separate per-service approval workflow for Gateway reachability. This makes the Gateway a trusted, multi-network administrative component; Podman network isolation does not protect an application from a compromised Gateway. Keep application credentials separate and rely on service authentication as well as the external perimeter.

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
- Nginx listener address and published host port (default `80`), plus `/app` frontend and `/app/api/` backend routes;
- a `database_backups` entry per PostgreSQL instance, with `schedule` and pre-mounted `remote_mount` path.

The exact file location and schema are decision gates. Configuration must contain references and metadata, not secret values or permanent container IPs.

Example service configuration; the actual top-level `networks` array must list every Podman network used by the host:

```json
{
	"application_gateway": {
		"enabled": true,
		"listen_address": "192.0.2.10",
		"http_port": 80,
		"routes": [
			{
				"prefix": "/app",
				"frontend": "project-a-frontend",
				"api_prefix": "/app/api/",
				"backend": "project-a-backend"
			}
		]
	},
	"database_backups": [
		{
			"postgres_container": "project-a-postgres",
			"schedule": "daily",
			"remote_mount": "/mnt/remote-backups/project-a"
		}
	]
}
```

`schedule` uses systemd `OnCalendar` syntax and generates a host timer. `remote_mount` names a mount managed by infrastructure; deployment must confirm it is mounted and writable. The sample address is documentation-only and must be replaced with the configured host address.

## 4. Lifecycle Contract

### Preflight

- Validate schema, resource names, CIDR overlap, image references, host prerequisites, secret paths/permissions, storage paths, port binds, and existing resource compatibility before mutation.
- Fail on an existing network, volume, or service whose observed identity/configuration conflicts with the declaration. Do not silently recreate or take ownership.
- Check that required secrets exist without printing their contents.
- Keep a snapshot of service definitions and active state needed for rollback.

### Apply

- Build or pull pinned images, create only missing declared networks and volumes, install service definitions atomically, and start dependencies in an explicit order.
- Wait for dependency readiness and application health before publishing routes or development DNS records.
- Update Application Gateway routes through its supported deployment interface.
- Notify the Development Gateway after a declared development target is ready and its current network address is known. Prefer a narrow DNS refresh operation. If the only available interface is full Gateway `--apply`, document and test its permissions, side effects, and restart behavior before using it as the handoff.
- Load destination `authorized_keys` inputs from root-managed public-key files outside Git. Keep gateway-login and application-destination files separate, consume them read-only, and validate owner, mode, file type, key format, and SELinux access before apply. Never copy private keys to the host or containers.
- Host audit records changes to the root-managed public-key files. PAM authentication and operator-session logging are provided by the host security layer and are not managed or tested by this deployment.
- Generate a systemd timer from each `database_backups[].schedule` in JSON. Run unfiltered `pg_dumpall` for all data and structure in the PostgreSQL instance, write compressed SQL to its configured remote mount, verify a checksum, and publish atomically. Fail closed if the configured mount is unavailable. Retention is owned by remote storage; deployment never restores automatically.

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

- Keep secret and public-key source files outside Git with documented owner, group, mode, rotation process, and consumer. Require root-controlled key-file writes; reject unexpected symlinks or ownership/mode changes and never overwrite source files. Host audit records key-file changes; PAM controls remain external to this plan.
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
6. Validate update, failure rollback, reboot, backup/restore, secret preservation, and isolation on disposable RHEL 9.8 with rootful Podman 5.8.2 and SELinux Enforcing.

## 8. Acceptance Checks

- Repeated apply is idempotent and does not restart unchanged services unnecessarily.
- Invalid configuration or missing secrets fail before host/service mutation.
- Network and volume identities, database sentinels, secret bytes, and permissions survive app-container replacement.
- A newly recreated development target gets a fresh DNS address only after readiness; stale records are removed according to the Gateway contract.
- VS Code ProxyJump reaches the declared application destination, and that destination accepts or rejects the developer key independently of Gateway authentication.
- Public routes become active only after application health passes.
- Failure during service start, route update, DNS/NAT handoff, or backup job has documented recovery without overwriting live database data.
- Backup restore and decommission procedures are proven against disposable resources.
- No application update exposes the Podman API, weakens SELinux, or removes unrelated resources.

## 9. Questions Before Implementation

1. Should adding NAT exposure data require `schema_version` 2, or can it be an optional backward-compatible extension to version 1?
2. Who is authorized to run production deployment, and how is that separated from everyday developer access?
3. Which host paths, UID/GID ownership, SELinux labels, and backup locations are approved?
4. What remote mount protocol and availability guarantees apply to the scheduled SQL backup destination?
5. What is the supported app DNS/NAT refresh interface, and can it update only Gateway-owned generated state without restarting DNS or the shared Gateway unnecessarily?
6. How are public route changes and TLS certificate rotation coordinated with application releases?
7. What root-owned host path and naming convention should hold per-user, per-destination public keys? Host audit records file changes; PAM and operator sessions remain externally managed.
8. Which remote client CIDRs need source-preserving return routes, and can those routes be configured through every target network on RHEL 9.8 / Podman 5.8.2?
9. Is the separate Debian file-transfer recipe in [file-gateway-deploy.md](../recipes/file-gateway-deploy.md) an intended product component? If yes, who owns its RHEL 9.8/SELinux-compatible deployment plan?
