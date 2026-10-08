#!/usr/bin/env bash
set -Eeuo pipefail

readonly IMAGE=localhost/development-gateway:1
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly TMP_DIR="$(mktemp -d)"
readonly TEST_NAME="development-gateway-test-$$"

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    if command -v podman >/dev/null 2>&1 && podman container exists "$TEST_NAME" >/dev/null 2>&1; then
        podman logs "$TEST_NAME" >&2 || true
    fi
    exit 1
}

cleanup() {
    local status=$?
    trap - EXIT
    if command -v podman >/dev/null 2>&1 && podman container exists "$TEST_NAME" >/dev/null 2>&1; then
        podman stop --time 10 "$TEST_NAME" >/dev/null 2>&1 || podman rm --force "$TEST_NAME" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TMP_DIR"
    exit "$status"
}
trap cleanup EXIT

for tool in podman jq ssh-keygen openssl; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required test tool is missing: $tool"
done
podman image exists "$IMAGE" || fail "Build the gateway image first: $IMAGE"

if podman run --rm --network none "$IMAGE" > "$TMP_DIR/missing-mounts.log" 2>&1; then
    fail 'Container startup accepted missing runtime mounts'
fi
grep -Fq 'Required read-only file is missing or unsafe: /etc/development-gateway/generated/config.json' \
    "$TMP_DIR/missing-mounts.log" || fail 'Missing-mount failure was not actionable'
printf 'PASS: missing runtime mounts rejected\n'

if podman run --rm --network none --entrypoint /bin/sh "$IMAGE" -c \
    'test -z "$(find /etc/ssh -maxdepth 1 -type f -name "ssh_host_*" -print -quit)"'; then
    printf 'PASS: image contains no generated SSH host keys\n'
else
    fail 'Image contains generated SSH host keys'
fi

install -d -m 0700 "$TMP_DIR/ssh" "$TMP_DIR/tls" "$TMP_DIR/run" "$TMP_DIR/config" "$TMP_DIR/dns" "$TMP_DIR/client"
ssh-keygen -q -t ed25519 -N '' -f "$TMP_DIR/ssh/developer"
cp -- "$TMP_DIR/ssh/developer.pub" "$TMP_DIR/ssh/authorized_keys"
cp -- "$TMP_DIR/ssh/developer" "$TMP_DIR/client/developer"
chmod 0600 "$TMP_DIR/client/developer"
ssh-keygen -q -t ed25519 -N '' -f "$TMP_DIR/ssh/ssh_host_ed25519_key"
openssl req -x509 -newkey ed25519 -keyout "$TMP_DIR/tls/development-gateway.key" \
    -out "$TMP_DIR/tls/development-gateway.cert" -nodes -days 1 -subj /CN=localhost >/dev/null 2>&1
chmod 0600 "$TMP_DIR/tls/development-gateway.key"
chmod 0644 "$TMP_DIR/tls/development-gateway.cert"
printf 'test-only-password\n' > "$TMP_DIR/run/cockpit-password"
chmod 0600 "$TMP_DIR/run/cockpit-password"
jq '.networks = [{"name":"project-a-net","subnet":"10.89.1.0/24"}] |
    .dns_records = [{"name":"backend.project-a.dev.internal","container":"project-a-backend","network":"project-a-net"}]' \
    "$REPO_ROOT/config/development-gateway.json" > "$TMP_DIR/config/config.json"
chmod 0644 "$TMP_DIR/config/config.json"
printf '# generated test record\n192.0.2.2 backend.project-a.dev.internal\n' > "$TMP_DIR/dns/hosts"
chmod 0644 "$TMP_DIR/dns/hosts"
printf 'nameserver 127.0.0.1\noptions attempts:1 timeout:1\n' > "$TMP_DIR/run/resolv.conf"
chmod 0644 "$TMP_DIR/run/resolv.conf"

podman run --detach --rm --network none --cap-drop=NET_RAW --name "$TEST_NAME" \
    --volume "$TMP_DIR/config:/etc/development-gateway/generated:ro" \
    --volume "$TMP_DIR/ssh/authorized_keys:/run/development-gateway/authorized_keys:ro" \
    --volume "$TMP_DIR/run/cockpit-password:/run/secrets/cockpit-password:ro" \
    --volume "$TMP_DIR/ssh/ssh_host_ed25519_key:/run/ssh-host-keys/ssh_host_ed25519_key:ro" \
    --volume "$TMP_DIR/ssh/ssh_host_ed25519_key.pub:/run/ssh-host-keys/ssh_host_ed25519_key.pub:ro" \
    --volume "$TMP_DIR/tls/development-gateway.cert:/etc/cockpit/ws-certs.d/development-gateway.cert:ro" \
    --volume "$TMP_DIR/tls/development-gateway.key:/etc/cockpit/ws-certs.d/development-gateway.key:ro" \
    --volume "$TMP_DIR/client:/run/test-client:ro" \
    --volume "$TMP_DIR/dns:/run/development-gateway/dns:ro" \
    --volume "$TMP_DIR/run/resolv.conf:/etc/resolv.conf:ro" "$IMAGE" >/dev/null || \
    fail 'Could not start the isolated gateway container'

wait_for_listener() {
    local port=$1 attempt listener
    for attempt in {1..30}; do
        if listener=$(podman exec "$TEST_NAME" ss -H -ltn "sport = :$port" 2>/dev/null) && [[ -n "$listener" ]]; then
            return 0
        fi
    done
    fail "Expected gateway service is not listening on TCP port $port"
}

local_dns_ip() {
    local expected=$1 attempt resolved
    for attempt in {1..30}; do
        if resolved=$(podman exec "$TEST_NAME" getent hosts backend.project-a.dev.internal 2>/dev/null | awk 'NR == 1 { print $1 }'); then
            [[ "$resolved" == "$expected" ]] && return 0
        fi
    done
    podman exec "$TEST_NAME" cat /etc/resolv.conf >&2 || true
    podman exec "$TEST_NAME" ss -lnut >&2 || true
    podman exec "$TEST_NAME" getent hosts backend.project-a.dev.internal >&2 || true
    fail "DNSMasq did not return expected address $expected"
}

wait_for_listener 22
wait_for_listener 9090
podman exec "$TEST_NAME" ssh -i /run/test-client/developer -o BatchMode=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    developer@127.0.0.1 true >/dev/null 2>&1 || fail 'Gateway rejected the configured developer public key'
podman exec "$TEST_NAME" openssl s_client -connect 127.0.0.1:9090 -servername localhost -brief \
    </dev/null >/dev/null 2>&1 || fail 'Cockpit TLS handshake failed'
local_dns_ip 192.0.2.2

temporary_hosts=$(mktemp "$TMP_DIR/dns/.hosts.XXXXXX")
printf '# updated test record\n192.0.2.3 backend.project-a.dev.internal\n' > "$temporary_hosts"
chmod 0644 "$temporary_hosts"
mv -f -- "$temporary_hosts" "$TMP_DIR/dns/hosts"
podman exec "$TEST_NAME" pkill -HUP dnsmasq || fail 'Could not signal DNSMasq to reload records'
local_dns_ip 192.0.2.3
podman stop --time 10 "$TEST_NAME" >/dev/null || fail 'Gateway container did not stop cleanly'
if podman container exists "$TEST_NAME" >/dev/null 2>&1; then
    fail 'Stopped test container was not removed'
fi
printf 'PASS: SSH, DNSMasq, and Cockpit stayed up; DNS refreshed after atomic replacement; SIGTERM shutdown succeeded\n'