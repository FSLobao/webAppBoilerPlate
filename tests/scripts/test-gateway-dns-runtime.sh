#!/usr/bin/env bash
set -Eeuo pipefail

readonly IMAGE=localhost/gateway:1
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
readonly TMP_DIR="$(mktemp -d)"
readonly TEST_SUFFIX="$$"
readonly GATEWAY_NAME="gateway-dns-runtime-${TEST_SUFFIX}"
readonly NETWORK_NAME="gateway-dns-runtime-${TEST_SUFFIX}"
readonly TARGET_NAME="gateway-dns-target-${TEST_SUFFIX}"
readonly BLOCKER_NAME="gateway-dns-blocker-${TEST_SUFFIX}"
readonly REPLACEMENT_NAME="$TARGET_NAME"
readonly DNS_NAME=target.project-a.dev.internal
readonly PODMAN_SOCKET="$TMP_DIR/podman/podman.sock"
readonly PODMAN_SERVICE_LOG="$TMP_DIR/podman-service.log"
PODMAN_SERVICE_PID=''
NETWORK_CREATED=0
TARGET_ID=''
BLOCKER_ID=''
REPLACEMENT_ID=''
GATEWAY_ID=''

# Report a failure and show logs from this test's Gateway only.
# Arguments: failure message. Reads GATEWAY_ID.
# Output: error and owned Gateway logs to stderr; exits nonzero.
fail() {
  printf 'FAIL: %s\n' "$*" >&2
  if [[ -n "$GATEWAY_ID" ]] && podman container exists "$GATEWAY_ID" >/dev/null 2>&1; then
    podman logs "$GATEWAY_ID" >&2 || true
  fi
  exit 1
}
# ---------------------------------- #

# Remove only this test's containers, network, socket service, and temporary files.
# Arguments: none. Reads exact resource names and IDs created by this test.
# Output: none. Preserves the triggering exit status.
cleanup() {
  local status=$? target
  trap - EXIT
  if [[ -n "$GATEWAY_ID" ]] && podman container exists "$GATEWAY_ID" >/dev/null 2>&1; then
    podman stop --time 5 "$GATEWAY_ID" >/dev/null 2>&1 || \
      podman rm --force "$GATEWAY_ID" >/dev/null 2>&1 || true
  fi
  for target in "$TARGET_ID" "$BLOCKER_ID" "$REPLACEMENT_ID"; do
    if [[ -n "$target" ]] && podman container exists "$target" >/dev/null 2>&1; then
      podman stop --time 0 "$target" >/dev/null 2>&1 || \
        podman rm --force "$target" >/dev/null 2>&1 || true
    fi
  done
  if (( NETWORK_CREATED )) && podman network exists "$NETWORK_NAME" >/dev/null 2>&1; then
    podman network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$PODMAN_SERVICE_PID" ]]; then
    kill "$PODMAN_SERVICE_PID" 2>/dev/null || true
    wait "$PODMAN_SERVICE_PID" 2>/dev/null || true
  fi
  rm -rf -- "$TMP_DIR"
  exit "$status"
}
# ---------------------------------- #
trap cleanup EXIT

# Wait for one exact target container to become healthy.
# Arguments: target name. Reads Podman state through the local engine.
# Output: none. Fails after a bounded wait.
wait_for_healthy_target() {
  local target=$1 attempt health
  for attempt in {1..30}; do
    health=$(podman inspect --format '{{.State.Health.Status}}' "$target" 2>/dev/null) || \
      fail "Could not inspect this test target: $target"
    [[ "$health" == healthy ]] && return 0
    sleep 1
  done
  fail "Test target did not become healthy: $target"
}
# ---------------------------------- #

# Wait until the test Gateway answers a DNS query with one expected address.
# Arguments: expected IPv4 address. Reads GATEWAY_ID and DNS_NAME.
# Output: none. Fails after a bounded wait.
wait_for_dns_address() {
  local expected=$1 attempt resolved
  for attempt in {1..30}; do
    resolved=$(podman exec "$GATEWAY_ID" getent hosts "$DNS_NAME" 2>/dev/null | \
      awk 'NR == 1 { print $1 }') || true
    [[ "$resolved" == "$expected" ]] && return 0
    sleep 1
  done
  fail "DNSMasq did not return expected address $expected for $DNS_NAME"
}
# ---------------------------------- #

# Wait until the test Gateway no longer resolves a scoped DNS name.
# Arguments: none. Reads GATEWAY_ID and DNS_NAME.
# Output: none. Fails after a bounded wait.
wait_for_dns_missing() {
  local attempt
  for attempt in {1..30}; do
    if ! podman exec "$GATEWAY_ID" getent hosts "$DNS_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "DNSMasq retained stale address for $DNS_NAME"
}
# ---------------------------------- #

# Create a revision-bound request for one app target event.
# Arguments: ready target full ID or empty for a pending/stop event.
# Output: protected request file at TMP_DIR/request.json.
write_handoff_request() {
  local target_id=$1 revision
  revision=$(python3 "$REPO_ROOT/gateway/development/dns_refresh.py" \
    revision "$TMP_DIR/config/config.json") || fail 'Could not calculate effective config revision.'
  if [[ -n "$target_id" ]]; then
    jq -n --arg revision "$revision" --arg target "$TARGET_NAME" --arg id "$target_id" \
      '{config_revision:$revision,target_scope:[$target],ready_targets:[{container:$target,id:$id}]}' \
      > "$TMP_DIR/request.json"
  else
    jq -n --arg revision "$revision" --arg target "$TARGET_NAME" \
      '{config_revision:$revision,target_scope:[$target],ready_targets:[]}' \
      > "$TMP_DIR/request.json"
  fi
  chmod 0600 "$TMP_DIR/request.json"
}
# ---------------------------------- #

# Render and atomically publish a candidate through the Gateway handoff module.
# Arguments: none. Reads the current DNS file and request; mutates only test-owned files.
# Output: none. Reloads only this test's DNSMasq process.
refresh_test_dns() {
  local candidate staged
  candidate=$(podman exec --interactive "$GATEWAY_ID" \
    python3 /usr/local/lib/gateway/dns_refresh.py handoff \
    --config /etc/gateway/generated/config.json \
    --hosts /run/gateway/dns/hosts < "$TMP_DIR/request.json") || \
    fail 'Gateway rejected the test readiness handoff.'
  staged=$(mktemp "$TMP_DIR/dns/.hosts.XXXXXX")
  chmod 0644 "$staged"
  printf '%s\n' "$candidate" > "$staged"
  podman exec "$GATEWAY_ID" dnsmasq --test --no-resolv --no-hosts \
    --bind-dynamic --addn-hosts="/run/gateway/dns/$(basename -- "$staged")" >/dev/null || \
    fail 'DNSMasq rejected the staged test hosts file.'
  mv -f -- "$staged" "$TMP_DIR/dns/hosts"
  podman exec "$GATEWAY_ID" pkill -HUP dnsmasq || fail 'Could not reload test DNSMasq.'
}
# ---------------------------------- #

for tool in podman jq python3 ssh-keygen openssl; do
  command -v "$tool" >/dev/null 2>&1 || fail "Required test tool is missing: $tool"
done
podman image exists "$IMAGE" || fail "Build the Gateway image first: $IMAGE"
[[ ! -e "$PODMAN_SOCKET" ]] || fail 'Test Podman socket path already exists.'

mkdir -p "$TMP_DIR/podman"
podman system service --time=0 "unix://$PODMAN_SOCKET" > "$PODMAN_SERVICE_LOG" 2>&1 &
PODMAN_SERVICE_PID=$!
for attempt in {1..30}; do
  [[ -S "$PODMAN_SOCKET" ]] && break
  sleep 1
done
[[ -S "$PODMAN_SOCKET" ]] || fail 'Temporary rootful Podman API socket did not become ready.'

podman network create "$NETWORK_NAME" >/dev/null || fail 'Could not create isolated test network.'
NETWORK_CREATED=1
TARGET_SUBNET=$(podman network inspect "$NETWORK_NAME" | jq -er '.[0].subnets[0].subnet') || \
  fail 'Could not inspect isolated test network subnet.'
podman run --detach --rm --name "$TARGET_NAME" --network "$NETWORK_NAME" \
  --health-cmd /bin/true --health-interval 1s --health-retries 1 \
  --entrypoint /bin/sleep "$IMAGE" 3600 >/dev/null || \
  fail 'Could not start healthy test target.'
wait_for_healthy_target "$TARGET_NAME"
TARGET_ID=$(podman inspect --format '{{.Id}}' "$TARGET_NAME") || \
  fail 'Could not capture the exact test target ID.'
TARGET_ADDRESS=$(podman inspect --format '{{json .NetworkSettings.Networks}}' "$TARGET_ID" | \
  jq -er --arg network "$NETWORK_NAME" '.[$network].IPAddress') || \
  fail 'Could not capture the test target network address.'

install -d -m 0700 "$TMP_DIR/ssh" "$TMP_DIR/tls" "$TMP_DIR/run" \
  "$TMP_DIR/config" "$TMP_DIR/dns" "$TMP_DIR/client"
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
jq --arg network "$NETWORK_NAME" --arg subnet "$TARGET_SUBNET" --arg target "$TARGET_NAME" \
  '.networks = [{"name":$network,"subnet":$subnet}] |
   .dns_records = [{"name":"target.project-a.dev.internal","container":$target,"network":$network}]' \
  "$REPO_ROOT/config/host_config.json" > "$TMP_DIR/config/config.json"
chmod 0644 "$TMP_DIR/config/config.json"
printf '# generated test record\n' > "$TMP_DIR/dns/hosts"
chmod 0644 "$TMP_DIR/dns/hosts"
printf 'nameserver 127.0.0.1\noptions attempts:1 timeout:1\n' > "$TMP_DIR/run/resolv.conf"
chmod 0644 "$TMP_DIR/run/resolv.conf"

GATEWAY_ID=$(podman run --detach --rm --network none --cap-drop=NET_RAW \
  --name "$GATEWAY_NAME" --env CONTAINER_HOST=unix:///run/podman/podman.sock \
  --volume "$TMP_DIR/config:/etc/gateway/generated:ro" \
  --volume "$TMP_DIR/ssh/authorized_keys:/run/gateway/authorized_keys:ro" \
  --volume "$TMP_DIR/run/cockpit-password:/run/secrets/cockpit-password:ro" \
  --volume "$TMP_DIR/ssh/ssh_host_ed25519_key:/run/ssh-host-keys/ssh_host_ed25519_key:ro" \
  --volume "$TMP_DIR/ssh/ssh_host_ed25519_key.pub:/run/ssh-host-keys/ssh_host_ed25519_key.pub:ro" \
  --volume "$TMP_DIR/tls/gateway.cert:/etc/cockpit/ws-certs.d/gateway.cert:ro" \
  --volume "$TMP_DIR/tls/gateway.key:/etc/cockpit/ws-certs.d/gateway.key:ro" \
  --volume "$TMP_DIR/client:/run/test-client:ro" \
  --volume "$TMP_DIR/dns:/run/gateway/dns:ro" \
  --volume "$TMP_DIR/run/resolv.conf:/etc/resolv.conf:ro" \
  --volume "$PODMAN_SOCKET:/run/podman/podman.sock:ro" "$IMAGE") || \
  fail 'Could not start isolated Gateway container with temporary Podman API socket.'

write_handoff_request "$TARGET_ID"
refresh_test_dns
wait_for_dns_address "$TARGET_ADDRESS"
printf 'PASS: Gateway re-inspected exact healthy target and DNSMasq published its live address\n'

OLD_TARGET_ADDRESS=$TARGET_ADDRESS
podman stop --time 0 "$TARGET_NAME" >/dev/null || fail 'Could not stop original test target.'
podman run --detach --rm --name "$BLOCKER_NAME" --network "$NETWORK_NAME" \
  --ip "$OLD_TARGET_ADDRESS" --entrypoint /bin/sleep "$IMAGE" 3600 >/dev/null || \
  fail 'Could not reserve the old test target address.'
BLOCKER_ID=$(podman inspect --format '{{.Id}}' "$BLOCKER_NAME") || \
  fail 'Could not capture old-address blocker ID.'
podman run --detach --rm --name "$REPLACEMENT_NAME" --network "$NETWORK_NAME" \
  --health-cmd /bin/true --health-interval 1s --health-retries 1 \
  --entrypoint /bin/sleep "$IMAGE" 3600 >/dev/null || \
  fail 'Could not start replacement test target.'
wait_for_healthy_target "$REPLACEMENT_NAME"
REPLACEMENT_ID=$(podman inspect --format '{{.Id}}' "$REPLACEMENT_NAME") || \
  fail 'Could not capture replacement target ID.'
REPLACEMENT_ADDRESS=$(podman inspect --format '{{json .NetworkSettings.Networks}}' "$REPLACEMENT_ID" | \
  jq -er --arg network "$NETWORK_NAME" '.[$network].IPAddress') || \
  fail 'Could not capture replacement target address.'
[[ "$REPLACEMENT_ID" != "$TARGET_ID" && "$REPLACEMENT_ADDRESS" != "$OLD_TARGET_ADDRESS" ]] || \
  fail 'Replacement target did not receive a new identity and address.'
write_handoff_request "$REPLACEMENT_ID"
refresh_test_dns
wait_for_dns_address "$REPLACEMENT_ADDRESS"
if podman exec "$GATEWAY_ID" getent hosts "$DNS_NAME" | grep -Fq "$OLD_TARGET_ADDRESS"; then
  fail 'DNSMasq retained the replaced target address.'
fi
printf 'PASS: replacement identity published its new address and removed the old address\n'

podman stop --time 0 "$REPLACEMENT_NAME" >/dev/null || fail 'Could not stop replacement target.'
write_handoff_request ''
refresh_test_dns
wait_for_dns_missing
printf 'PASS: stopped target handoff removed its DNS record after actual DNSMasq reload\n'

podman stop --time 10 "$GATEWAY_ID" >/dev/null || fail 'Test Gateway did not stop cleanly.'
if podman container exists "$GATEWAY_ID" >/dev/null 2>&1; then
  fail 'Stopped test Gateway was not removed.'
fi
GATEWAY_ID=''
printf 'PASS: isolated DNS runtime resources completed and Gateway stopped cleanly\n'
