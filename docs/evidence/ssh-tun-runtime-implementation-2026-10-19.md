# SSH TUN runtime implementation and validation (2026-10-19)

## Implemented scope

This record covers the opt-in Gateway SSH TUN lifecycle. Checked-in
configuration leaves it disabled. No production key, SSH pool, OpenVPN profile,
host return route, or active Gateway service was used.

- `AuthorizedKeysCommand` runs a fixed root-owned Python helper. It checks the
  dedicated account, strict Ed25519 key format, exact root-managed key allow
  list, and normalized `%C` endpoint pairs before reserving a bounded slot.
  Repeated key queries are idempotent. Pending slots expire after 60 seconds
  during later auth or PAM lifecycle events; no watcher runs.
- Required root `pam_exec.so` hooks create a user-owned TUN only after
  authenticated session open. Close removes only the recorded interface and
  shared-forwarding lease. SSH sessions cannot retain `NET_ADMIN`.
- The forced command rejects non-empty original commands, reports the
  client-side address pair, and holds the requested session. Clients must omit
  `ssh -N`.
- Shared forwarding uses one ownership-checked nftables table and an owner
  lease per OpenVPN or SSH session. It allows TUN-to-configured-Podman traffic
  and established replies, drops Podman-to-Podman forwarding, and adds no NAT.
- Quadlet templates a deterministic host return route for each enabled pool.
  It uses protocol 186 and exact pool/next-hop cleanup. Checked-in SSH TUN and
  OpenVPN settings remain disabled.

## Isolated acceptance

The real test used rootful Podman, temporary generated Ed25519 keys, a
temporary host key and certificate, a disposable bridge network, and the local
`localhost/gateway:1` image. `podman info` reported
`rootless=false runtime=crun podman=5.8.2`; `ssh -V` inside the built image
reported `OpenSSH_10.0p2 Debian-7+deb13u4`. This matches the upstream OpenSSH
version in the separate permission probe, but does not establish target-host
acceptance.

`RUN_GATEWAY_SSH_TUN_INTEGRATION=1 uv run --locked python -m pytest -q tests/scripts/test_gateway_ssh_tun_integration.py`
passed: one real SSH TUN integration test. It authenticated two concurrent
clients using the same key, sent TCP packets through both tunnels, confirmed
the receiver saw each original source address, disconnected one client,
confirmed the other tunnel still carried traffic, and verified the final
session removed only owned forwarding/interface state. The test confirmed the
temporary connected route for the disposable Podman bridge was absent after
cleanup. It did not install a host return route.

The integration test uses a synthetic Gateway network and receiver route. It
does not activate the production pool, add a host return route, inspect
application containers, read or mount any OpenVPN profile, or change host
security settings. Podman created and removed only the test bridge and its
connected route. OpenVPN coexistence is covered by synthetic shared-lease
tests, not a live OpenVPN connection.

The image's `/etc/pam.d/sshd` marks `pam_loginuid` optional because this
container lacks `CAP_AUDIT_CONTROL` and cannot set the host audit login UID.
The SSH TUN `pam_exec` hook remains required. Its command sets a fixed system
`PATH` because PAM omits the sbin directories needed to find `nft`. The runtime
also accepts the numeric account UID and peer address field emitted by
iproute2.

### PAM hook UID proof

The installed test-host `pam_exec(8)` manual states that its default executes a
command with the PAM caller's real UID; `seteuid` instead uses the caller's
effective UID. It does not switch the command to the authenticated PAM user's
credentials. The rebuilt Debian 13 image uses `libpam-modules` 1.7.0-5.

The opt-in integration test adds test-only `pam_exec` loggers immediately
before the real hook. They run `id -ru` and `id -u` for `open_session`, with
logs stored only inside the disposable Gateway container. The test uses
generated developer and tunnel keys. Before removing `seteuid`, a normal
developer login and two concurrent TUN sessions logged real/effective UIDs
`0`; the tunnel test passed. After removing it, the rebuilt image logged the
same UIDs for the developer login and both TUN sessions, and the root-guarded
lifecycle hook still created and removed the tunnels. Developer login therefore
works with SSH TUN enabled, and the root requirement remains enforced.

Only the disposable container's `/etc/pam.d/sshd` received these logger lines.
The test made no host PAM changes. The built image contains no test logger.

## Checks and limits

Commands and results from the final worktree:

- `uv run --locked python -m pytest -q`: 163 passed, 1 integration test skipped by
  default. The skip is the separately gated disposable SSH TUN test.
- `uv run --locked python -m pytest -q tests/scripts/test_gateway_ssh_tun_runtime.py tests/scripts/test_gateway_remote_forwarding.py tests/scripts/test_gateway_openvpn_runtime.py tests/scripts/test_gateway_remote_access.py tests/scripts/test_gateway_host_preflight.py`:
  130 passed.
- `RUN_GATEWAY_SSH_TUN_INTEGRATION=1 uv run --locked python -m pytest -q tests/scripts/test_gateway_ssh_tun_integration.py`:
  1 passed with `seteuid` in 41.34 seconds, then 1 passed without it in
  41.65 seconds. Both runs included the developer login and test-only PAM UID
  logger assertions.
- `bash tests/scripts/test-gateway-config.sh`: passed all configuration,
  route-rendering, and read-only cleanup checks.
- `podman build --tag localhost/gateway:1 --file gateway/development/Containerfile gateway/development`:
  passed; final image ID
  `f4397a31c418da5039282056ca3027693b1648e330d13a53c4acb7c1497cc482`.
- `bash tests/scripts/test-gateway-container.sh`: passed mount validation,
  image policy, SSH key authentication, DNS record refresh, Cockpit TLS, and
  clean shutdown.
- `uv lock --check`: passed.
- `uv run ruff check` on changed runtime modules and focused tests: passed.
  `tests/scripts/test_gateway_host_preflight.py` passed with only its existing
  `PLR0402` import-alias rule ignored.
- `uv run ruff format --check` on changed runtime/test files and the changed
  ranges in `scripts/gateway/config_validation.py` and
  `scripts/gateway/host_preflight.py`: passed.
- `bash -n gateway/development/startup.sh scripts/deploy-gateway.sh scripts/host-preflight.sh tests/scripts/test-gateway-config.sh tests/scripts/test-gateway-container.sh`
  and `git diff --check`: passed.
- `uv run ruff check .`: reported four existing findings outside the
  implementation: import ordering in `test_gateway_config_validation.py`,
  the existing `PLR0402` alias in `test_gateway_host_preflight.py`, and import
  ordering plus an unused import in `test_strict_json.py`. They were not
  broadened into unrelated cleanup.
- `shellcheck -s bash` on changed shell files: attempted; command unavailable
  because `shellcheck` is not installed.

The tests cover key validation before allocation, capacity, stable and
concurrent reservations, expiry, route-conflict preflight, user-owned TUN
verification, cleanup isolation, and shared forwarding leases.

Not verified: RHEL 9.8 / Podman 5.8.2 target acceptance, live Quadlet
activation, actual host return-route installation, DNS forwarding or DNS
lifecycle, OpenVPN profile review or live OpenVPN coexistence, abrupt TCP-loss
cleanup timing, reconnect races, Windows/VM forwarding, or operator approval
of production inputs. `ClientAliveInterval 15` with
`ClientAliveCountMax 3` bounds abrupt-loss detection, but the 45-second cleanup
path was not timed in this test. Production remains disabled.
