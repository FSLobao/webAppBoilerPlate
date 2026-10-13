#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
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

jq '.networks = [{"name":"project-a-net","subnet":"10.89.1.0/24"}] |
    .gateway.networks = ["project-a-net"] |
    .dns_records = [{"name":"backend.project-a.dev.internal","container":"project-a-backend","network":"project-a-net"}]' \
    "$SAMPLE_CONFIG" > "$TMP_DIR/valid.json"
"$DEPLOY_SCRIPT" --validate-config "$TMP_DIR/valid.json" >/dev/null
"$PREFLIGHT_SCRIPT" --validate-config "$TMP_DIR/valid.json" >/dev/null
printf 'PASS: valid configuration accepted\n'

jq 'del(.gateway) | .networks = [{"name":"database","subnet":"10.90.0.0/24"}] |
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

jq '.networks += [{"name":"project-a-net","subnet":"10.89.2.0/24"}]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-network.json"
expect_invalid 'duplicate network name' "$TMP_DIR/duplicate-network.json"

jq '.dns_records += [.dns_records[0]]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/duplicate-dns.json"
expect_invalid 'duplicate DNS name' "$TMP_DIR/duplicate-dns.json"

jq '.networks += [{"name":"project-b-net","subnet":"10.89.1.128/25"}]' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/overlapping-cidr.json"
expect_invalid 'overlapping CIDRs' "$TMP_DIR/overlapping-cidr.json"

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

before=$(sha256sum "$SAMPLE_CONFIG")
"$DEPLOY_SCRIPT" --validate-config "$SAMPLE_CONFIG" >/dev/null
after=$(sha256sum "$SAMPLE_CONFIG")
[[ "$before" == "$after" ]] || fail 'validation changed the source configuration'
printf 'PASS: validation leaves source configuration unchanged\n'