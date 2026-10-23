# Application Stack Plan

**Status:** Design plan; Vite with vanilla JavaScript and PostgreSQL 18 are selected. Container lifecycle remains unimplemented.
**Contract:** [Web Application Boilerplate Architecture](../contracts/ARCHITECTURE.md)

## 1. Goal and Components

Define the selected initial application stack: JavaScript frontend and Python/FastAPI in `webApp`, plus PostgreSQL. Other HTTP applications may configure their own HTTP upstreams and ports. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use maintained, efficient Linux images for the Gateway and applications, preferably Debian or Alpine; choose container bases independently from the host distribution. Each app gets a unique app-specific Podman network, but members also connect to `shared` and require service-level authentication. `shared` is a Podman bridge for attached containers, not a physical/host interface or a VPN route/address pool. Deploy and verify the shared Development Gateway before this application stack. Application deployment owns app container creation/readiness; this plan does not implement the Gateway or NGINX HTTP proxy runtime; see [HTTP Proxy Plan](http-proxy-plan.md).

## 2. Proposed Network Shape

```text
Optional NGINX HTTP -> initial `webApp:8000` SPA and FastAPI routes
webApp container    -> PostgreSQL on `webApp` and `shared`
Development Gateway -> all configured services and ports on every declared Podman network
```

Selected Podman membership:

- `webApp`: `webApp` and `shared`.
- `postgres`: `webApp` and `shared`.
- NGINX: `shared`.
- Development Gateway: every declared network, including `shared` and `webApp`.

The global top-level `networks` array contains the Podman application networks and their non-overlapping CIDRs; it does not describe host interfaces, physical/host network attachments, VPN routes, or tunnel address pools. The `webApp` network uses `192.168.8.0/29`; `shared` uses `192.168.9.0/24`. The `/29` provides six usable addresses for the host bridge, Gateway, `webApp`, PostgreSQL, and future headroom. PostgreSQL has no published host port by default. App deployment assigns a unique, non-overlapping CIDR to each future app network, creates it, adds it only to the global top-level `networks` inventory, and reconciles the existing Gateway to attach it.

### Shared-network security boundary

The requester confirmed that all app containers, including PostgreSQL, join `shared`. That network provides direct connectivity between all its members. No routing between app-specific networks does not prevent communication over `shared`; each service must enforce its own authentication and authorization.

The selected initial `webApp` container combines built Vite assets and FastAPI. FastAPI serves the SPA at `/app/` and the API at `/app/api/` on the single internal TCP listener `8000`, and holds PostgreSQL credentials. NGINX, when enabled, proxies both paths to that same listener. Browser assets do not receive those credentials; keep them out of build output and HTTP responses. There are no separate frontend/API listener ports or unresolved port inputs in this initial stack. This does not restrict additional HTTP applications: their configured routes may use their own upstreams and ports.

For protected end-user HTTP operations, the external perimeter authenticates users and injects trusted
`X-USER` identity fields after stripping/replacing client-supplied identity. The application uses
those fields to authorize; NGINX only proxies and is not a login/authentication engine. Protected
endpoints reject missing or untrusted identity. The exact `X-USER` allowlist and verified provenance
mechanism remain implementation prerequisites; runtime authentication/authorization is not claimed.
The selected initial host proxy bind is `0.0.0.0:8080`, and Development Gateway access bypasses the proxy.
Deployment must gate protected routes on effective restriction to the trusted perimeter or verified
perimeter-to-application identity provenance. A CIDR or raw header alone does not establish trust.

End-user non-HTTP services are published directly only with explicitly declared host bind address,
protocol, and published port, and retain their own service authentication and perimeter controls.
Developer reachability through the Development Gateway covers configured container ports/services
and never requires host publication.

The `192.168.8.0/29` subnet is reserved for this `webApp` network. Reusing it for another simultaneous Podman network is invalid; future apps require distinct CIDRs.

### Deployment order and readiness ownership

- Gateway is the first containerized service on a clean host. Gateway preflight validates its own host/tools/credentials and all declared Podman network definitions; it may create missing declared networks during apply. It succeeds without any `nginx`, `webApp`, PostgreSQL, or DNS-target containers and never creates, starts, or inspects them.
- After Gateway is healthy, application deployment validates the shared versioned host-config candidate and existing network compatibility before atomically updating it for new networks, containers, routes, or DNS declarations; unrelated config objects and operator inputs are preserved. It creates missing declared networks and reconciles the existing Gateway to attach newly declared networks before creating/starting the application workload. Existing incompatible networks and invalid staged references fail before mutation.
- Application deployment owns dependency ordering and readiness for `webApp`, PostgreSQL, NGINX, and any other app services. Declared container existence, `http_proxy.enabled`, or DNS mappings do not establish runtime readiness or mean those services are implemented.
- Only after an app target passes its declared health/readiness checks does application deployment request a revision-scoped DNS refresh. Gateway re-inspects Podman and publishes only the current valid address on the target's declared network. Absent, stopped, unhealthy, unattached, or not-ready targets remain pending and have no DNS record; Gateway never starts them.
- App start, stop, failure, and replacement paths request DNS refresh so the address is added, updated, or removed. A refresh must never retain the previous address as fallback. There is no background watcher in scope, so an unannounced process crash can leave DNS stale until an explicit refresh or Gateway restart; that limitation must be visible in operations.

Application lifecycle, container readiness, and dependency checks belong to this application phase, not Gateway host preflight. Gateway checks no longer impose application-container prerequisites, and Gateway apply does not start stopped DNS targets. The readiness-scoped DNS refresh handoff remains unimplemented. The top-level `networks` array remains strictly the Podman network inventory; VPN/tunnel routes and host interfaces remain separate configuration.

## 3. Frontend and API Alternatives

| Option | Advantages | Costs and risks | Fit |
|---|---|---|---|
| Plain HTML/CSS and JavaScript modules, served as static files | Few dependencies, fast builds, easy to inspect and cache. | State, routing, and reusable UI patterns become application-owned as the SPA grows. | Best for a few simple pages or forms. |
| Vite with vanilla JavaScript modules, served as static files | Adds development server, bundling, and asset hashing without choosing a UI framework. | Adds a Node.js build tool and requires SPA fallback routing. | Recommended default for a small mostly-SPA boilerplate. Start with browser History API routing only if multiple client routes are needed. |
| Vite with a framework such as Vue, Svelte, or React | Component/state conventions and mature ecosystem for complex interactive applications. | Larger dependency surface and framework-specific learning/upgrade costs. | Adopt when reusable stateful UI or team standards justify it; no framework is required by the architecture. |
| FastAPI serves frontend assets and API from one container | One application endpoint and simple same-origin behavior. | Couples frontend/backend builds, scaling, cache policy, releases, and process isolation. | Selected initial layout: one `webApp` container, with NGINX as the only HTTP provider. |

| API route | Advantages | Costs and risks | Recommendation |
|---|---|---|---|
| Same-origin `/app/` and `/app/api/` through the optional HTTP proxy | No browser CORS setup and one public origin. | Requires path-prefix proxy rules and SPA fallback exclusions. | Selected for the initial `webApp` app. NGINX sends both paths to `webApp:8000`; additional applications may configure separate upstreams and ports. |
| Separate API hostname | Not selected. | Would add a second public origin and separate routing policy. | Outside the confirmed default contract. |
| Direct development access through Gateway | Reaches all configured services/ports without publishing host ports. | Requires authorized developer network access and service authentication. | Selected for developer access; not an end-user exposure mechanism. |

Vite is not a UI framework. It is a build tool and development server. With vanilla JavaScript, it gives ES-module development, dependency bundling, optimized static output, and a configurable asset base path without React/Vue/Svelte runtime conventions. For a handful of static pages, plain HTML and modules without Vite have fewer dependencies. For a mostly-SPA application, Vite is a pragmatic middle ground; set its base path to `/app/` so built assets work under the configured application prefix.

The initial app's public route contract is `https://<domain>/app/` for the built SPA and `https://<domain>/app/api/<route>` for FastAPI; the external perimeter terminates TLS and forwards HTTP to NGINX. NGINX preserves `/app/api/`, matches it before `/app/`, and proxies both paths to the same `webApp:8000` listener. Local development should expose the same paths through the Vite proxy. This does not require other applications to use this listener.

## 4. Component Contracts

### Frontend

- Default to Vite plus vanilla JavaScript ES modules, with static output served by the selected static server. Add Vue, Svelte, or React only when app complexity or team standards justify it.
- Configure Vite's `base` to `/app/`; keep browser routes and asset URLs beneath that prefix.
- Build Vite assets into the combined `webApp` image. FastAPI serves the SPA under `/app/` and API routes under `/app/api/` on its one TCP listener `8000`; optional NGINX is the host-published HTTP proxy and proxies both paths.
- Keep API endpoints configurable by environment without embedding production secrets in build output.
- Do not connect directly to PostgreSQL or receive database credentials.
- Define client-side route fallback and static asset cache behavior with the HTTP proxy route plan.

### Backend

- Run Python and FastAPI in the combined `webApp` container, with dependency and interpreter versions pinned through repository-managed tooling.
- Expose application APIs under `/app/api/*` and readiness/liveness checks; do not own host, Podman, DNS, or Gateway configuration.
- Read database credentials and other secrets from external runtime files or an approved secret mechanism. Do not place secret values in image layers, command-line arguments, or logs.
- Run with the least container privileges practical. Do not require host networking or the Podman socket.

### PostgreSQL

- Run PostgreSQL 18 by default, with the major version declared in config, in its own container with a named or dedicated persistent volume.
- Mount PostgreSQL credentials only into the `webApp` container for FastAPI use. One FastAPI process serves static assets and APIs, so it holds database credentials; browser assets do not receive those credentials.
- Define initialization, readiness, PostgreSQL/client versions, backup, and manual restore procedures before production use. pgBackRest is installed at a version pinned in the PostgreSQL image and invoked as the `postgres` OS account, with local database-file access and PostgreSQL authentication. pgBackRest's database roles and permissions must be compatible with the selected backup operations.
- Container replacement must preserve the database volume. Image rollback must not imply an unsafe data downgrade.

### Optional file services

- Add a TUS file-transfer container only when declared in config. NGINX publishes its route; enforce a 1 GB maximum file size in the TUS service and proxy configuration by default.
- Add NGINX basic file sharing only when declared. Serve files read-only by default; use the TUS service for uploads.
- Keep file data on declared persistent volumes and include their backup/restore responsibility in the application manifest.

### Backup and restore

The selected primary backup design uses pgBackRest, not `pg_dumpall`:

- Pin a pgBackRest version in the PostgreSQL image and keep it compatible with the PostgreSQL major version and restore tooling. Execute it inside that container as OS account `postgres`; use local PostgreSQL file access and configured database authentication/roles. Do not put passwords in command arguments, environment dumps, or logs. Use local peer authentication where suitable or a protected credential file readable only by the required account.
- Keep three storage responsibilities distinct: (1) the live PostgreSQL `PGDATA` volume; (2) a writable pgBackRest working repository volume, separate from both `PGDATA` and the completed-export volume; and (3) a host-mounted completed-export volume. The PostgreSQL-side operator writes to the working repository and writes completed publications to the completed-export mount. Neither repository nor export mount is read-only. A missing mount, wrong mount, permission error, or full volume is a hard failure; never fall back to a container layer or another local directory.
- Install/configure a controlled host operator entrypoint and systemd timers. The external scheduler invokes that fixed local entrypoint, which uses constrained `podman exec` calls to run the backup and publication steps. Do not give a remote backup server or collector the rootful Podman socket/API or unrestricted host command execution. Run the backup as `postgres`, serialize all backup/publication work with a lock and bounded timeout, and prevent the full and incremental timers from overlapping or duplicating a run.
- Default recovery-point creation to a monthly full backup and weekly incremental backups. When schedules coincide, run one full backup, not an additional incremental. This yields weekly scheduled recovery points, not daily or continuous recovery. Do not imply PITR or continuous WAL export is required by this design. pgBackRest must retain and publish all WAL and metadata required to make each selected backup consistent and restorable; optional PITR and its additional continuous WAL export, retention, and recovery-point requirements need an explicit later decision.
- A pgBackRest repository is dependency-linked, mutable state, not a directory of independently complete backup files. Do not manually prune it, edit it, copy it while writers are active, or rename a repository subtree. The baseline publication strategy is a complete, snapshot-consistent repository generation, rather than bespoke selection/reconstruction of individual backups. Before export, the implementation must use a supported repository snapshot/locking procedure that excludes concurrent pgBackRest backup and archive writers and captures the selected successful backup together with its parent chain, manifests, repository metadata, and all required consistency WAL. If a consistent generation cannot be produced safely, fail publication.
- The backup command must succeed before export begins. The working-repository volume (including any working/snapshot staging there) is distinct from the completed-export volume. Copy the consistent generation to a separate, hidden, transient publication-in-progress directory on the completed-export filesystem; it is transfer staging, not the working repository. Verify the copy and its repository structure, flush data/metadata as supported, then publish under a unique generation identity with an atomic rename within that destination filesystem or a completion manifest written only after verification. A cross-volume rename is not atomic. Incomplete transfer bytes may temporarily exist in the hidden destination staging area, but the completed namespace must never expose an incomplete generation. Published generations are immutable and never overwritten or edited. The external collector consumes only final generation names or valid completion markers, never hidden staging paths, partial directories, or “stable file size” guesses.
- Full-repository generation exports are intentionally simple and restore-oriented but may consume substantial storage and transfer bandwidth on every schedule. This strategy does not promise incremental network transfers; a collector may deduplicate only through a mechanism that safely preserves immutable generations and their dependencies.
- Failed backup or copy leaves prior published generations and the working repository chain intact. Cleanup may remove only the current failed staging directory and only after confirming it belongs to that run. Do not delete source repository content until external acknowledgement and repository-aware retention prove that no retained backup depends on it; generic remote retention alone must not remove a parent. Define external collector path, encrypted transport/storage, narrowly scoped credentials, acknowledgement, and retention before deployment. Database files, credential files, and exports are sensitive; checksums detect transfer corruption but do not prove recoverability.

Restore is manual and operator-triggered, never an automatic deployment rollback. Restore a verified complete published repository generation using compatible pgBackRest tooling into an isolated/disposable PostgreSQL target first; retain the repository structure and required WAL/metadata intact. Conduct a restore drill, including recovery of a selected incremental through its parent chain, before production acceptance. Only after verification should an authorized operator restore to a production target through an approved private route. Do not expose PostgreSQL through the HTTP proxy or leave a public PostgreSQL port open. `pg_dumpall` may remain an optional logical portability/manual export, but it is not the primary incremental backup or restore path.

**RPO and recovery scope:** with the selected monthly-full/weekly-incremental schedule and no optional continuous WAL publication, the newest planned recovery point is at most one scheduled weekly interval old, subject to job success and publication. This is not PITR. Define operational RPO/RTO acceptance, missed-run alerting, and the policy for optional WAL export separately; do not claim a stronger objective until implemented and tested.

**Planning-only configuration shape (not accepted by the current runtime validator):**

```json
{
  "database_backups": [
    {
      "postgres_container": "project-a-postgres",
      "working_volume": "project-a-pgbackrest-work",
      "working_container_path": "/var/lib/pgbackrest",
      "completed_host_mount": "/mnt/completed-backups/project-a",
      "completed_container_path": "/completed-backups",
      "full_schedule": "monthly",
      "incremental_schedule": "weekly"
    }
  ]
}
```

These names are a documentation proposal only. No backup schema, service fields, timers, mounts, pgBackRest image support, publisher, or restore tooling is implemented by this plan's examples.

Workers, schedulers, caches, and other services are out of scope until a concrete application requires them.

## 5. Implementation Phases

### Phase 0: Resolve the stack contract

- Use Vite plus vanilla JavaScript as the default. Define the supported Node.js build version and SPA fallback.
- Keep frontend assets and FastAPI in the single `webApp` container on internal TCP port `8000`. NGINX proxies both `/app/` and `/app/api/` to that listener.
- Use PostgreSQL 18 by default; define the matching client image version in config.
- Reserve `192.168.8.0/29` for the `webApp` network. Assign each future app network a unique, non-overlapping CIDR and static Gateway address.
- Pin pgBackRest and PostgreSQL versions together; define the monthly-full/weekly-incremental host schedules, three storage locations, safe repository-generation export, encrypted collector handoff, dependency-aware retention, and private restore drill before production use. Backup fields are not currently supported by the runtime validator.

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
- Test fresh database initialization, successful full and incremental pgBackRest backups, publication failure/cleanup, and a manual restore from a completed generation into an isolated cluster; verify container replacement with data sentinels.
- Test frontend-to-backend routing through the selected optional HTTP proxy contract.

## 6. Acceptance Checks

- The SPA and FastAPI run in one `webApp` image and one TCP `8000` listener; PostgreSQL uses a separate image. Document each process and internal port.
- No frontend image/config contains database credentials.
- PostgreSQL has persistent storage and no external port publication.
- FastAPI serves the SPA at `/app/` and API at `/app/api/` on the single `webApp:8000` listener and holds database credentials. Verify build output and HTTP responses never expose those credentials; shared-network membership cannot enforce service authorization.
- The external perimeter supplies authenticated `X-USER` identity; the application authorizes and rejects missing/untrusted identity on protected endpoints. NGINX does not authenticate, and runtime implementation is not claimed.
- Protected HTTP routes do not become deployable until the ingress restriction or verified identity-provenance gate passes; direct Gateway or host-listener access is not trusted identity.
- PostgreSQL rejects unauthorized connections from other shared-network members. The Gateway has network-level reach but receives no database credentials.
- Backend and frontend health checks detect startup failure without leaking secrets.
- A PostgreSQL replacement preserves the data volume. A successful published pgBackRest generation restores through a full/incremental parent chain into a disposable cluster; restore drills verify recoverability and compatibility.
- Monthly full and weekly incremental operations run non-overlapping under one host lock. Only consistent full repository snapshots with successful source backup, required dependency metadata/WAL, and completed publication verification are visible to the collector. Failed copies remain hidden and preserve previous generations and the working source chain.
- On a pristine host, Gateway bootstrap succeeds with optional app container, DNS, and route declarations present but no application containers; Gateway does not start or operate them. Missing Podman networks are reported by read-only check and created only during apply.
- After Gateway health, application deployment creates/readies `webApp` and PostgreSQL, preserves unrelated objects while atomically updating the shared config, and reconciles the existing Gateway for new networks before app startup. A repeated deployment is idempotent; a malformed staged config or incompatible existing network fails before mutation.
- An absent, stopped, or unhealthy declared service is pending rather than a Gateway bootstrap error or a published DNS answer. After application readiness, Gateway publishes the live address; stop/replacement refresh removes or updates the record and never falls back to an old address.
- Gateway reboot recovery does not depend on app targets. Application units start in their own phase after Gateway/network prerequisites, and readiness triggers the same DNS handoff.

## 7. Remaining Implementation Inputs

- Select the supported Node.js build version and non-root UID/GID for each image.
- Define writable paths and verify permissions on the SELinux-disabled RHEL 9.8 host.
- Set actual PostgreSQL network and `PGDATA` volume. Once the backup schema is implemented, define its separate working-repository volume, completed-export host mount, and DNS names in supported config; the proposed backup fields are not currently accepted.
- Configure the remote tunnel DNS suffixes. The Development Gateway reaches every configured service/port without host publication; each service must enforce its own authentication and authorization.
