# Application Stack Plan

**Status:** Design plan; Vite with vanilla JavaScript and PostgreSQL 18 are selected. Container lifecycle remains unimplemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)

## 1. Goal and Components

Define the per-application container stack: JavaScript frontend and Python/FastAPI in `webApp`, plus PostgreSQL. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use maintained, efficient Linux images for the Gateway and applications, preferably Debian or Alpine; choose container bases independently from the host distribution. Each app gets a unique app-specific Podman network, but members also connect to `shared` and require service-level authentication. `shared` is a Podman bridge for attached containers, not a physical/host interface or a VPN route/address pool. Deploy and verify the shared Development Gateway before this application stack. Application deployment owns app container creation/readiness; this plan does not implement the Gateway or NGINX runtime; see [Application Gateway Plan](application-gateway-plan.md).

## 2. Proposed Network Shape

```text
NGINX               -> `webApp` frontend and FastAPI routes
webApp container    -> PostgreSQL on `webApp` and `shared`
Development Gateway -> every declared Podman network
```

Selected Podman membership:

- `webApp`: `webApp` and `shared`.
- `postgres`: `webApp` and `shared`.
- NGINX: `shared`.
- Development Gateway: every declared network, including `shared` and `webApp`.

The global top-level `networks` array contains the Podman application networks and their non-overlapping CIDRs; it does not describe host interfaces, physical/host network attachments, VPN routes, or tunnel address pools. The `webApp` network uses `192.168.8.0/29`; `shared` uses `192.168.7.0/24`. The `/29` provides six usable addresses for the host bridge, Gateway, `webApp`, PostgreSQL, and future headroom. PostgreSQL has no published host port by default. App deployment assigns a unique, non-overlapping CIDR to each future app network, creates it, adds it only to the global top-level `networks` inventory, and reconciles the existing Gateway to attach it.

### Shared-network security boundary

The requester confirmed that all app containers, including PostgreSQL, join `shared`. That network provides direct connectivity between all its members. No routing between app-specific networks does not prevent communication over `shared`; each service must enforce its own authentication and authorization.

The `webApp` container combines Vite assets and FastAPI. The latest decision supersedes the earlier separate-process choice: FastAPI serves both assets and API on port `8000` and holds PostgreSQL credentials. Browser assets do not receive those credentials; keep them out of build output and HTTP responses.

The `192.168.8.0/29` subnet is reserved for this `webApp` network. Reusing it for another simultaneous Podman network is invalid; future apps require distinct CIDRs.

### Deployment order and readiness ownership

- Gateway is the first containerized service on a clean host. Gateway preflight validates its own host/tools/credentials and all declared Podman network definitions; it may create missing declared networks during apply. It succeeds without any `nginx`, `webApp`, PostgreSQL, or DNS-target containers and never creates, starts, or inspects them.
- After Gateway is healthy, application deployment validates the shared versioned host-config candidate and existing network compatibility before atomically updating it for new networks, containers, routes, or DNS declarations; unrelated config objects and operator inputs are preserved. It creates missing declared networks and reconciles the existing Gateway to attach newly declared networks before creating/starting the application workload. Existing incompatible networks and invalid staged references fail before mutation.
- Application deployment owns dependency ordering and readiness for `webApp`, PostgreSQL, NGINX, and any other app services. Declared container existence, `application_gateway.enabled`, or DNS mappings do not establish runtime readiness or mean those services are implemented.
- Only after an app target passes its declared health/readiness checks does application deployment request a revision-scoped DNS refresh. Gateway re-inspects Podman and publishes only the current valid address on the target's declared network. Absent, stopped, unhealthy, unattached, or not-ready targets remain pending and have no DNS record; Gateway never starts them.
- App start, stop, failure, and replacement paths request DNS refresh so the address is added, updated, or removed. A refresh must never retain the previous address as fallback. There is no background watcher in scope, so an unannounced process crash can leave DNS stale until an explicit refresh or Gateway restart; that limitation must be visible in operations.

Application lifecycle, container readiness, and dependency checks belong to this application phase, not Gateway host preflight. The current scripts still impose older Gateway container prerequisites and may start stopped DNS targets; that runtime behavior is not this plan and must be changed before clean-host Gateway-first acceptance. The top-level `networks` array remains strictly the Podman network inventory; VPN/tunnel routes and host interfaces remain separate configuration.

## 3. Frontend and API Alternatives

| Option | Advantages | Costs and risks | Fit |
|---|---|---|---|
| Plain HTML/CSS and JavaScript modules, served as static files | Few dependencies, fast builds, easy to inspect and cache. | State, routing, and reusable UI patterns become application-owned as the SPA grows. | Best for a few simple pages or forms. |
| Vite with vanilla JavaScript modules, served as static files | Adds development server, bundling, and asset hashing without choosing a UI framework. | Adds a Node.js build tool and requires SPA fallback routing. | Recommended default for a small mostly-SPA boilerplate. Start with browser History API routing only if multiple client routes are needed. |
| Vite with a framework such as Vue, Svelte, or React | Component/state conventions and mature ecosystem for complex interactive applications. | Larger dependency surface and framework-specific learning/upgrade costs. | Adopt when reusable stateful UI or team standards justify it; no framework is required by the architecture. |
| FastAPI serves frontend assets and API from one container | One application endpoint and simple same-origin behavior. | Couples frontend/backend builds, scaling, cache policy, releases, and process isolation. | Selected initial layout: one `webApp` container, with NGINX as the only HTTP provider. |

| API route | Advantages | Costs and risks | Recommendation |
|---|---|---|---|
| Same-origin `/app/api` reverse proxy through the Application Gateway | No browser CORS setup and one public origin. | Requires path-prefix proxy rules and SPA fallback exclusions. | Selected default. NGINX sends both paths to `webApp:8000`. |
| Separate API hostname such as `api.example.com` | Independent API origin and release/routing policy; useful for multiple clients. | Requires CORS allowlists, extra DNS/TLS, cookie and credential policy, and origin-specific testing. | Use when independent API consumers or ownership require it. |
| Publish the backend port directly | Simple for isolated development tools. | Bypasses the Application Gateway, expands public endpoints, and couples clients to deployment ports. | Development-only when explicitly restricted; not the production default. |

Vite is not a UI framework. It is a build tool and development server. With vanilla JavaScript, it gives ES-module development, dependency bundling, optimized static output, and a configurable asset base path without React/Vue/Svelte runtime conventions. For a handful of static pages, plain HTML and modules without Vite have fewer dependencies. For a mostly-SPA application, Vite is a pragmatic middle ground; set its base path to `/app/` so built assets work under the configured application prefix.

The public route contract is `https://<domain>/app` for frontend assets and `https://<domain>/app/api/<route>` for FastAPI; the external perimeter terminates TLS and forwards HTTP to NGINX. NGINX preserves `/app/api/`, matches it before `/app`, and proxies both paths to `webApp:8000`. Local development should expose the same paths through the Vite proxy.

## 4. Component Contracts

### Frontend

- Default to Vite plus vanilla JavaScript ES modules, with static output served by the selected static server. Add Vue, Svelte, or React only when app complexity or team standards justify it.
- Configure Vite's `base` to `/app/`; keep browser routes and asset URLs beneath that prefix.
- Build Vite assets into the combined `webApp` image. FastAPI serves static assets under `/app` and API routes under `/app/api/` on port `8000`; NGINX is the only host-published HTTP provider and proxies both paths.
- Keep API endpoints configurable by environment without embedding production secrets in build output.
- Do not connect directly to PostgreSQL or receive database credentials.
- Define client-side route fallback and static asset cache behavior with the Application Gateway route plan.

### Backend

- Run Python and FastAPI in the combined `webApp` container, with dependency and interpreter versions pinned through repository-managed tooling.
- Expose application APIs under `/app/api/*` and readiness/liveness checks; do not own host, Podman, DNS, or Gateway configuration.
- Read database credentials and other secrets from external runtime files or an approved secret mechanism. Do not place secret values in image layers, command-line arguments, or logs.
- Run with the least container privileges practical. Do not require host networking or the Podman socket.

### PostgreSQL

- Run PostgreSQL 18 by default, with the major version declared in config, in its own container with a named or dedicated persistent volume.
- Mount PostgreSQL credentials only into the `webApp` container for FastAPI use. One FastAPI process serves static assets and APIs, so it holds database credentials; browser assets do not receive those credentials.
- Define initialization, readiness, PostgreSQL/client versions, full-cluster backup, and manual restore procedures before production use. The default backup schedule is monthly and remains configurable per instance.
- Mount the host-managed remote backup path into the PostgreSQL container read-only at a configured path. The host backup job writes to the host path and logs an error if remote storage is unavailable; it never falls back to local-only storage.
- Container replacement must preserve the database volume. Image rollback must not imply an unsafe data downgrade.

### Optional file services

- Add a TUS file-transfer container only when declared in config. NGINX publishes its route; enforce a 1 GB maximum file size in the TUS service and proxy configuration by default.
- Add NGINX basic file sharing only when declared. Serve files read-only by default; use the TUS service for uploads.
- Keep file data on declared persistent volumes and include their backup/restore responsibility in the application manifest.

### Backup and restore

| Option | Recovery capability | Operational cost | Fit |
|---|---|---|---|
| Scheduled plain-SQL `pg_dumpall` to the configured remote mount | Captures every database's schema and data plus cluster-wide roles; restores to dump time, without point-in-time recovery. | Low to moderate. Requires mount checks, credentials, checksums, and restore drills. | Required initial default. JSON config supplies the schedule and mount; remote storage owns retention. |
| `pgBackRest` or WAL-G with base backups and WAL archiving | Point-in-time recovery and lower recovery-point objectives. | Higher setup, credentials, monitoring, storage, and restore complexity. | Adopt when data value, size, or recovery objectives need PITR. |
| Storage snapshots coordinated with PostgreSQL | Fast volume-level recovery when snapshots are crash-consistent or database-coordinated. | Storage-provider-specific; snapshots alone are not a portable logical backup. | Supplement, not the only backup, unless consistency and restore are proven. |

Run unfiltered `pg_dumpall` for the complete PostgreSQL cluster: all database schemas and data, plus global roles. Write its UTF-8 SQL stream to a timestamped file on the configured host-mounted remote path, compress it, verify a checksum, then publish it atomically. Log a clear error and fail the job if the mount is absent or unwritable; never fall back to local-only storage. Retention is managed by the remote-storage service. Protect credentials and dump files, and keep secrets out of process arguments and logs.

Restore is a manual, operator-triggered task, not an automatic deployment rollback. The initial interface is a restore script; a Cockpit tool may be added later. An authorized operator connects directly to PostgreSQL through an approved private route or temporary management tunnel and runs the complete SQL dump through `psql` as a PostgreSQL administrator. Do not expose the database through the Application Gateway or leave a public PostgreSQL port open. Test role and ownership restoration before acceptance.

For a compressed `pg_dumpall` file, the manual restore shape is:

```bash
gzip --decompress --stdout "$dump_file" | psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname=postgres
```

Supply the host, port, and administrator credentials through the approved private connection and protected PostgreSQL client configuration, not command-line passwords. Run this against the intended target cluster; `pg_dumpall` contains commands that create/connect to multiple databases and restore global objects.

Workers, schedulers, caches, and other services are out of scope until a concrete application requires them.

## 5. Implementation Phases

### Phase 0: Resolve the stack contract

- Use Vite plus vanilla JavaScript as the default. Define the supported Node.js build version and SPA fallback.
- Keep frontend assets and FastAPI in the single `webApp` container on internal port `8000`. NGINX proxies both `/app` and `/app/api/` to that listener.
- Use PostgreSQL 18 by default; define the matching client image version in config.
- Reserve `192.168.8.0/29` for the `webApp` network. Assign each future app network a unique, non-overlapping CIDR and static Gateway address.
- Set the default full-cluster backup schedule to monthly in JSON. Define the host-mounted remote path and approved direct restore connection. Retention is managed by remote storage.

### Phase 1: Define service interfaces

- Document image names/tags, internal ports, health checks, required environment keys, secret-file references, and network memberships.
- Separate build-time public configuration from runtime secrets.

### Phase 2: Build and validate images

- Build the combined `webApp` image and separate PostgreSQL image from repository sources with pinned dependencies and a minimal runtime surface.
- Run containers without unnecessary capabilities and without host mounts beyond declared configuration, secrets, and persistent data. The qualification host has SELinux disabled by explicit decision; deployment must not change host security settings.
- Test startup, graceful shutdown, health checks, and behavior when dependencies are unavailable.

### Phase 3: Validate data and isolation

- Verify the combined `webApp` container reaches PostgreSQL over `webApp` and `shared`. All services attached to `shared` have direct network reach to PostgreSQL; prove PostgreSQL authentication denies unauthorized workloads and only FastAPI's process can read database credentials.
- Verify app-specific networks do not route to one another. Do not treat this as isolation between containers that share `shared`.
- Test fresh database initialization, full `pg_dumpall` backup, manual SQL restore into an isolated cluster, and container replacement with data sentinels.
- Test frontend-to-backend routing through the selected Application Gateway contract.

## 6. Acceptance Checks

- The frontend and FastAPI run in one `webApp` image; PostgreSQL uses a separate image. Document each process and internal port.
- No frontend image/config contains database credentials.
- PostgreSQL has persistent storage and no external port publication.
- FastAPI serves frontend assets and APIs on `webApp:8000` and holds database credentials. Verify build output and HTTP responses never expose those credentials; shared-network membership cannot enforce service authorization.
- PostgreSQL rejects unauthorized connections from other shared-network members. The Gateway has network-level reach but receives no database credentials.
- Backend and frontend health checks detect startup failure without leaking secrets.
- A PostgreSQL replacement preserves the data volume; a full-cluster SQL dump restores every database and global role into a disposable cluster.
- On a pristine host, Gateway bootstrap succeeds with optional app container, DNS, and route declarations present but no application containers; Gateway does not start or operate them. Missing Podman networks are reported by read-only check and created only during apply.
- After Gateway health, application deployment creates/readies `webApp` and PostgreSQL, preserves unrelated objects while atomically updating the shared config, and reconciles the existing Gateway for new networks before app startup. A repeated deployment is idempotent; a malformed staged config or incompatible existing network fails before mutation.
- An absent, stopped, or unhealthy declared service is pending rather than a Gateway bootstrap error or a published DNS answer. After application readiness, Gateway publishes the live address; stop/replacement refresh removes or updates the record and never falls back to an old address.
- Gateway reboot recovery does not depend on app targets. Application units start in their own phase after Gateway/network prerequisites, and readiness triggers the same DNS handoff.

## 7. Remaining Implementation Inputs

- Select the supported Node.js build version and non-root UID/GID for each image.
- Define writable paths and verify permissions on the SELinux-disabled RHEL 9.8 host.
- Set actual PostgreSQL network, volume, host-mounted backup path, and DNS names in config.
- Configure the remote tunnel DNS suffixes. The Development Gateway reaches every configured service; each service must enforce its own authentication and authorization.
