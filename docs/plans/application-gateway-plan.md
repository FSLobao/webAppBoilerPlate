# Application Gateway Plan

**Status:** Route defaults and v1 config validation are selected; NGINX runtime deployment remains pending.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)

## 1. Goal and Boundary

Provide HTTP/HTTPS access to application services through a component separate from the Development Gateway. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use a maintained, efficient Linux image for the Gateway, preferably Debian or Alpine; keep container image selection independent from the host distribution. The Application Gateway handles user traffic only. It does not provide SSH, Cockpit, Podman administration, or developer maintenance access.

The external security perimeter provides TLS termination, certificates, public DNS, and network reachability. It forwards approved HTTP traffic to the configured host listener. Application-level authentication and authorization remain the responsibility of each application.

## 2. Contract

- Keep the Application Gateway separate from the Development Gateway.
- Do not use it as a maintenance path to containers or the host.
- Publish the routes declared in `config/host_config.json`; there is no separate per-service approval workflow. Do not route PostgreSQL through the public Application Gateway by default.
- Keep unique per-app networks and do not route between them. The selected topology also connects every app container to `shared`; members have direct network reach and must enforce service authentication.
- Treat DNS names, routes, certificates, and upstream service identities as configuration, not container IP identities.
- NGINX is the only HTTP provider. Install it only when the optional `application_gateway` section is enabled; the minimum config installs no NGINX or application services.
- Map NGINX container TCP port `80` to configured host port `8080` by default.
- External perimeter, public DNS, certificates, and TLS termination are assumed to be provided outside this host-and-container plan.

## 3. Proposed Traffic Flow

```text
User
  -> external security perimeter
  -> approved host address and published port (default `8080`)
  -> Application Gateway
  -> declared frontend or backend endpoint
```

When enabled, one shared NGINX Application Gateway serves every declared HTTP route. The selected config attaches NGINX to `shared`; PostgreSQL and all app containers also join `shared`. NGINX therefore has direct network reach to PostgreSQL even without a database HTTP route. The requester accepts this shared-network connectivity; PostgreSQL authentication remains the control. A route omission is not a network isolation control.

The Development Gateway is separate. It does not publish user HTTP routes or replace the Application Gateway.

Use same-origin path routing: public `https://<domain>/app` serves the frontend, and `https://<domain>/app/api/<route>` reaches FastAPI with the prefix preserved. The external perimeter terminates TLS and forwards HTTP to the host listener. NGINX matches `/app/api/` before `/app`; both routes proxy to `webApp:8000`. FastAPI serves built Vite assets and API routes in one process. Configure Vite's asset base as `/app/`. A separate API hostname is out of the default design.

## 4. Selected Defaults

- `schema_version: 1` remains required. The validator accepts an optional `application_gateway` section and route/upstream ports; NGINX runtime deployment remains unimplemented.
- Bind NGINX to `0.0.0.0:8080` for the DHCP-assigned host address; publish container TCP port `80`. External perimeter forwards traffic to the host's current address.
- Route `/app` and `/app/api/` to the combined `webApp:8000` listener, preserving `/app/api/`. Configure FastAPI forwarded prefix and OpenAPI URLs consistently.
- Do not configure NGINX rate limiting by default. Set the default maximum uploaded file size and NGINX request-body limit to 1 GB. Keep both configurable; enforce total file size in the TUS service.
- Use the repository-pinned NGINX image. External perimeter owns public DNS, certificates, TLS termination, and forwarding to the host listener.
- Enable TUS upload and NGINX basic file sharing only when their optional service configuration is present. Default basic file sharing to read-only.

## 5. Implementation Phases

### Phase 0: Resolve ownership and topology

- Define configured public endpoint inventory and NGINX network attachments. External perimeter inputs are assumed and remain outside this plan's ownership.
- Confirm the upstream service names and ports from [Application Stack Plan](application-stack-plan.md).

### Phase 1: Versioned routing configuration

- Define `/app` and `/app/api/` routes to the combined `webApp:8000` upstream, preserving the API prefix. Reject duplicate/overlapping prefixes, undeclared upstreams, and any route to PostgreSQL.
- Treat an absent `http_port` as `8080`; default the listener address to `0.0.0.0` for the assigned host IP. Reject invalid/occupied ports, duplicate routes, and undeclared upstreams.
- Normalize `/app` to `/app/`. Match `/app/api/` before `/app/`; preserve the API prefix and never send API paths to the SPA fallback. Configure Vite's base path as `/app/` and FastAPI's forwarded prefix/OpenAPI URLs consistently.
- Set NGINX request-body limit to 1 GB by default, with no rate limits. Configure the TUS service to reject files larger than 1 GB by default.
- Add optional TUS and read-only NGINX file-sharing routes only when declared. Reject duplicate/overlapping prefixes and undeclared upstreams.
- Define atomic config replacement, syntax validation, reload behavior, and rollback to the last known-good configuration.

### Phase 2: Container lifecycle and integration

- Add the NGINX image and lifecycle using rootful Podman Quadlet only when `application_gateway` is enabled. Bind `0.0.0.0:8080` to container TCP port `80`; fail preflight if the port is occupied.
- Attach NGINX to `shared`. PostgreSQL is also on `shared`, so NGINX has network reach to it; omit database HTTP routes and rely on PostgreSQL authentication.
- Configure optional TUS and basic file-sharing endpoints only when declared.
- Add readiness and health behavior that distinguishes proxy failure from unavailable upstreams.

### Phase 3: RHEL 9.8 / Podman 5.8.2 acceptance

- Validate image provenance/pinning, Quadlet behavior, restart/reboot behavior, and external bind addresses on the authorized disposable RHEL 9.8 / Podman 5.8.2 host with SELinux disabled. Do not change host security settings.
- Verify malformed route configuration fails without changing active routes or service state.
- Verify reload failure preserves the last known-good config and active service.

## 6. Acceptance Checks

- Approved HTTP and HTTPS routes reach only their declared upstreams.
- Unknown hosts and paths do not fall through to an unintended application.
- PostgreSQL, the Development Gateway, Cockpit, SSH, and Podman API are not reachable through this component.
- App-specific networks have no routing between them. Test direct shared-network reach separately and verify each service's authentication blocks unauthorized cross-service access.
- External perimeter forwards TLS-protected public traffic to the configured host listener. Perimeter behavior and certificate rotation are assumed, not validated here.
- Stopping an upstream produces a defined health/error response without exposing internal details or secrets.
- Config update, rollback, restart, and reboot work without deleting application data.

## 7. Unresolved Questions

The selected host listener is `0.0.0.0:8080` mapped to NGINX TCP `80`. External TLS, DNS, and perimeter forwarding are assumed. Application routes use `/app` and `/app/api/*`, both proxying to `webApp:8000`; TUS and read-only file sharing are optional features. The default upload limit is 1 GB with no NGINX rate limit.

The selected single FastAPI process serves static assets and API on `webApp:8000` and holds PostgreSQL credentials. Browser assets do not receive those credentials; verify they never appear in build output or HTTP responses. PostgreSQL remains on `shared`; NGINX has network reach to it but must not declare a database HTTP route.
