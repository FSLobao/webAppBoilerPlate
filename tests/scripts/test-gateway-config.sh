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
    .dns_records = [{"name":"backend.project-a.dev.internal","container":"project-a-backend","network":"project-a-net"}]' \
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
PATH="$TMP_DIR/generic-bin:$PATH" "$PREFLIGHT_SCRIPT" --check "$TMP_DIR/generic-host.json" >/dev/null
printf 'PASS: generic host preflight checks containers without gateway requirements\n'

jq '.schema_version = 2' "$TMP_DIR/valid.json" > "$TMP_DIR/unsupported-version.json"
expect_invalid 'unsupported schema version' "$TMP_DIR/unsupported-version.json"

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

jq '.dns_records[0].name = "Backend.project-a.dev.internal"' \
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