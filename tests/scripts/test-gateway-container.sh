#!/usr/bin/env bash
set -Eeuo pipefail

readonly IMAGE=localhost/gateway:1
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly TMP_DIR="$(mktemp -d)"
readonly TEST_NAME="gateway-test-$$"
CONTAINER_CREATED=0
TEST_CONTAINER_ID=''

# Report a test failure and log only this test's created container.
# Arguments: failure message. Reads CONTAINER_CREATED and TEST_CONTAINER_ID.
# Output: failure message and owned-container logs to stderr; exits nonzero.
fail() {
    printf 'FAIL: %s\n' "$*" >&2
    if (( CONTAINER_CREATED )) && command -v podman >/dev/null 2>&1 && \
        podman container exists "$TEST_CONTAINER_ID" >/dev/null 2>&1; then
        podman logs "$TEST_CONTAINER_ID" >&2 || true
    fi
    exit 1
}
# ---------------------------------- #

# Remove only the container created by this test and its private temporary files.
# Arguments: none. Reads CONTAINER_CREATED and TEST_CONTAINER_ID; removes only owned resources.
# Output: none. Preserves the triggering exit status.
cleanup() {
    local status=$?
    trap - EXIT
    if (( CONTAINER_CREATED )) && command -v podman >/dev/null 2>&1 && \
        podman container exists "$TEST_CONTAINER_ID" >/dev/null 2>&1; then
        podman stop --time 10 "$TEST_CONTAINER_ID" >/dev/null 2>&1 || \
            podman rm --force "$TEST_CONTAINER_ID" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TMP_DIR"
    exit "$status"
}
# ---------------------------------- #
trap cleanup EXIT

for tool in podman jq ssh-keygen openssl; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required test tool is missing: $tool"
done
podman image exists "$IMAGE" || fail "Build the gateway image first: $IMAGE"
if podman container exists "$TEST_NAME" >/dev/null 2>&1; then
    fail "Test container name is already in use: $TEST_NAME"
fi

if podman run --rm --network none "$IMAGE" > "$TMP_DIR/missing-mounts.log" 2>&1; then
    fail 'Container startup accepted missing runtime mounts'
fi
grep -Fq 'Required read-only file is missing or unsafe: /etc/gateway/generated/config.json' \
    "$TMP_DIR/missing-mounts.log" || fail 'Missing-mount failure was not actionable'
printf 'PASS: missing runtime mounts rejected\n'

if podman run --rm --network none --entrypoint /bin/sh "$IMAGE" -c \
    'test -z "$(find /etc/ssh -maxdepth 1 -type f -name "ssh_host_*" -print -quit)"'; then
    printf 'PASS: image contains no generated SSH host keys\n'
else
    fail 'Image contains generated SSH host keys'
fi
if podman run --rm --network none --entrypoint /bin/sh "$IMAGE" -c \
    'command -v openvpn >/dev/null && command -v nft >/dev/null &&
        test -x /usr/local/lib/gateway/openvpn_runtime.py &&
        test -f /usr/local/lib/gateway/remote_forwarding.py &&
        test -L /usr/local/bin/gateway-openvpn-up &&
        test -x /usr/local/lib/gateway/ssh_tun_runtime.py &&
        getent passwd gateway-tunnel | awk -F: '\''$3 != 0 && $7 == "/bin/sh" { found = 1 } END { exit !found }'\'' &&
        python3 /usr/local/lib/gateway/openvpn_runtime.py --help >/dev/null &&
        python3 /usr/local/lib/gateway/ssh_tun_runtime.py --help >/dev/null'; then
    printf 'PASS: image contains restricted SSH TUN and shared OpenVPN forwarding runtimes\n'
else
    fail 'Image is missing a restricted remote-access runtime or forwarding tool'
fi

install -d -m 0700 "$TMP_DIR/ssh" "$TMP_DIR/tls" "$TMP_DIR/run" "$TMP_DIR/config" "$TMP_DIR/dns" "$TMP_DIR/client"
ssh-keygen -q -t ed25519 -N '' -f "$TMP_DIR/ssh/developer"
cp -- "$TMP_DIR/ssh/developer.pub" "$TMP_DIR/ssh/authorized_keys"
cp -- "$TMP_DIR/ssh/developer" "$TMP_DIR/client/developer"
chmod 0600 "$TMP_DIR/client/developer"
ssh-keygen -q -t ed25519 -N '' -f "$TMP_DIR/ssh/ssh_host_ed25519_key"
openssl req -x509 -newkey ed25519 -keyout "$TMP_DIR/tls/gateway.key" \
    -out "$TMP_DIR/tls/gateway.cert" -nodes -days 1 -subj /CN=localhost >/dev/null 2>&1
chmod 0600 "$TMP_DIR/tls/gateway.key"
chmod 0644 "$TMP_DIR/tls/gateway.cert"
printf 'test-only-password\n' > "$TMP_DIR/run/cockpit-password"
chmod 0600 "$TMP_DIR/run/cockpit-password"
jq '.networks = [{"name":"project-a-net","subnet":"10.89.1.0/24"}] |
    .dns_records = [{"name":"backend.project-a.dev.internal","container":"project-a-backend","network":"project-a-net"}]' \
    "$REPO_ROOT/config/host_config.json" > "$TMP_DIR/config/config.json"
chmod 0644 "$TMP_DIR/config/config.json"
printf '# generated test record\n192.0.2.2 backend.project-a.dev.internal\n' > "$TMP_DIR/dns/hosts"
chmod 0644 "$TMP_DIR/dns/hosts"
printf 'nameserver 127.0.0.1\noptions attempts:1 timeout:1\n' > "$TMP_DIR/run/resolv.conf"
chmod 0644 "$TMP_DIR/run/resolv.conf"

if ! TEST_CONTAINER_ID=$(podman run --detach --rm --network none --cap-drop=NET_RAW --name "$TEST_NAME" \
    --volume "$TMP_DIR/config:/etc/gateway/generated:ro" \
    --volume "$TMP_DIR/ssh/authorized_keys:/run/gateway/authorized_keys:ro" \
    --volume "$TMP_DIR/run/cockpit-password:/run/secrets/cockpit-password:ro" \
    --volume "$TMP_DIR/ssh/ssh_host_ed25519_key:/run/ssh-host-keys/ssh_host_ed25519_key:ro" \
    --volume "$TMP_DIR/ssh/ssh_host_ed25519_key.pub:/run/ssh-host-keys/ssh_host_ed25519_key.pub:ro" \
    --volume "$TMP_DIR/tls/gateway.cert:/etc/cockpit/ws-certs.d/gateway.cert:ro" \
    --volume "$TMP_DIR/tls/gateway.key:/etc/cockpit/ws-certs.d/gateway.key:ro" \
    --volume "$TMP_DIR/client:/run/test-client:ro" \
    --volume "$TMP_DIR/dns:/run/gateway/dns:ro" \
    --volume "$TMP_DIR/run/resolv.conf:/etc/resolv.conf:ro" "$IMAGE"); then
    fail 'Could not start the isolated gateway container'
fi
CONTAINER_CREATED=1

wait_for_listener() {
    local port=$1 attempt listener
    for attempt in {1..30}; do
        if listener=$(podman exec "$TEST_CONTAINER_ID" ss -H -ltn "sport = :$port" 2>/dev/null) && [[ -n "$listener" ]]; then
            return 0
        fi
    done
    fail "Expected gateway service is not listening on TCP port $port"
}

local_dns_ip() {
    local expected=$1 attempt resolved
    for attempt in {1..30}; do
        if resolved=$(podman exec "$TEST_CONTAINER_ID" getent hosts backend.project-a.dev.internal 2>/dev/null | awk 'NR == 1 { print $1 }'); then
            [[ "$resolved" == "$expected" ]] && return 0
        fi
    done
    podman exec "$TEST_CONTAINER_ID" cat /etc/resolv.conf >&2 || true
    podman exec "$TEST_CONTAINER_ID" ss -lnut >&2 || true
    podman exec "$TEST_CONTAINER_ID" getent hosts backend.project-a.dev.internal >&2 || true
    fail "DNSMasq did not return expected address $expected"
}

wait_for_listener 22
wait_for_listener 9090
podman exec "$TEST_CONTAINER_ID" ssh -i /run/test-client/developer -o BatchMode=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    developer@127.0.0.1 true >/dev/null 2>&1 || fail 'Gateway rejected the configured developer public key'
podman exec "$TEST_CONTAINER_ID" openssl s_client -connect 127.0.0.1:9090 -servername localhost -brief \
    </dev/null >/dev/null 2>&1 || fail 'Cockpit TLS handshake failed'
local_dns_ip 192.0.2.2

temporary_hosts=$(mktemp "$TMP_DIR/dns/.hosts.XXXXXX")
printf '# updated test record\n192.0.2.3 backend.project-a.dev.internal\n' > "$temporary_hosts"
chmod 0644 "$temporary_hosts"
mv -f -- "$temporary_hosts" "$TMP_DIR/dns/hosts"
podman exec "$TEST_CONTAINER_ID" pkill -HUP dnsmasq || fail 'Could not signal DNSMasq to reload records'
local_dns_ip 192.0.2.3
podman stop --time 10 "$TEST_CONTAINER_ID" >/dev/null || fail 'Gateway container did not stop cleanly'
if podman container exists "$TEST_CONTAINER_ID" >/dev/null 2>&1; then
    fail 'Stopped test container was not removed'
fi
printf 'PASS: SSH, DNSMasq, and Cockpit stayed up; DNS refreshed after atomic replacement; SIGTERM shutdown succeeded\n'