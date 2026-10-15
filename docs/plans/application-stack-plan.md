# Application Stack Plan

**Status:** Design plan; framework and database lifecycle decisions remain open.
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

The public route contract is `http://<domain>/app` for the frontend and `http://<domain>/app/api/<route>` for FastAPI. Nginx sends `/app/api/` to the API before applying the SPA fallback to other `/app/` paths. Local development should expose the same paths through the Vite proxy.

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
- Expose application APIs and readiness/liveness checks; do not own host, Podman, DNS, or Gateway configuration.
- Read database credentials and other secrets from external runtime files or an approved secret mechanism. Do not place secret values in image layers, command-line arguments, or logs.
- Run with the least container privileges practical. Do not require host networking or the Podman socket.

### PostgreSQL

- Run the selected supported PostgreSQL major in its own container with a named or dedicated persistent volume.
- Mount credentials/configuration only into PostgreSQL and the backend that needs them. Do not publish the database port externally.
- Define initialization, readiness, supported PostgreSQL major/client versions, full-cluster backup, and manual restore procedures before production use. The remote storage service owns backup retention.
- Container replacement must preserve the database volume. Image rollback must not imply an unsafe data downgrade.

### Backup and restore

| Option | Recovery capability | Operational cost | Fit |
|---|---|---|---|
| Scheduled plain-SQL `pg_dumpall` to the configured remote mount | Captures every database's schema and data plus cluster-wide roles; restores to dump time, without point-in-time recovery. | Low to moderate. Requires mount checks, credentials, checksums, and restore drills. | Required initial default. JSON config supplies the schedule and mount; remote storage owns retention. |
| `pgBackRest` or WAL-G with base backups and WAL archiving | Point-in-time recovery and lower recovery-point objectives. | Higher setup, credentials, monitoring, storage, and restore complexity. | Adopt when data value, size, or recovery objectives need PITR. |
| Storage snapshots coordinated with PostgreSQL | Fast volume-level recovery when snapshots are crash-consistent or database-coordinated. | Storage-provider-specific; snapshots alone are not a portable logical backup. | Supplement, not the only backup, unless consistency and restore are proven. |

Run unfiltered `pg_dumpall` for the complete PostgreSQL cluster: all database schemas and data, plus global roles. Write its UTF-8 SQL stream to a timestamped file on the configured remote mount, compress it, verify a checksum, then publish it atomically. The job must fail if the mount is absent or unwritable; never fall back to local-only storage. Retention is managed by the remote-storage service. Protect credentials and dump files, and keep secrets out of process arguments and logs.

Restore is a deliberate operator task, not an automatic deployment rollback. An authorized operator connects directly to PostgreSQL through an approved private route or temporary management tunnel and runs the complete SQL dump through `psql` as a PostgreSQL administrator. Do not expose the database through the Application Gateway or leave a public PostgreSQL port open. Test role and ownership restoration before acceptance.

For a compressed `pg_dumpall` file, the manual restore shape is:

```bash
gzip --decompress --stdout "$dump_file" | psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname=postgres
```

Supply the host, port, and administrator credentials through the approved private connection and protected PostgreSQL client configuration, not command-line passwords. Run this against the intended target cluster; `pg_dumpall` contains commands that create/connect to multiple databases and restore global objects.

Workers, schedulers, caches, and other services are out of scope until a concrete application requires them.

## 5. Implementation Phases

### Phase 0: Resolve the stack contract

- Confirm Vite plus vanilla JavaScript as the default, or select a framework with a recorded reason; define supported Node.js build version and SPA fallback.
- Confirm the supported PostgreSQL major and matching client image version.
- Define the full-cluster backup schedule in JSON, the pre-mounted remote path, and the approved direct restore connection. Retention is managed by remote storage.

### Phase 1: Define service interfaces

- Document image names/tags, internal ports, health checks, required environment keys, secret-file references, and network memberships.
- Separate build-time public configuration from runtime secrets.

### Phase 2: Build and validate images

- Build each image from repository sources with pinned dependencies and a minimal runtime surface.
- Run containers without unnecessary capabilities and without host mounts beyond declared configuration, secrets, and persistent data.
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

## 7. Open Questions

1. Is Vite with vanilla JavaScript acceptable as the default build path for mostly-SPA applications, with plain static modules available for very small pages?
2. Is the public path contract `/app` for the frontend and `/app/api/*` for API requests correct for all applications?
3. Is a daily full-cluster backup schedule appropriate as the default? The schedule remains configurable per PostgreSQL instance; remote storage owns retention.
4. Which non-root UID/GID and writable paths are compatible with the selected images and RHEL 9.8 SELinux policy?
5. Which development services, if any, need DNS/SSH access through the Development Gateway?
