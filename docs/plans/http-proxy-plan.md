# HTTP Proxy Plan

**Status:** Initial route paths and static v1 config validation are selected; NGINX runtime deployment/readiness remains pending. `http_proxy.enabled` is a desired declaration to validate, not evidence of deployed or successful runtime behavior.
**Contract:** [Web Application Boilerplate Architecture](../contracts/WEB_APP_BOILERPLATE_ARCHITECTURE.md)

## 1. Goal and Boundary

Provide an optional shared NGINX HTTP reverse proxy for HTTP application routes. It is not the Development Gateway and does not define a general-purpose application-access entity. The Development Gateway provides developers routed access to all configured container services and ports without requiring host port publication. End-user non-HTTP services are exposed directly using explicit host bind address, protocol, and published port declarations, with service-owned authentication and perimeter controls. Host deployment targets RHEL 9.8 with rootful Podman 5.8.2. Use a maintained, efficient Linux image, preferably Debian or Alpine; keep container image selection independent from the host distribution.

The external security perimeter provides TLS termination, certificates, public DNS, and end-user authentication. For HTTP, it injects the trusted `X-USER` identity fields and forwards approved traffic to the configured host listener. The application uses those fields to authorize users; NGINX only proxies and is not a login or authentication engine.

## 2. Contract

- Keep the HTTP proxy optional and separate from the Development Gateway. It handles HTTP only and is not a general application-access gateway.
- Do not use the HTTP proxy as a maintenance path to containers or the host.
- Declare HTTP routes and direct non-HTTP service publication in `config/host_config.json`; there is no separate per-service approval workflow. The proxy can route to HTTP services across applications, each with its configured upstream and port. Do not route PostgreSQL through the HTTP proxy.
- Keep unique per-app Podman networks and do not route between them. The selected topology also connects every app container to `shared`; this is a Podman bridge, not a host/physical interface or VPN route/pool. Members have direct network reach and must enforce service authentication.
- Treat DNS names, routes, certificates, and upstream service identities as configuration, not container IP identities.
- NGINX is the only HTTP provider. The optional `http_proxy` section expresses desired NGINX/routes and enables static validation; runtime NGINX and upstream deployment occurs only in the post-Gateway application phase. The minimum config installs no NGINX or application services.
- When `http_proxy` is enabled, its v1 config must explicitly provide `listen_address` and `http_port`. The selected values are `0.0.0.0` and `8080`, mapped to NGINX container TCP port `80`; these are not implicit defaults.
- External perimeter, public DNS, certificates, and TLS termination are assumed to be provided outside this host-and-container plan.
- The perimeter must strip or replace spoofable user identity fields and be the only trusted source of `X-USER` identity. Direct Development Gateway access or direct host HTTP-listener access never establishes trusted identity. Protected endpoints reject absent or untrusted identity. Exact identity-header allowlist and provenance mechanism are unresolved implementation prerequisites; a network CIDR or raw header alone does not establish authentication.

## 3. Proposed Traffic Flow

```text
User
  -> external security perimeter
  -> approved host address and explicitly configured published port (selected `8080`)
  -> optional NGINX HTTP reverse proxy
  -> configured application HTTP upstream
```

When enabled, one shared NGINX HTTP reverse proxy serves every declared HTTP route across configured applications; each route may target its own configured upstream and port. NGINX may also serve optional read-only static files/downloads outside the SPA. The selected initial application is `webApp`: its `/app/` and `/app/api/` routes use the same `webApp:8000` listener. This initial-app choice does not restrict future routes or applications to that upstream or port.

The selected config attaches NGINX to `shared`; PostgreSQL and all app containers also join `shared`. NGINX therefore has direct network reach to PostgreSQL even without a database HTTP route. The requester accepts this shared-network connectivity; PostgreSQL authentication remains the control. A route omission is not a network isolation control.

The Development Gateway is solely for developer access to all configured container ports and services. Its routed reachability does not depend on host-published ports. It must bootstrap before NGINX or application containers and must not require or start them; app target readiness is owned by application deployment.

For the selected initial application, use same-origin path routing: public `https://<domain>/app/` serves the built SPA, and `https://<domain>/app/api/<route>` reaches FastAPI with the prefix preserved. The external perimeter terminates TLS and forwards HTTP to the host listener. NGINX matches `/app/api/` before `/app/`; both routes proxy to the single `webApp:8000` listener. FastAPI serves built Vite assets under `/app/` and API routes under `/app/api/` in one process. Configure Vite's asset base as `/app/`. Additional applications can configure independent routes/upstreams and ports; a separate API hostname is not part of the initial app contract.

## 4. Selected Defaults

- `schema_version: 1` remains required. The optional `http_proxy` section requires explicit `listen_address` and `http_port` values under the current v1 schema; the selected values are `0.0.0.0` and `8080`. NGINX runtime deployment remains unimplemented.
- Bind NGINX at the explicitly configured `0.0.0.0:8080` for the DHCP-assigned host address; publish container TCP port `80`. External perimeter forwards traffic to the host's current address.
- For the selected initial `webApp` application, route `/app/` and `/app/api/` to the same combined `webApp:8000` listener, preserving `/app/api/`. Other applications may configure their own HTTP upstreams and ports. FastAPI in `webApp` serves its built SPA and API on this one listener. Configure its forwarded prefix and OpenAPI URLs consistently.
- Do not configure NGINX rate limiting by default. Set the default maximum uploaded file size and NGINX request-body limit to 1 GB. Keep both configurable; enforce total file size in the TUS service.
- Use the repository-pinned NGINX image. External perimeter owns public DNS, certificates, TLS termination, and forwarding to the host listener.
- Enable TUS upload and NGINX basic file sharing only when their optional service configuration is present. Default basic file sharing to read-only.
- Before enabling protected HTTP routes, deployment must gate access to the `0.0.0.0:8080` listener: require effective ingress restriction to the trusted perimeter or verified perimeter-to-application identity provenance. Neither Gateway bypass access, a network CIDR, nor an unverified raw `X-USER` header proves user authentication. NGINX does not authenticate users.
- Keep the exact `X-USER` field allowlist and the mechanism proving trusted perimeter provenance unresolved until implementation is defined and verified. Do not invent identity header names or claim runtime authentication/authorization is implemented.

## 5. Implementation Phases

### Phase 0: Resolve ownership and topology

- Define configured public endpoint inventory and NGINX network attachments. External perimeter inputs are assumed and remain outside this plan's ownership.
- Confirm the upstream service names and ports from [Application Stack Plan](application-stack-plan.md).
- Keep `http_proxy.enabled` as desired-state declaration/static-validation input only. Do not interpret it as implementation or runtime success.

### Phase 1: Versioned routing configuration

- Define `/app/` and `/app/api/` routes for the initial `webApp` application to its combined `webApp:8000` upstream, preserving the API prefix. Other applications may declare separate routes to their configured upstreams and ports; do not impose `webApp:8000` as a global route restriction.
- Planned validator gate: reject routes targeting PostgreSQL. The current validator does not yet enforce this rule; do not treat it as implemented until added and tested.
- Reject malformed route configuration, duplicate declarations, and references to undeclared networks/containers before mutation even when NGINX or upstream containers are absent. Absence at runtime is readiness-pending, not a reason for Gateway bootstrap to fail.
- Require explicit `listen_address` and `http_port` fields whenever the optional `http_proxy` section is present. The selected values are `0.0.0.0` and `8080`; reject missing or invalid values and occupied ports.
- Normalize `/app` to `/app/`. Match `/app/api/` before `/app/`; preserve the API prefix and never send API paths to the SPA fallback. Configure Vite's base path as `/app/` and FastAPI's forwarded prefix/OpenAPI URLs consistently.
- Set NGINX request-body limit to 1 GB by default, with no rate limits. Configure the TUS service to reject files larger than 1 GB by default.
- Add optional TUS and read-only NGINX file-sharing routes only when declared. Reject duplicate/overlapping prefixes and undeclared upstreams.
- Define atomic config replacement, syntax validation, reload behavior, and rollback to the last known-good configuration.

### Phase 2: Container lifecycle and integration

- Run this phase only after the shared Development Gateway is healthy. Application deployment owns NGINX image/lifecycle and app container creation, startup, health, and readiness. The Gateway must never create, start, inspect, or otherwise operate NGINX or its upstream containers.
- Stage and validate any network/container/route/DNS changes against the complete shared versioned host config, including compatibility of existing networks, then atomically update it while preserving unrelated objects and operator inputs. Create missing application networks and reconcile the existing Gateway for added network declarations before creating/starting application containers; do not deploy a second Gateway.
- Add the NGINX image and lifecycle using rootful Podman Quadlet only when `http_proxy` is enabled. Bind `0.0.0.0:8080` to container TCP port `80`; fail application-phase preflight if the port is occupied.
- Attach NGINX to `shared`. PostgreSQL is also on `shared`, so NGINX has network reach to it; omit database HTTP routes and rely on PostgreSQL authentication.
- Configure optional TUS and basic file-sharing endpoints only when declared.
- Add readiness and health behavior that distinguishes proxy failure from unavailable upstreams. Publish/reload routes only after NGINX and each route target pass their owning readiness checks. A valid route declaration alone is not readiness.
- On service stop, replacement, or failed readiness, retain no route to an unready upstream after the application phase reconciles state. For development DNS targets use the revision-scoped Development Gateway handoff; absent/stopped targets remain pending and produce no record, and Gateway does not start them.

### Phase 3: RHEL 9.8 / Podman 5.8.2 acceptance

- Validate image provenance/pinning, Quadlet behavior, restart/reboot behavior, and external bind addresses on the authorized disposable RHEL 9.8 / Podman 5.8.2 host with SELinux disabled. Do not change host security settings.
- Verify malformed route configuration fails without changing active routes or service state.
- Verify reload failure preserves the last known-good config and active service.
- Verify the clean-host order: Gateway bootstraps first with no application or NGINX containers even when their optional declarations exist; then app deployment creates and readies upstreams and NGINX without changing unrelated host-config objects.
- Verify an absent, stopped, or unhealthy upstream does not make Gateway bootstrap fail and is not represented as a successful route deployment. Public routes become active only after NGINX/upstream readiness and the protected-route perimeter/provenance gate; a failed staged config or incompatible network fails before mutation.

## 6. Acceptance Checks

- Approved HTTP routes reach only their declared upstreams. HTTPS/TLS termination belongs to the external perimeter.
- Verify the selected initial application serves `/app/` and `/app/api/` through `webApp:8000`, while separate declared HTTP applications can route to their own configured upstreams and ports.
- Unknown hosts and paths do not fall through to an unintended application.
- PostgreSQL, the Development Gateway, Cockpit, SSH, and Podman API are not reachable through this component. PostgreSQL-route rejection is a planned validator gate and must be covered by tests before claiming it is enforced.
- App-specific networks have no routing between them. Test direct shared-network reach separately and verify each service's authentication blocks unauthorized cross-service access.
- External perimeter forwards TLS-protected public traffic to the configured host listener. Perimeter behavior and certificate rotation are assumed, not validated here.
- Stopping an upstream produces a defined health/error response without exposing internal details or secrets.
- Config update, rollback, restart, and reboot work without deleting application data.
- `http_proxy.enabled` is reported as desired declaration/static validation only until NGINX runtime acceptance has actually passed.

## 7. Selected Contract and Implementation Prerequisites

The current v1 `http_proxy` section requires explicit `listen_address` and `http_port`; the selected values are `0.0.0.0` and `8080`, mapped to NGINX TCP `80`. No absent-field fallback is specified. External TLS, DNS, authentication, and perimeter forwarding are assumed. The initial application routes use `/app/` and `/app/api/*`, both proxying to the single `webApp:8000` listener; other applications may configure their own upstreams and ports. TUS and read-only file sharing are optional features. The default upload limit is 1 GB with no NGINX rate limit.

The selected single FastAPI process serves the built SPA at `/app/` and API at `/app/api/` on `webApp:8000` and holds PostgreSQL credentials. The external perimeter authenticates users, strips/replaces client-supplied identity fields, and supplies trusted `X-USER` identity fields; the application uses them for authorization. NGINX only proxies. Browser assets do not receive PostgreSQL credentials; verify they never appear in build output or HTTP responses. PostgreSQL remains on `shared`; NGINX has network reach to it but must not declare a database HTTP route. Direct host or Development Gateway reachability is not trusted identity, and protected application endpoints reject missing or untrusted identity. Before protected routes are enabled, deployment must verify effective ingress restriction to the trusted perimeter or verified identity provenance through to the application. The exact `X-USER` allowlist and provenance mechanism are implementation prerequisites, not open decisions about the selected authentication/authorization model.
