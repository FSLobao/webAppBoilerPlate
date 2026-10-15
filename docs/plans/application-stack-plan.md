# Application Stack Plan

**Status:** Design plan; Vite with vanilla JavaScript and PostgreSQL 18 are selected. Container lifecycle remains unimplemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)

## 1. Goal and Components

Define the per-application container stack: JavaScript frontend, Python/FastAPI backend, and PostgreSQL. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use maintained, efficient Linux images for the Gateway and applications, preferably Debian or Alpine; choose container bases independently from the host distribution. Each application remains replaceable and isolated from other applications. This plan does not implement the shared Development Gateway or choose the user-facing proxy; see [Application Gateway Plan](application-gateway-plan.md).

## 2. Proposed Network Shape

```text
Application Gateway -> frontend and approved backend routes
frontend            -> backend API through the selected application route
backend             -> PostgreSQL on a dedicated database network
```

Candidate Podman membership for one application:

- Frontend: application network only.
- Backend: application network and that application's dedicated database network.
- PostgreSQL: that application's dedicated database network only.
- Development Gateway: one interface on every configured network, including this application's database network. Treat it as a trusted administrative component with network-level reach to every service.
- Application Gateway: attach only to application networks with declared HTTP routes; never attach it to a database-only network.

No application network is shared across applications. PostgreSQL has no published host port by default. The Development Gateway can reach the database network by design; application-level database credentials still belong only to the backend and approved operator tasks.

## 3. Frontend and API Alternatives

| Option | Advantages | Costs and risks | Fit |
|---|---|---|---|
| Plain HTML/CSS and JavaScript modules, served as static files | Few dependencies, fast builds, easy to inspect and cache. | State, routing, and reusable UI patterns become application-owned as the SPA grows. | Best for a few simple pages or forms. |
| Vite with vanilla JavaScript modules, served as static files | Adds development server, bundling, and asset hashing without choosing a UI framework. | Adds a Node.js build tool and requires SPA fallback routing. | Recommended default for a small mostly-SPA boilerplate. Start with browser History API routing only if multiple client routes are needed. |
| Vite with a framework such as Vue, Svelte, or React | Component/state conventions and mature ecosystem for complex interactive applications. | Larger dependency surface and framework-specific learning/upgrade costs. | Adopt when reusable stateful UI or team standards justify it; no framework is required by the architecture. |
| FastAPI serves the frontend assets and API from one container | One application endpoint and simple same-origin behavior. | Couples frontend/backend builds, scaling, cache policy, and releases; departs from the separate frontend/backend boundary. | A valid simplification for a small app, but not the default boilerplate topology. |

| API route | Advantages | Costs and risks | Recommendation |
|---|---|---|---|
| Same-origin `/app/api` reverse proxy through the Application Gateway | No browser CORS setup, one public origin, backend stays private, independent frontend/backend containers remain possible. | Requires path-prefix proxy rules and SPA fallback exclusions. | Recommended default. Frontend uses relative `/app/api` URLs. |
| Separate API hostname such as `api.example.com` | Independent API origin and release/routing policy; useful for multiple clients. | Requires CORS allowlists, extra DNS/TLS, cookie and credential policy, and origin-specific testing. | Use when independent API consumers or ownership require it. |
| Publish the backend port directly | Simple for isolated development tools. | Bypasses the Application Gateway, expands public endpoints, and couples clients to deployment ports. | Development-only when explicitly restricted; not the production default. |

Vite is not a UI framework. It is a build tool and development server. With vanilla JavaScript, it gives ES-module development, dependency bundling, optimized static output, and a configurable asset base path without React/Vue/Svelte runtime conventions. For a handful of static pages, plain HTML and modules without Vite have fewer dependencies. For a mostly-SPA application, Vite is a pragmatic middle ground; set its base path to `/app/` so built assets work under the configured application prefix.

The public route contract is `https://<domain>/app` for the frontend and `https://<domain>/app/api/<route>` for FastAPI; the external perimeter terminates TLS and forwards HTTP to NGINX. NGINX preserves `/app/api/` when proxying and matches it before the SPA fallback. Local development should expose the same paths through the Vite proxy.

## 4. Component Contracts

### Frontend

- Default to Vite plus vanilla JavaScript ES modules, with static output served by the selected static server. Add Vue, Svelte, or React only when app complexity or team standards justify it.
- Configure Vite's `base` to `/app/`; keep browser routes and asset URLs beneath that prefix.
- Build static assets into a minimal serving image unless the chosen application requires a runtime server.
- Keep API endpoints configurable by environment without embedding production secrets in build output.
- Do not connect directly to PostgreSQL or receive database credentials.
- Define client-side route fallback and static asset cache behavior with the Application Gateway route plan.

### Backend

- Use Python and FastAPI, with dependency and interpreter versions pinned through repository-managed tooling.
- Expose application APIs under `/app/api/*` and readiness/liveness checks; do not own host, Podman, DNS, or Gateway configuration.
- Read database credentials and other secrets from external runtime files or an approved secret mechanism. Do not place secret values in image layers, command-line arguments, or logs.
- Run with the least container privileges practical. Do not require host networking or the Podman socket.

### PostgreSQL

- Run PostgreSQL 18 by default, with the major version declared in config, in its own container with a named or dedicated persistent volume.
- Mount credentials/configuration only into PostgreSQL and the backend that needs them. Do not publish the database port externally.
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
- Use PostgreSQL 18 by default; define the matching client image version in config.
- Set the default full-cluster backup schedule to monthly in JSON. Define the host-mounted remote path and approved direct restore connection. Retention is managed by remote storage.

### Phase 1: Define service interfaces

- Document image names/tags, internal ports, health checks, required environment keys, secret-file references, and network memberships.
- Separate build-time public configuration from runtime secrets.

### Phase 2: Build and validate images

- Build each image from repository sources with pinned dependencies and a minimal runtime surface.
- Run containers without unnecessary capabilities and without host mounts beyond declared configuration, secrets, and persistent data. The qualification host has SELinux disabled by explicit decision; deployment must not change host security settings.
- Test startup, graceful shutdown, health checks, and behavior when dependencies are unavailable.

### Phase 3: Validate data and isolation

- Prove frontend cannot reach PostgreSQL, the backend can reach only its declared database, and another application's workload cannot reach this database. Separately confirm the trusted Development Gateway can connect through its all-network attachment.
- Test fresh database initialization, full `pg_dumpall` backup, manual SQL restore into an isolated cluster, and container replacement with data sentinels.
- Test frontend-to-backend routing through the selected Application Gateway contract.

## 6. Acceptance Checks

- Frontend, backend, and database have distinct images and documented interfaces.
- No frontend image/config contains database credentials.
- PostgreSQL has persistent storage and no external port publication.
- Only the backend can reach its database under the declared network model.
- Only the backend workload receives application database credentials and connects during normal app operation; the trusted Development Gateway has network-level reach for maintenance/restore.
- Backend and frontend health checks detect startup failure without leaking secrets.
- A PostgreSQL replacement preserves the data volume; a full-cluster SQL dump restores every database and global role into a disposable cluster.

## 7. Remaining Implementation Inputs

- Select the supported Node.js build version and non-root UID/GID for each image.
- Define writable paths and verify permissions on the SELinux-disabled RHEL 9.8 host.
- Set actual PostgreSQL network, volume, host-mounted backup path, and DNS names in config.
- Configure the remote tunnel DNS suffixes. The Development Gateway reaches every configured service; each service must enforce its own authentication and authorization.
