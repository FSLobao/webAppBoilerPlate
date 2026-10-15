# Application Gateway Plan

**Status:** Design plan; implementation blocked on the open decisions below.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)

## 1. Goal and Boundary

Provide HTTP/HTTPS access to application services through a component separate from the Development Gateway. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use a maintained, efficient Linux image for the Gateway, preferably Debian or Alpine; keep container image selection independent from the host distribution. The Application Gateway handles user traffic only. It does not provide SSH, Cockpit, Podman administration, or developer maintenance access.

The external security perimeter remains responsible for network reachability and organizational access controls. Application-level authentication and authorization remain the responsibility of each application unless an explicitly approved gateway policy says otherwise.

## 2. Contract

- Keep the Application Gateway separate from the Development Gateway.
- Do not use it as a maintenance path to containers or the host.
- Publish the routes declared in `config/host_config.json`; there is no separate per-service approval workflow. Do not route PostgreSQL through the public Application Gateway by default.
- Keep each application's Podman network isolated. Do not introduce a shared application network to simplify proxy routing.
- Treat DNS names, routes, certificates, and upstream service identities as configuration, not container IP identities.
- Do not claim TLS, authentication, or external DNS responsibilities until their owners are defined.

## 3. Proposed Traffic Flow

```text
User
  -> external security perimeter
  -> approved host address and published port
  -> Application Gateway
  -> declared frontend or backend endpoint
```

The baseline uses one shared Nginx Application Gateway. Attach it only to application networks needed by the routes declared in JSON, not database-only networks. This limits its reach compared with the Development Gateway, which intentionally attaches to every configured network.

The Development Gateway's NAT is a separate path for direct TCP access such as SSH. It does not replace this HTTP Application Gateway or publish its private upstream ports.

Use same-origin path routing by default: `http://<domain>/app` serves the frontend, and `http://<domain>/app/api/<route>` forwards to FastAPI. Nginx must match `/app/api/` before the SPA route and must not let the frontend fallback capture API requests. Configure Vite's asset base as `/app/`. A separate API hostname remains an alternative only when separate consumers or ownership justify CORS and extra DNS/TLS.

## 4. Decisions Required

1. Confirm Nginx's route-based application-network reach is sufficient for all declared public routes; the Development Gateway remains attached to every network.
2. Port 80 is unencrypted HTTP. Where must TLS terminate before credentials or sensitive traffic are sent, and who owns certificates?
3. Who manages public DNS and the external perimeter rule for the configured listener address?
4. Should Nginx strip `/app/api` before proxying, with FastAPI routes mounted at `/`, or preserve the prefix end-to-end?
5. Are per-application rate limits or request-size limits required, and which layer owns them?

Use the repository-pinned Nginx image and publish the configured host address/port; default the port to TCP 80. Resolve TLS termination before sending credentials or sensitive data over an external connection.
Use the repository-pinned Nginx image and configure all published addresses, ports, and routes in JSON. The initial listener is TCP 80; TLS remains a separate perimeter decision.

## 5. Implementation Phases

### Phase 0: Resolve ownership and topology

- Answer the decisions above with the infrastructure and application owners.
- Define public endpoint inventory, network attachments, TLS boundary, and certificate ownership.
- Confirm the upstream service names and ports from [Application Stack Plan](application-stack-plan.md).

### Phase 1: Versioned routing configuration

- Define each route with application prefix, frontend upstream, API prefix `/app/api/`, backend upstream, and health endpoint. Reject duplicate/overlapping prefixes, undeclared upstreams, and any route to PostgreSQL.
- Treat an absent `http_port` as `80`; require an explicit host bind address. Reject invalid/occupied ports, duplicate routes, and undeclared upstreams.
- Normalize `/app` to `/app/`. Match `/app/api/` before `/app/`; never send API paths to the SPA fallback. Configure Vite's base path as `/app/` and FastAPI's forwarded prefix/OpenAPI URLs consistently.
- Keep certificate contents and private keys outside Git and container images. Mount only required files read-only.
- Define atomic config replacement, syntax validation, reload behavior, and rollback to the last known-good configuration.

### Phase 2: Container lifecycle and integration

- Add the Nginx image and lifecycle using rootful Podman Quadlet. Publish configured host address and port (default `80`) to container TCP port `80`; fail preflight if the address or port is occupied.
- Attach Nginx only to application networks needed by declared routes. Do not attach it to database-only networks or enable general routing between application networks.
- Add readiness and health behavior that distinguishes proxy failure from unavailable upstreams.

### Phase 3: RHEL 9.8 / Podman 5.8.2 acceptance

- Validate image provenance/pinning, Quadlet behavior, SELinux mounts, restart/reboot behavior, and external bind addresses on a disposable RHEL 9.8 / Podman 5.8.2 host.
- Verify malformed route configuration fails without changing active routes or service state.
- Verify reload failure preserves the last known-good config and active service.

## 6. Acceptance Checks

- Approved HTTP and HTTPS routes reach only their declared upstreams.
- Unknown hosts and paths do not fall through to an unintended application.
- PostgreSQL, the Development Gateway, Cockpit, SSH, and Podman API are not reachable through this component.
- Application networks remain isolated; tests attempt cross-application access through both the proxy and upstream services.
- TLS behavior, certificate rotation, and external perimeter ownership match the recorded decision.
- Stopping an upstream produces a defined health/error response without exposing internal details or secrets.
- Config update, rollback, restart, and reboot work without deleting application data.

## 7. Unresolved Questions

The initial proposal is one Nginx listener on configured host address/TCP 80 with `/app` and `/app/api/` routes. TLS termination and external DNS/perimeter ownership remain open; plain HTTP must not carry sensitive credentials unless an upstream trusted layer provides TLS.
