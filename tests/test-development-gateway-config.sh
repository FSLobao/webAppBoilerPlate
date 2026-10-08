#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly DEPLOY_SCRIPT="$REPO_ROOT/scripts/deploy-development-gateway.sh"
readonly SAMPLE_CONFIG="$REPO_ROOT/config/development-gateway.json"
readonly TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

expect_invalid() {
    local label=$1
    local config_path=$2

    if "$DEPLOY_SCRIPT" --validate-config "$config_path" >/dev/null 2>&1; then
        fail "$label was accepted"
    fi
    printf 'PASS: %s rejected\n' "$label"
}

jq '.networks = [{"name":"project-a-net","subnet":"10.89.1.0/24"}] |
    .dns_records = [{"name":"backend.project-a.dev.internal","container":"project-a-backend","network":"project-a-net"}]' \
    "$SAMPLE_CONFIG" > "$TMP_DIR/valid.json"
"$DEPLOY_SCRIPT" --validate-config "$TMP_DIR/valid.json" >/dev/null
printf 'PASS: valid configuration accepted\n'

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

before=$(sha256sum "$SAMPLE_CONFIG")
"$DEPLOY_SCRIPT" --validate-config "$SAMPLE_CONFIG" >/dev/null
after=$(sha256sum "$SAMPLE_CONFIG")
[[ "$before" == "$after" ]] || fail 'validation changed the source configuration'
printf 'PASS: validation leaves source configuration unchanged\n'