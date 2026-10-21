#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly DEPLOY_SCRIPT="$REPO_ROOT/scripts/deploy-gateway.sh"
readonly PREFLIGHT_SCRIPT="$REPO_ROOT/scripts/host-preflight.sh"
readonly SAMPLE_CONFIG="$REPO_ROOT/config/host_config.json"
readonly TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

expect_invalid() {
    local label=$1 config_path=$2 script

    for script in "$DEPLOY_SCRIPT" "$PREFLIGHT_SCRIPT"; do
        if "$script" --validate-config "$config_path" >/dev/null 2>&1; then
            fail "$label was accepted by ${script##*/}"
        fi
    done
    printf 'PASS: %s rejected\n' "$label"
}

jq '.networks = [
        {"name":"shared","subnet":"10.89.1.0/24","gateway_address":"10.89.1.2"},
        {"name":"project-a-net","subnet":"10.89.2.0/24"},
        {"name":"newly-added-net","subnet":"10.89.3.0/24"}
    ] |
    .containers = [
        {"name":"nginx","networks":["shared","newly-added-net"]},
        {"name":"project-a-backend","networks":["project-a-net","shared","newly-added-net"]}
    ] |
    .http_proxy = {
        "enabled":true,
        "listen_address":"0.0.0.0",
        "http_port":8080,
        "routes":[{
            "prefix":"/app",
            "frontend":"project-a-backend",
            "frontend_port":8000,
            "api_prefix":"/app/api/",
            "backend":"project-a-backend",
            "backend_port":8000
        }]
    } |
    .dns_records = [{"name":"backend.project-a.dev.anatel","container":"project-a-backend","network":"project-a-net"}]' \
    "$SAMPLE_CONFIG" > "$TMP_DIR/valid.json"
"$DEPLOY_SCRIPT" --validate-config "$TMP_DIR/valid.json" >/dev/null
"$PREFLIGHT_SCRIPT" --validate-config "$TMP_DIR/valid.json" >/dev/null
printf 'PASS: valid configuration accepted\n'

bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json" "$TMP_DIR/rendered.container"
mapfile -t rendered_networks < <(grep '^Network=' "$TMP_DIR/rendered.container")
expected_networks=(
    'Network=shared:ip=10.89.1.2'
    'Network=project-a-net'
    'Network=newly-added-net'
)
[[ "${rendered_networks[*]}" == "${expected_networks[*]}" ]] || \
    fail "Gateway Quadlet networks differ from top-level Podman declarations: ${rendered_networks[*]}"
printf 'PASS: all declared Podman networks are rendered; HTTP proxy routes are not networks\n'

jq '.gateway.remote_access.openvpn |= . + {
        "enabled":true
    }' "$TMP_DIR/valid.json" > "$TMP_DIR/openvpn-enabled.json"
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-enabled.json" "$TMP_DIR/openvpn.container"
grep -Fxq -- \
    'Volume=/etc/gateway/openvpn/ERMXDF02.ovpn:/run/openvpn/client.ovpn:ro' \
    "$TMP_DIR/openvpn.container" || fail 'OpenVPN profile was not mounted read-only'
grep -Fxq 'AddDevice=/dev/net/tun' "$TMP_DIR/openvpn.container" || \
    fail 'OpenVPN TUN device was not added'
grep -Fxq 'AddCapability=NET_ADMIN' "$TMP_DIR/openvpn.container" || \
    fail 'OpenVPN minimum network capability was not added'
grep -Fxq \
    'ExecStartPost=/usr/sbin/ip -4 route add 172.24.0.0/21 via 10.89.1.2 proto 186' \
    "$TMP_DIR/openvpn.container" || fail 'OpenVPN host return route was not rendered'
grep -Fxq \
    'ExecStopPost=-/usr/sbin/ip -4 route del 172.24.0.0/21 via 10.89.1.2 proto 186' \
    "$TMP_DIR/openvpn.container" || fail 'OpenVPN owned host route cleanup was not rendered'
if [[ -x /usr/lib/systemd/system-generators/podman-system-generator ]] || \
    [[ -x /usr/libexec/podman/quadlet ]]; then
    bash -c 'source "$1"; validate_quadlet_candidate "$2"' \
        _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn.container"
    printf 'PASS: host Quadlet generator accepts opt-in OpenVPN unit without activation\n'
fi
printf 'PASS: OpenVPN Quadlet opt-in mounts the opaque profile read-only and owns only the tagged return route\n'
jq '.gateway.remote_access.openvpn |= (del(.client_pool) + {
        "enabled":true
    })' "$TMP_DIR/valid.json" > "$TMP_DIR/openvpn-no-pool.json"
"$DEPLOY_SCRIPT" --validate-config "$TMP_DIR/openvpn-no-pool.json" \
    > "$TMP_DIR/openvpn-no-pool-validation.log" 2>&1
"$PREFLIGHT_SCRIPT" --validate-config "$TMP_DIR/openvpn-no-pool.json" \
    >> "$TMP_DIR/openvpn-no-pool-validation.log" 2>&1
grep -Fq 'client_pool is not configured' "$TMP_DIR/openvpn-no-pool-validation.log" || \
    fail 'Missing OpenVPN pool warning was not reported'
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-no-pool.json" "$TMP_DIR/openvpn-no-pool.container"
if grep -Eq '^Exec(Start|Stop)Post=.*route (add|del) 172\.24\.' \
    "$TMP_DIR/openvpn-no-pool.container"; then
    fail 'OpenVPN without a client pool rendered a managed host route'
fi
printf 'PASS: enabled OpenVPN accepts missing client_pool with warning and no managed return route\n'
jq '.gateway.remote_access.ssh_tun = {
        "enabled":true,
        "account":"gateway-tunnel",
        "address_pool":"198.18.0.0/24",
        "authorized_keys_path":"/etc/gateway/ssh_tun/authorized_keys",
        "max_sessions":4
    }' "$TMP_DIR/valid.json" > "$TMP_DIR/ssh-tun-enabled.json"
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/ssh-tun-enabled.json" "$TMP_DIR/ssh-tun.container"
grep -Fxq \
    'Volume=/etc/gateway/ssh_tun/authorized_keys:/run/gateway/ssh_tun/authorized_keys:ro' \
    "$TMP_DIR/ssh-tun.container" || fail 'SSH TUN public keys were not mounted read-only'
grep -Fxq 'AddDevice=/dev/net/tun' "$TMP_DIR/ssh-tun.container" || \
    fail 'SSH TUN device was not added'
grep -Fxq 'AddCapability=NET_ADMIN' "$TMP_DIR/ssh-tun.container" || \
    fail 'SSH TUN minimum network capability was not added'
grep -Fxq \
    'ExecStartPost=/usr/sbin/ip -4 route add 198.18.0.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/ssh-tun.container" || fail 'SSH TUN host return route was not rendered'
grep -Fxq \
    'ExecStopPost=-/usr/sbin/ip -4 route del 198.18.0.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/ssh-tun.container" || fail 'SSH TUN owned host route cleanup was not rendered'
printf 'PASS: SSH TUN opt-in renders read-only keys, minimum capability, and one deterministic host route\n'
jq '.gateway.remote_access.wireguard = {
        "enabled":true,
        "host_bind_address":"127.0.0.1",
        "listen_port":54000,
        "address_pool":"198.18.1.0/24",
        "server_address":"198.18.1.1",
        "dns_server":"198.18.1.1",
        "server_private_key_path":"/etc/gateway/wireguard/test-server.key"
    }' "$TMP_DIR/valid.json" > "$TMP_DIR/wireguard-enabled.json"
"$DEPLOY_SCRIPT" --validate-config "$TMP_DIR/wireguard-enabled.json" >/dev/null
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-enabled.json" "$TMP_DIR/wireguard.container"
grep -Fxq \
    'Volume=/etc/gateway/wireguard/test-server.key:/run/gateway/wireguard/server.key:ro' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard server key was not mounted read-only'
grep -Fxq \
    'Volume=/var/lib/gateway/wireguard:/var/lib/gateway/wireguard:rw' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard public peer inventory was not persisted'
grep -Fxq 'AddCapability=NET_ADMIN' "$TMP_DIR/wireguard.container" || \
    fail 'WireGuard minimum network capability was not added'
grep -Fxq 'PublishPort=127.0.0.1:54000:54000/udp' "$TMP_DIR/wireguard.container" || \
    fail 'WireGuard UDP host publication was not rendered'
grep -Fxq \
    'ExecStartPost=/usr/sbin/ip -4 route add 198.18.1.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard host return route was not rendered'
grep -Fxq \
    'ExecStopPost=-/usr/sbin/ip -4 route del 198.18.1.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard host return route cleanup was not rendered'
printf 'PASS: WireGuard renders explicit UDP bind, read-only server key, persistent public peers, minimum capability, and owned return route\n'
mkdir -m 0700 "$TMP_DIR/wireguard-key-directory" "$TMP_DIR/key-bin"
jq --arg key_path "$TMP_DIR/wireguard-key-directory/server.key" \
    '.gateway.remote_access.wireguard.server_private_key_path = $key_path' \
    "$TMP_DIR/wireguard-enabled.json" > "$TMP_DIR/wireguard-key-config.json"
cat > "$TMP_DIR/key-bin/podman" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "$PODMAN_KEY_CALL_LOG"
if [[ "$*" == *'server-key validate'* ]]; then
    exit 0
fi
[[ "$*" == *'server-key generate'* ]] || exit 97
volume=''
filename=''
while (($#)); do
    case "$1" in
        --volume) volume=$2; shift 2 ;;
        --filename) filename=$2; shift 2 ;;
        *) shift ;;
    esac
done
[[ -n "$volume" && -n "$filename" ]] || exit 96
printf 'test-only-server-key\n' > "${volume%%:*}/$filename"
chmod 0600 "${volume%%:*}/$filename"
SH
chmod 0755 "$TMP_DIR/key-bin/podman"
PATH="$TMP_DIR/key-bin:$PATH" PODMAN_KEY_CALL_LOG="$TMP_DIR/key-generation.log" \
    bash -c 'source "$1"; ensure_wireguard_server_key "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-key-config.json" \
    > "$TMP_DIR/key-generation-output.log" 2>&1 || \
    fail 'WireGuard apply helper did not provision a missing server key'
[[ "$(stat -c %a "$TMP_DIR/wireguard-key-directory/server.key")" == 600 ]] || \
    fail 'Generated WireGuard server key mode was not 0600'
grep -Fq 'server-key generate --filename server.key' "$TMP_DIR/key-generation.log" || \
    fail 'WireGuard key generator was not invoked for a missing key'
grep -Fq -- '--network none' "$TMP_DIR/key-generation.log" || \
    fail 'WireGuard key generator was not network-isolated'
grep -Fq -- '--read-only --cap-drop=all' "$TMP_DIR/key-generation.log" || \
    fail 'WireGuard key generator did not use a read-only, capability-free root filesystem'
grep -Fq -- \
    "--volume $TMP_DIR/wireguard-key-directory:/run/gateway/wireguard:rw,noexec,nosuid,nodev" \
    "$TMP_DIR/key-generation.log" || fail 'WireGuard key helper did not receive only the restricted key directory'
! grep -Fq 'test-only-server-key' "$TMP_DIR/key-generation-output.log" || \
    fail 'WireGuard private key contents were written to command output'
before=$(sha256sum "$TMP_DIR/wireguard-key-directory/server.key")
: > "$TMP_DIR/key-generation.log"
PATH="$TMP_DIR/key-bin:$PATH" PODMAN_KEY_CALL_LOG="$TMP_DIR/key-generation.log" \
    bash -c 'source "$1"; ensure_wireguard_server_key "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-key-config.json" \
    > "$TMP_DIR/key-reuse-output.log" 2>&1 || \
    fail 'WireGuard apply helper failed to reuse an existing server key'
after=$(sha256sum "$TMP_DIR/wireguard-key-directory/server.key")
[[ "$before" == "$after" ]] || fail 'WireGuard redeployment replaced an existing server key'
grep -Fq 'server-key validate' "$TMP_DIR/key-generation.log" || \
    { cat "$TMP_DIR/key-reuse-output.log" >&2; cat "$TMP_DIR/key-generation.log" >&2; \
        fail 'Existing WireGuard server key was not validated'; }
grep -Fq 'server.key:/run/gateway/wireguard/server.key:ro,noexec,nosuid,nodev' \
    "$TMP_DIR/key-generation.log" || fail 'Existing server key was not mounted read-only for validation'
! grep -Fq 'server-key generate' "$TMP_DIR/key-generation.log" || \
    fail 'WireGuard redeployment regenerated an existing server key'
printf 'PASS: WireGuard key is generated only when missing and reused for existing client profiles\n'
jq '.gateway.remote_access.openvpn |= . + {
        "enabled":true
    }' "$TMP_DIR/ssh-tun-enabled.json" > "$TMP_DIR/shared-remote-access.json"
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/shared-remote-access.json" "$TMP_DIR/shared.container"
[[ "$(grep -c '^AddDevice=/dev/net/tun$' "$TMP_DIR/shared.container")" == 1 ]] || \
    fail 'Shared OpenVPN and SSH TUN runtime duplicated TUN device grants'
[[ "$(grep -c '^AddCapability=NET_ADMIN$' "$TMP_DIR/shared.container")" == 1 ]] || \
    fail 'Shared OpenVPN and SSH TUN runtime duplicated NET_ADMIN grants'
printf 'PASS: concurrent OpenVPN and SSH TUN use one shared device grant and capability\n'
jq '.gateway.remote_access.wireguard = {
        "enabled":true,
        "host_bind_address":"127.0.0.1",
        "listen_port":54000,
        "address_pool":"198.18.1.0/24",
        "server_address":"198.18.1.1",
        "dns_server":"198.18.1.1",
        "server_private_key_path":"/etc/gateway/wireguard/test-server.key"
    }' "$TMP_DIR/shared-remote-access.json" > "$TMP_DIR/all-remotes.json"
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/all-remotes.json" "$TMP_DIR/all-remotes.container"
[[ "$(grep -c '^AddCapability=NET_ADMIN$' "$TMP_DIR/all-remotes.container")" == 1 ]] || \
    fail 'Concurrent remote transports duplicated NET_ADMIN grants'
[[ "$(grep -c '^PublishPort=.*\/udp$' "$TMP_DIR/all-remotes.container")" == 1 ]] || \
    fail 'Concurrent remote transports rendered an unexpected UDP publication'
printf 'PASS: all remote transports share one minimum NET_ADMIN grant\n'

mkdir -p "$TMP_DIR/route-bin"
cat > "$TMP_DIR/route-bin/ip" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$*" in
    '-j -4 route show table all 172.24.0.0/21')
        printf '%s\n' "$OPENVPN_ROUTE_STATE"
        ;;
        '-j -4 route show table all 198.18.0.0/24')
            printf '%s\n' "$SSH_TUN_ROUTE_STATE"
        ;;
    '-4 route del 172.24.0.0/21 via 10.89.1.2 proto 186')
        printf '%s\n' "$*" >> "$ROUTE_MUTATION_LOG"
        ;;
    '-4 route del 198.18.0.0/24 via 10.89.1.2 proto 186')
        printf '%s\n' "$*" >> "$ROUTE_MUTATION_LOG"
        ;;
    *) exit 97 ;;
esac
SH
chmod 0755 "$TMP_DIR/route-bin/ip"
jq '.gateway.remote_access.openvpn.enabled = false' "$TMP_DIR/valid.json" \
    > "$TMP_DIR/openvpn-disabled-route.json"
PATH="$TMP_DIR/route-bin:$PATH" \
    OPENVPN_ROUTE_STATE='[{"dst":"172.24.0.0/21","gateway":"10.89.1.2","protocol":"186","table":"main"}]' \
    ROUTE_MUTATION_LOG="$TMP_DIR/route-mutations.log" \
    bash -c 'source "$1"; remove_managed_remote_access_return_routes "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-disabled-route.json"
grep -Fxq -- \
    '-4 route del 172.24.0.0/21 via 10.89.1.2 proto 186' \
    "$TMP_DIR/route-mutations.log" || fail 'Owned OpenVPN return route was not cleaned'
PATH="$TMP_DIR/route-bin:$PATH" \
    OPENVPN_ROUTE_STATE='[{"dst":"172.24.0.0/21","gateway":"10.89.1.2","protocol":"static","table":"main"}]' \
    ROUTE_MUTATION_LOG="$TMP_DIR/foreign-route-mutations.log" \
    bash -c 'source "$1"; remove_managed_remote_access_return_routes "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-disabled-route.json"
[[ ! -e "$TMP_DIR/foreign-route-mutations.log" ]] || \
    fail 'Unowned OpenVPN-pool route was removed'
printf 'PASS: host cleanup removes only the exact protocol-186 return route\n'
PATH="$TMP_DIR/route-bin:$PATH" \
    ROUTE_MUTATION_LOG="$TMP_DIR/no-pool-route-mutations.log" \
    bash -c 'source "$1"; remove_managed_remote_access_return_routes "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-no-pool.json"
[[ ! -e "$TMP_DIR/no-pool-route-mutations.log" ]] || \
    fail 'OpenVPN without a client pool inspected or deleted a managed return route'
printf 'PASS: host cleanup does not inspect or delete OpenVPN routes without client_pool\n'
jq '.gateway.remote_access.ssh_tun = {
        "enabled":false,
        "address_pool":"198.18.0.0/24"
    }' "$TMP_DIR/valid.json" > "$TMP_DIR/ssh-tun-disabled-route.json"
PATH="$TMP_DIR/route-bin:$PATH" \
    OPENVPN_ROUTE_STATE='[]' \
    SSH_TUN_ROUTE_STATE='[{"dst":"198.18.0.0/24","gateway":"10.89.1.2","protocol":"186","table":"main"}]' \
    ROUTE_MUTATION_LOG="$TMP_DIR/ssh-route-mutations.log" \
    bash -c 'source "$1"; remove_managed_remote_access_return_routes "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/ssh-tun-disabled-route.json"
grep -Fxq -- \
    '-4 route del 198.18.0.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/ssh-route-mutations.log" || fail 'Owned SSH TUN return route was not cleaned'
printf 'PASS: host cleanup removes only disabled SSH TUN pool routes\n'

mkdir -p "$TMP_DIR/network-bin"
cat > "$TMP_DIR/network-bin/podman" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-} ${2:-}" in
    'network exists') exit 1 ;;
    'network create') printf '%s\n' "${5:-}" >> "$NETWORK_CREATE_LOG" ;;
    *) exit 97 ;;
esac
SH
chmod 0755 "$TMP_DIR/network-bin/podman"
PATH="$TMP_DIR/network-bin:$PATH" NETWORK_CREATE_LOG="$TMP_DIR/network-create.log" \
    bash -c 'source "$1"; create_declared_networks "$2"' _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json"
mapfile -t created_networks < "$TMP_DIR/network-create.log"
expected_created_networks=(shared project-a-net newly-added-net)
[[ "${created_networks[*]}" == "${expected_created_networks[*]}" ]] || \
    fail "Created Podman networks differ from declarations: ${created_networks[*]}"
printf 'PASS: all declared Podman networks are created\n'

mkdir -p "$TMP_DIR/dns-bin"
cat > "$TMP_DIR/dns-bin/podman" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PODMAN_CALL_LOG"
exit 97
SH
chmod 0755 "$TMP_DIR/dns-bin/podman"
PATH="$TMP_DIR/dns-bin:$PATH" PODMAN_CALL_LOG="$TMP_DIR/dns-podman.log" \
    bash -c 'source "$1"; generate_dns_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json" "$TMP_DIR/dns-hosts"
grep -Fq \
    '# PENDING DNS target: backend.project-a.dev.anatel (project-a-backend readiness/unverified)' \
    "$TMP_DIR/dns-hosts" || fail 'DNS candidate did not retain unverified target status'
[[ ! -s "$TMP_DIR/dns-podman.log" ]] || \
    fail 'DNS candidate generation queried a target container'
printf 'PASS: DNS candidate generation does not inspect application containers\n'

jq 'del(.gateway, .http_proxy) | .networks = [{"name":"database","subnet":"10.90.0.0/24"}] |
    .containers = [{"name":"postgres","networks":["database"]}] | .dns_records = []' \
    "$SAMPLE_CONFIG" > "$TMP_DIR/generic-host.json"
"$PREFLIGHT_SCRIPT" --validate-config "$TMP_DIR/generic-host.json" >/dev/null
printf 'PASS: generic host configuration accepted without gateway section\n'

mkdir -p "$TMP_DIR/generic-bin"
cat > "$TMP_DIR/generic-bin/podman" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:-}" in
    version) printf '3.0.0\n' ;;
    network)
        case "${2:-}" in
            ls) printf 'database\n' ;;
            inspect) printf '[{"subnets":[{"subnet":"10.90.0.0/24"}]}]\n' ;;
            *) exit 97 ;;
        esac
        ;;
    container) [[ "${2:-}" == exists && "${3:-}" == postgres ]] ;;
    inspect)
        printf '[{"State":{"Running":true},"NetworkSettings":{"Networks":{"database":{"IPAddress":"10.90.0.5"}}}}]\n'
        ;;
    *) exit 97 ;;
esac
SH
chmod 0755 "$TMP_DIR/generic-bin/podman"
cat > "$TMP_DIR/generic-bin/ip" <<'SH'
#!/usr/bin/env bash
printf '[]\n'
SH
chmod 0755 "$TMP_DIR/generic-bin/ip"
PATH="$TMP_DIR/generic-bin:$PATH" "$PREFLIGHT_SCRIPT" --check "$TMP_DIR/generic-host.json" >/dev/null
printf 'PASS: generic host preflight checks containers without gateway requirements\n'

jq '.schema_version = 2' "$TMP_DIR/valid.json" > "$TMP_DIR/unsupported-version.json"
expect_invalid 'unsupported schema version' "$TMP_DIR/unsupported-version.json"

jq '.gateway.remote_access.openvpn.routes = ["192.168.9.0/24"]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/unapproved-openvpn-routes.json"
expect_invalid 'unapproved OpenVPN route metadata' "$TMP_DIR/unapproved-openvpn-routes.json"

jq '.gateway.remote_access.ssh_tun.enabled = true' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/incomplete-ssh-tun.json"
expect_invalid 'SSH TUN without explicit account and pool' "$TMP_DIR/incomplete-ssh-tun.json"

jq '.gateway.networks = ["project-a-net"]' "$TMP_DIR/valid.json" > "$TMP_DIR/legacy-gateway-networks.json"
expect_invalid 'gateway.networks field' "$TMP_DIR/legacy-gateway-networks.json"
if python3 "$REPO_ROOT/gateway/development/host_config_validation.py" \
    "$TMP_DIR/legacy-gateway-networks.json" >/dev/null 2>&1; then
    fail 'startup host-config validator accepted gateway.networks'
fi
printf 'PASS: startup host-config validator rejects gateway.networks\n'

jq '.networks += [{"name":"project-a-net","subnet":"10.89.2.0/24"}]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-network.json"
expect_invalid 'duplicate network name' "$TMP_DIR/duplicate-network.json"

jq '.dns_records += [.dns_records[0]]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-dns.json"
expect_invalid 'duplicate DNS name' "$TMP_DIR/duplicate-dns.json"

jq '.networks += [{"name":"project-b-net","subnet":"10.89.1.128/25"}]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/overlapping-cidr.json"
expect_invalid 'overlapping CIDRs' "$TMP_DIR/overlapping-cidr.json"

jq '.networks[0].gateway_address = 123' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/non-string-gateway-address.json"
expect_invalid 'non-string Gateway address' "$TMP_DIR/non-string-gateway-address.json"

jq '.gateway.cockpit_bind_address = "::1"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/invalid-cockpit-bind.json"
expect_invalid 'non-IPv4 Cockpit bind address' "$TMP_DIR/invalid-cockpit-bind.json"

jq '.http_proxy.http_port = 70000' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/invalid-http-proxy-port.json"
expect_invalid 'invalid HTTP proxy port' "$TMP_DIR/invalid-http-proxy-port.json"

jq '.http_proxy.routes[0].api_prefix = "/api/"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/invalid-api-prefix.json"
expect_invalid 'API prefix outside application prefix' "$TMP_DIR/invalid-api-prefix.json"

jq '.containers |= map(select(.name != "nginx"))' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/missing-nginx-container.json"
expect_invalid 'HTTP proxy without NGINX container' "$TMP_DIR/missing-nginx-container.json"

jq '.application_gateway = .http_proxy | del(.http_proxy)' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/removed-application-gateway.json"
expect_invalid 'removed application_gateway section' "$TMP_DIR/removed-application-gateway.json"
if python3 "$REPO_ROOT/gateway/development/host_config_validation.py" \
    "$TMP_DIR/removed-application-gateway.json" >/dev/null 2>&1; then
    fail 'startup host-config validator accepted application_gateway'
fi
printf 'PASS: startup host-config validator rejects application_gateway\n'

jq '.networks[0].subnet = "10.89.1.7/24"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/noncanonical-cidr.json"
expect_invalid 'non-canonical CIDR' "$TMP_DIR/noncanonical-cidr.json"

jq '.dns_records[0].network = "undeclared-net"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/undeclared-network.json"
expect_invalid 'DNS record on undeclared network' "$TMP_DIR/undeclared-network.json"

jq '.dns_records[0].name = "Backend.project-a.dev.anatel"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/malformed-dns-name.json"
expect_invalid 'malformed DNS name' "$TMP_DIR/malformed-dns-name.json"

jq '.gateway.private_key_path = "/tmp/private-key"' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/private-key-path.json"
expect_invalid 'private-key path in configuration' "$TMP_DIR/private-key-path.json"

printf '{not json}\n' > "$TMP_DIR/malformed.json"
expect_invalid 'malformed JSON' "$TMP_DIR/malformed.json"
if "$DEPLOY_SCRIPT" --check "$TMP_DIR/malformed.json" >/dev/null 2>&1; then
    fail 'host preflight accepted malformed configuration'
fi
printf 'PASS: host preflight rejects malformed configuration\n'

sed '0,/"schema_version": 1/s//"schema_version": 2,\n    "schema_version": 1/' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-top-level.json"
sed '0,/"name": "gateway"/s//"name": "invalid",\n        "name": "gateway"/' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-nested.json"
for duplicate_config in "$TMP_DIR/duplicate-top-level.json" "$TMP_DIR/duplicate-nested.json"; do
    jq empty "$duplicate_config" >/dev/null || fail 'Duplicate-key regression fixture is not valid JSON.'
    expect_invalid 'duplicate JSON key' "$duplicate_config"
    if python3 "$REPO_ROOT/gateway/development/host_config_validation.py" \
        "$duplicate_config" >/dev/null 2>&1; then
        fail 'startup host-config validator accepted duplicate JSON keys'
    fi
done

mkdir -p "$TMP_DIR/source-check/scripts" "$TMP_DIR/source-check/gateway/development"
install -m 0755 "$PREFLIGHT_SCRIPT" "$TMP_DIR/source-check/scripts/host-preflight.sh"
if "$TMP_DIR/source-check/scripts/host-preflight.sh" --check-gateway "$TMP_DIR/valid.json" \
    > "$TMP_DIR/source-check.log" 2>&1; then
    fail 'host preflight accepted a missing Containerfile'
fi
grep -Fq 'Gateway deployment source asset is missing, unreadable, or unsafe:' "$TMP_DIR/source-check.log" || \
    fail 'missing Containerfile did not produce a source-asset error'
printf 'PASS: host preflight rejects missing deployment source assets\n'

mkdir "$TMP_DIR/fake-bin"
for command_name in podman systemctl install; do
    cat > "$TMP_DIR/fake-bin/$command_name" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "${0##*/}" >> "$HOST_COMMAND_LOG"
exit 97
SH
    chmod 0755 "$TMP_DIR/fake-bin/$command_name"
done
if PATH="$TMP_DIR/fake-bin:$PATH" HOST_COMMAND_LOG="$TMP_DIR/host-commands.log" \
    "$DEPLOY_SCRIPT" --apply "$TMP_DIR/malformed.json" >/dev/null 2>&1; then
    fail 'apply accepted malformed configuration'
fi
[[ ! -s "$TMP_DIR/host-commands.log" ]] || fail 'apply ran host commands before rejecting malformed configuration'
printf 'PASS: invalid apply stops before host commands\n'
for duplicate_config in "$TMP_DIR/duplicate-top-level.json" "$TMP_DIR/duplicate-nested.json"; do
    if PATH="$TMP_DIR/fake-bin:$PATH" HOST_COMMAND_LOG="$TMP_DIR/host-commands.log" \
        "$DEPLOY_SCRIPT" --apply "$duplicate_config" >/dev/null 2>&1; then
        fail 'apply accepted duplicate JSON keys'
    fi
    [[ ! -s "$TMP_DIR/host-commands.log" ]] || fail 'apply ran host commands before rejecting duplicate keys'
done
printf 'PASS: duplicate-key apply failures stop before host commands\n'

before=$(sha256sum "$SAMPLE_CONFIG")
"$DEPLOY_SCRIPT" --validate-config "$SAMPLE_CONFIG" >/dev/null
after=$(sha256sum "$SAMPLE_CONFIG")
[[ "$before" == "$after" ]] || fail 'validation changed the source configuration'
printf 'PASS: validation leaves source configuration unchanged\n'