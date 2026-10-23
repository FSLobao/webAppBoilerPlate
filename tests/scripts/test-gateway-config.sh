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
jq '.gateway.startup_readiness.interval_seconds = 61' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/invalid-readiness.json"
expect_invalid 'startup readiness interval greater than timeout' \
    "$TMP_DIR/invalid-readiness.json"

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
if grep -q '^DNS=' "$TMP_DIR/rendered.container"; then
    fail 'Gateway Quadlet must inherit Podman DNS instead of overriding it'
fi
printf 'PASS: all declared Podman networks are rendered; HTTP proxy routes are not networks\n'
if grep -Fxq 'PodmanArgs=--rm=false' "$TMP_DIR/rendered.container"; then
    fail 'Normal Gateway Quadlet unexpectedly disables Podman container removal'
fi
bash -c '
    source "$1"
    render_quadlet_candidate "$2" "$3" true
    render_gateway_debug_dropin "$3" "$4"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json" "$TMP_DIR/debug.container" \
    "$TMP_DIR/debug-preserve.conf"
grep -Fxq 'PodmanArgs=--rm=false' "$TMP_DIR/debug.container" || \
    fail 'Debug Quadlet did not retain the failed Podman container'
grep -Fxq '# Managed by scripts/deploy-gateway.sh; debug-preserve v1' \
    "$TMP_DIR/debug-preserve.conf" || fail 'Debug override lacks its ownership marker'
grep -Fxq 'Restart=no' "$TMP_DIR/debug-preserve.conf" || \
    fail 'Debug override did not disable automatic service restart'
grep -Fxq 'ExecStop=' "$TMP_DIR/debug-preserve.conf" || \
    fail 'Debug override did not clear generated container cleanup'
grep -Fxq 'ExecStopPost=' "$TMP_DIR/debug-preserve.conf" || \
    fail 'Debug override did not clear generated post-stop cleanup'
grep -Fq 'ExecStopPost=-/bin/sh -c' "$TMP_DIR/debug-preserve.conf" || \
    fail 'Debug override did not retain owned route cleanup hooks'
grep -Fq 'RTNETLINK answers: No such process' "$TMP_DIR/debug-preserve.conf" || \
    fail 'Debug override did not suppress expected missing-route cleanup'
if [[ -x /usr/lib/systemd/system-generators/podman-system-generator ]] || \
    [[ -x /usr/libexec/podman/quadlet ]]; then
    bash -c 'source "$1"; validate_quadlet_candidate "$2"' \
        _ "$DEPLOY_SCRIPT" "$TMP_DIR/debug.container"
    printf 'PASS: host Quadlet generator accepts the debug-preserve candidate\n'
fi
printf 'PASS: debug Quadlet retains failed containers and preserves owned route cleanup\n'
printf 'managed debug state\n' > "$TMP_DIR/retained-debug-preserve.conf"
RETAINED_DEBUG_PATH="$TMP_DIR/retained-debug-preserve.conf" \
    bash -c '
        source "$1"
        gateway_debug_dropin_is_managed() { [[ -f "$1" ]]; }
        ensure_no_stale_gateway_debug_state "$RETAINED_DEBUG_PATH"
    ' _ "$DEPLOY_SCRIPT" > "$TMP_DIR/retained-debug-output.log"
grep -Fq 'Reusing retained debug state' "$TMP_DIR/retained-debug-output.log" || \
    fail 'Retry rejected an existing deployment-owned debug override'
if bash -c '
    source "$1"
    gateway_debug_dropin_is_managed() { return 1; }
    ensure_no_stale_gateway_debug_state "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/retained-debug-preserve.conf" \
    > "$TMP_DIR/unowned-debug-output.log" 2>&1; then
    fail 'Retry accepted an unowned debug override'
fi
grep -Fq 'is not owned by deployment' "$TMP_DIR/unowned-debug-output.log" || \
    fail 'Retry did not explain why an unowned debug override was rejected'
printf 'PASS: retries reuse only deployment-owned debug overrides\n'
DEBUG_NORMALIZE_LOG="$TMP_DIR/debug-normalize.log" bash -c '
    source "$1"
    STAGED_QUADLET=normal-candidate
    STAGED_DEBUG_QUADLET=debug-candidate
    cmp() { printf "cmp %s\n" "$*" >> "$DEBUG_NORMALIZE_LOG"; return 1; }
    install_atomic_if_changed() {
        printf "install %s\n" "$*" >> "$DEBUG_NORMALIZE_LOG"
    }
    remove_gateway_debug_dropin() {
        printf "remove override\n" >> "$DEBUG_NORMALIZE_LOG"
        DEBUG_DROPIN_INSTALLED=0
    }
    systemctl() { printf "systemctl %s\n" "$*" >> "$DEBUG_NORMALIZE_LOG"; }
    DEBUG_PRESERVE_ACTIVE=1
    PRESERVE_FAILED_STATE=1
    DEBUG_DROPIN_INSTALLED=1
    normalize_gateway_debug_unit
    [[ "$DEBUG_PRESERVE_ACTIVE" == 0 && "$PRESERVE_FAILED_STATE" == 0 ]]
' _ "$DEPLOY_SCRIPT"
grep -Fxq 'install normal-candidate /etc/containers/systemd/gateway.container 0644' \
    "$TMP_DIR/debug-normalize.log" || \
    fail 'Successful health checks did not restore the normal Quadlet'
grep -Fxq 'remove override' "$TMP_DIR/debug-normalize.log" || \
    fail 'Successful health checks did not remove the debug override'
grep -Fxq 'systemctl daemon-reload' "$TMP_DIR/debug-normalize.log" || \
    fail 'Successful health checks did not reload systemd after normalization'
printf 'PASS: successful health checks restore the normal Quadlet and remove debug state\n'
mkdir -p "$TMP_DIR/diagnostic-bin"
cat > "$TMP_DIR/diagnostic-bin/podman" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'podman %s\n' "$*" >> "$PODMAN_DIAGNOSTIC_LOG"
case "$*" in
    *'{{.State.Running}} gateway') printf 'false\n' ;;
    *'{{.State.Status}} exit_code='*) printf 'exited exit_code=1 error= image=test\n' ;;
esac
SH
cat > "$TMP_DIR/diagnostic-bin/journalctl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'journalctl %s\n' "$*" >> "$PODMAN_DIAGNOSTIC_LOG"
SH
chmod 0755 "$TMP_DIR/diagnostic-bin/podman" "$TMP_DIR/diagnostic-bin/journalctl"
PODMAN_DIAGNOSTIC_LOG="$TMP_DIR/podman-diagnostic.log" \
    PATH="$TMP_DIR/diagnostic-bin:$PATH" bash -c '
        source "$1"
        debug_gateway_failure
    ' _ "$DEPLOY_SCRIPT" > "$TMP_DIR/podman-diagnostic-output.log" 2>&1
grep -Fq 'podman ps -a --filter name=gateway' "$TMP_DIR/podman-diagnostic.log" || \
    fail 'Startup diagnostics did not list retained Podman containers'
grep -Fq 'podman inspect --format {{.State.Status}}' "$TMP_DIR/podman-diagnostic.log" || \
    fail 'Startup diagnostics did not inspect container exit state'
grep -Fxq 'podman logs --tail 100 gateway' "$TMP_DIR/podman-diagnostic.log" || \
    fail 'Startup diagnostics did not collect container logs'
grep -Fxq 'journalctl -u gateway.service -n 100 --no-pager' \
    "$TMP_DIR/podman-diagnostic.log" || \
    fail 'Startup diagnostics did not collect the systemd journal'
grep -Fq 'podman start gateway' "$TMP_DIR/podman-diagnostic-output.log" || \
    fail 'Startup diagnostics did not explain how to retry a stopped container'
printf 'PASS: startup diagnostics collect Podman state, logs, and systemd journal\n'

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
grep -Fq 'ExecStopPost=-/bin/sh -c' "$TMP_DIR/openvpn.container" || \
    fail 'OpenVPN host route cleanup wrapper was not rendered'
grep -Fq 'ip -4 route del 172.24.0.0/21 via 10.89.1.2 proto 186' \
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
grep -Fq 'ip -4 route del 198.18.0.0/24 via 10.89.1.2 proto 186' \
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
grep -Fxq \
    'ExecStartPre=/usr/sbin/modprobe --use-blacklist wireguard' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard module load was not added to the Gateway service'
grep -Fxq 'PublishPort=127.0.0.1:54000:54000/udp' "$TMP_DIR/wireguard.container" || \
    fail 'WireGuard UDP host publication was not rendered'
grep -Fxq \
    'ExecStartPost=/usr/sbin/ip -4 route add 198.18.1.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard host return route was not rendered'
grep -Fq 'ip -4 route del 198.18.1.0/24 via 10.89.1.2 proto 186' \
    "$TMP_DIR/wireguard.container" || fail 'WireGuard host return route cleanup was not rendered'
if [[ -x /usr/lib/systemd/system-generators/podman-system-generator ]] || \
    [[ -x /usr/libexec/podman/quadlet ]]; then
    bash -c 'source "$1"; validate_quadlet_candidate "$2"' \
        _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard.container"
    printf 'PASS: host Quadlet generator accepts WireGuard module loading at service start\n'
fi
printf 'PASS: WireGuard renders explicit UDP bind, read-only server key, persistent public peers, minimum capability, and owned return route\n'
jq '.gateway.remote_access.wireguard.enabled = false' "$TMP_DIR/valid.json" \
    > "$TMP_DIR/wireguard-disabled.json"
bash -c 'source "$1"; render_quadlet_candidate "$2" "$3"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-disabled.json" "$TMP_DIR/wireguard-disabled.container"
if grep -Fxq \
    'ExecStartPre=/usr/sbin/modprobe --use-blacklist wireguard' \
    "$TMP_DIR/wireguard-disabled.container"; then
    fail 'Disabled WireGuard still renders the module load command'
fi
printf 'PASS: disabled WireGuard does not request host module loading\n'
MODULE_CALL_LOG="$TMP_DIR/wireguard-module-call.log" bash -c '
    source "$1"
    run_python_module() {
        printf "%s\n" "$1" >> "$MODULE_CALL_LOG"
    }
    ensure_wireguard_kernel_module "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-enabled.json"
grep -Fxq 'scripts.gateway.wireguard_kernel' "$TMP_DIR/wireguard-module-call.log" || \
    fail 'Enabled WireGuard did not request kernel module loading during apply'
: > "$TMP_DIR/wireguard-module-call.log"
MODULE_CALL_LOG="$TMP_DIR/wireguard-module-call.log" bash -c '
    source "$1"
    run_python_module() {
        printf "%s\n" "$1" >> "$MODULE_CALL_LOG"
    }
    ensure_wireguard_kernel_module "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/wireguard-disabled.json"
[[ ! -s "$TMP_DIR/wireguard-module-call.log" ]] || \
    fail 'Disabled WireGuard requested kernel module loading during apply'
printf 'PASS: apply requests host module loading only when WireGuard is enabled\n'
mkdir -p "$TMP_DIR/system-bin"
cat > "$TMP_DIR/system-bin/systemctl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "$SYSTEMCTL_CALL_LOG"
SH
chmod 0755 "$TMP_DIR/system-bin/systemctl"
: > "$TMP_DIR/systemctl-call.log"
SYSTEMCTL_CALL_LOG="$TMP_DIR/systemctl-call.log" \
    PATH="$TMP_DIR/system-bin:$PATH" bash -c '
        source "$1"
        activate_gateway_service 0
        [[ "$ACTIVATION_ATTEMPTED" == 1 ]]
    ' _ "$DEPLOY_SCRIPT"
grep -Fxq 'start gateway.service' "$TMP_DIR/systemctl-call.log" || \
    fail 'First deployment did not start the generated Gateway unit directly'
: > "$TMP_DIR/systemctl-call.log"
SYSTEMCTL_CALL_LOG="$TMP_DIR/systemctl-call.log" \
    PATH="$TMP_DIR/system-bin:$PATH" bash -c '
        source "$1"
        activate_gateway_service 1
    ' _ "$DEPLOY_SCRIPT"
grep -Fxq 'restart gateway.service' "$TMP_DIR/systemctl-call.log" || \
    fail 'Existing active Gateway unit was not restarted directly'
if bash -c '
    source "$1"
    systemctl() { return 1; }
    debug_gateway_failure() { printf "activation diagnostics\n"; }
    activate_gateway_service 0
' _ "$DEPLOY_SCRIPT" > "$TMP_DIR/activation-failure-output.log" 2>&1; then
    fail 'Gateway activation failure was accepted'
fi
grep -Fxq 'activation diagnostics' "$TMP_DIR/activation-failure-output.log" || \
    fail 'Gateway activation failure did not trigger Podman diagnostics'
grep -Fq 'Could not start gateway.service.' "$TMP_DIR/activation-failure-output.log" || \
    fail 'Gateway activation failure did not report its systemd error'
if bash -c '
    source "$1"
    rollback_deployment() { printf "rollback attempted\n"; }
    APPLY_MUTATING=1
    ROLLBACK_READY=1
    PRESERVE_FAILED_STATE=1
    trap cleanup_after_apply EXIT
    exit 1
' _ "$DEPLOY_SCRIPT" > "$TMP_DIR/preserved-cleanup-output.log" 2>&1; then
    fail 'Preserved failed state returned success'
fi
grep -Fq 'automatic rollback was skipped' "$TMP_DIR/preserved-cleanup-output.log" || \
    fail 'Failed startup did not preserve state for debugging'
if grep -Fq 'rollback attempted' "$TMP_DIR/preserved-cleanup-output.log"; then
    fail 'Failed startup unexpectedly invoked deployment rollback'
fi
: > "$TMP_DIR/systemctl-call.log"
SYSTEMCTL_CALL_LOG="$TMP_DIR/systemctl-call.log" \
    PATH="$TMP_DIR/system-bin:$PATH" bash -c '
        source "$1"
        SERVICE_WAS_ACTIVE=0
        ACTIVATION_ATTEMPTED=1
        restore_gateway_service_state
    ' _ "$DEPLOY_SCRIPT"
grep -Fxq 'stop gateway.service' "$TMP_DIR/systemctl-call.log" || \
    fail 'Rollback did not stop the first-deploy Gateway unit'
if grep -Eq '^(enable|disable)( |$)' "$TMP_DIR/systemctl-call.log"; then
    fail 'Quadlet rollback tried to enable or disable a generated unit'
fi
printf 'PASS: generated Quadlet units start, restart, and roll back without enable/disable calls\n'
: > "$TMP_DIR/deploy-flow.log"
DEPLOY_FLOW_LOG="$TMP_DIR/deploy-flow.log" bash -c '
    source "$1"
    run_preflight_command() {
        printf "preflight %s\n" "$*" >> "$DEPLOY_FLOW_LOG"
    }
    acquire_gateway_config_lock() {
        printf "lock\n" >> "$DEPLOY_FLOW_LOG"
    }
    apply_deployment_locked() {
        printf "apply %s\n" "$1" >> "$DEPLOY_FLOW_LOG"
    }
    main "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json"
grep -Fxq "preflight --validate-gateway-config $TMP_DIR/valid.json" "$TMP_DIR/deploy-flow.log" || \
    fail 'Positional config did not validate first'
grep -Fxq 'lock' "$TMP_DIR/deploy-flow.log" || \
    fail 'Sequential deployment did not lock before host preflight'
grep -Fxq "preflight --check-gateway $TMP_DIR/valid.json" "$TMP_DIR/deploy-flow.log" || \
    fail 'Positional config did not run host preflight'
grep -Fxq "apply $TMP_DIR/valid.json" "$TMP_DIR/deploy-flow.log" || \
    fail 'Positional config did not apply after successful preflight'
[[ "$(grep -c . "$TMP_DIR/deploy-flow.log")" == 4 ]] || \
    fail 'Sequential deployment ran unexpected stages'
printf 'PASS: config-only invocation runs validate, check, and apply in order\n'
: > "$TMP_DIR/deploy-flow.log"
if DEPLOY_FLOW_LOG="$TMP_DIR/deploy-flow.log" bash -c '
    source "$1"
    run_preflight_command() {
        printf "preflight %s\n" "$*" >> "$DEPLOY_FLOW_LOG"
        [[ "$1" != "--check-gateway" ]]
    }
    acquire_gateway_config_lock() {
        printf "lock\n" >> "$DEPLOY_FLOW_LOG"
    }
    apply_deployment_locked() {
        printf "apply %s\n" "$1" >> "$DEPLOY_FLOW_LOG"
    }
    main "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json" >/dev/null 2>&1; then
    fail 'Sequential deployment continued after a failed host check'
fi
[[ "$(grep -c . "$TMP_DIR/deploy-flow.log")" == 3 ]] || \
    fail 'Failed host check did not stop before apply'
if grep -q '^apply ' "$TMP_DIR/deploy-flow.log"; then
    fail 'Failed host check reached the apply stage'
fi
printf 'PASS: sequential deployment stops immediately when a stage fails\n'
: > "$TMP_DIR/deploy-flow.log"
DEPLOY_FLOW_LOG="$TMP_DIR/deploy-flow.log" bash -c '
    source "$1"
    run_preflight_command() {
        printf "preflight %s\n" "$*" >> "$DEPLOY_FLOW_LOG"
    }
    acquire_gateway_config_lock() {
        printf "lock\n" >> "$DEPLOY_FLOW_LOG"
    }
    apply_deployment_locked() {
        printf "apply %s\n" "$1" >> "$DEPLOY_FLOW_LOG"
    }
    main --apply "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/valid.json" >/dev/null 2>&1
grep -Fxq "apply $TMP_DIR/valid.json" "$TMP_DIR/deploy-flow.log" || \
    fail 'Standalone apply did not invoke the apply stage'
if grep -q '^preflight ' "$TMP_DIR/deploy-flow.log"; then
    fail 'Standalone apply unexpectedly ran preflight'
fi
[[ "$(grep -c . "$TMP_DIR/deploy-flow.log")" == 2 ]] || \
    fail 'Standalone apply ran unexpected stages'
printf 'PASS: standalone apply skips preflight and assumes prior --check\n'
jq '.gateway.remote_access.openvpn.enabled = true |
    .gateway.remote_access.wireguard.enabled = true' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/remote-access-health.json"
REMOTE_ACCESS_HEALTH_LOG="$TMP_DIR/remote-access-health.log" bash -c '
    source "$1"
    podman() {
        printf "%s\n" "$*" >> "$REMOTE_ACCESS_HEALTH_LOG"
        case "$*" in
            *"dev tun0") printf "[{\"addr_info\":[{\"family\":\"inet\",\"local\":\"172.24.1.2\"}]}]\n" ;;
            *"dev wg0") printf "[{\"addr_info\":[{\"family\":\"inet\",\"local\":\"192.168.10.1\"}]}]\n" ;;
            *) return 97 ;;
        esac
    }
    check_gateway_remote_access_health "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/remote-access-health.json"
grep -Fq 'dev tun0' "$TMP_DIR/remote-access-health.log" || \
    fail 'Enabled OpenVPN tunnel readiness was not checked'
grep -Fq 'dev wg0' "$TMP_DIR/remote-access-health.log" || \
    fail 'Enabled WireGuard server readiness was not checked'
if bash -c '
    source "$1"
    podman() { printf "[]\n"; }
    check_gateway_remote_access_health "$2"
' _ "$DEPLOY_SCRIPT" "$TMP_DIR/remote-access-health.json" \
    > "$TMP_DIR/missing-tunnel-output.log" 2>&1; then
    fail 'Remote-access health accepted missing tunnel interfaces'
fi
grep -Fq 'OpenVPN tunnel is not ready: tun0 has no IPv4 address.' \
    "$TMP_DIR/missing-tunnel-output.log" || \
    fail 'Missing OpenVPN tunnel did not report an actionable health failure'
printf 'PASS: enabled remote-access tunnels must have ready IPv4 interfaces\n'
: > "$TMP_DIR/deploy-flow.log"
jq '.gateway.startup_readiness = {"timeout_seconds":3,"interval_seconds":1}' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/readiness-retry.json"
: > "$TMP_DIR/readiness-retry.log"
READINESS_CHECK_LOG="$TMP_DIR/readiness-retry.log" \
    bash -c '
        source "$1"
        check_gateway_health_once() {
            printf "attempt\n" >> "$READINESS_CHECK_LOG"
            if [[ "$(wc -l < "$READINESS_CHECK_LOG")" -lt 3 ]]; then
                printf "temporary startup miss\n" >&2
                return 1
            fi
            printf "health ready\n"
        }
        sleep() { SECONDS=$((SECONDS + $1)); }
        wait_for_gateway_health "$2" "$3"
    ' _ "$DEPLOY_SCRIPT" "$TMP_DIR/readiness-retry.json" "$TMP_DIR/dns-hosts" \
    > "$TMP_DIR/readiness-retry-output.log" 2>&1
[[ "$(grep -c '^attempt$' "$TMP_DIR/readiness-retry.log")" == 3 ]] || \
    fail 'Gateway readiness did not retry twice before succeeding'
if grep -Fq 'temporary startup miss' "$TMP_DIR/readiness-retry-output.log"; then
    fail 'Transient readiness errors were printed after a successful retry'
fi
grep -Fq 'Health checks passed after 3 attempts.' "$TMP_DIR/readiness-retry-output.log" || \
    fail 'Gateway readiness success did not report the retry count'
printf 'PASS: readiness retries suppress transient errors and stop on success\n'
jq '.gateway.startup_readiness = {"timeout_seconds":3,"interval_seconds":1}' \
    "$TMP_DIR/valid.json" > "$TMP_DIR/readiness-timeout.json"
: > "$TMP_DIR/readiness-timeout.log"
if READINESS_CHECK_LOG="$TMP_DIR/readiness-timeout.log" \
    bash -c '
        source "$1"
        DEBUG_PRESERVE_ACTIVE=1
        check_gateway_health_once() {
            printf "attempt\n" >> "$READINESS_CHECK_LOG"
            printf "startup still pending\n" >&2
            return 1
        }
        sleep() { SECONDS=$((SECONDS + $1)); }
        wait_for_gateway_health "$2" "$3"
    ' _ "$DEPLOY_SCRIPT" "$TMP_DIR/readiness-timeout.json" "$TMP_DIR/dns-hosts" \
    > "$TMP_DIR/readiness-timeout-output.log" 2>&1; then
    fail 'Readiness timeout accepted a Gateway that never became healthy'
fi
[[ "$(grep -c '^attempt$' "$TMP_DIR/readiness-timeout.log")" == 3 ]] || \
    fail 'Readiness timeout did not stop after its configured time budget'
grep -Fq 'Gateway did not become healthy within 3s after 3 attempts; state is preserved for debugging.' \
    "$TMP_DIR/readiness-timeout-output.log" || \
    fail 'Readiness timeout did not report its configured bound'
[[ "$(grep -c '^startup still pending$' "$TMP_DIR/readiness-timeout-output.log")" == 1 ]] || \
    fail 'Readiness timeout did not report only the last transient failure'
printf 'PASS: readiness retries stop at the configured timeout and report the last failure\n'
if READINESS_CHECK_LOG="$TMP_DIR/readiness-fail-fast.log" \
    bash -c '
        source "$1"
        DEBUG_PRESERVE_ACTIVE=1
        systemctl() {
            [[ "$*" == "show --property=ActiveState --value gateway.service" ]] || return 97
            printf "inactive\n"
        }
        check_gateway_health_once() {
            printf "attempt\n" >> "$READINESS_CHECK_LOG"
            printf "Gateway unit is not active: gateway.service\n" >&2
            return 1
        }
        debug_gateway_failure() { printf "diagnostics\n"; }
        sleep() { printf "unexpected retry\n" >> "$READINESS_CHECK_LOG"; }
        wait_for_gateway_health "$2" "$3"
    ' _ "$DEPLOY_SCRIPT" "$TMP_DIR/readiness-timeout.json" "$TMP_DIR/dns-hosts" \
    > "$TMP_DIR/readiness-fail-fast-output.log" 2>&1; then
    fail 'Readiness continued after systemd reported a terminal inactive state'
fi
[[ "$(grep -c '^attempt$' "$TMP_DIR/readiness-fail-fast.log")" == 1 ]] || \
    fail 'Terminal Gateway startup failure was checked more than once'
if grep -Fq 'unexpected retry' "$TMP_DIR/readiness-fail-fast.log"; then
    fail 'Terminal Gateway startup failure did not stop retries immediately'
fi
grep -Fq 'Gateway unit entered state inactive; stopping readiness retries.' \
    "$TMP_DIR/readiness-fail-fast-output.log" || \
    fail 'Terminal Gateway startup failure did not report the systemd state'
grep -Fxq 'diagnostics' "$TMP_DIR/readiness-fail-fast-output.log" || \
    fail 'Terminal Gateway startup failure did not run Podman diagnostics'
printf 'PASS: terminal inactive state stops retries and runs failure diagnostics\n'
if READINESS_CHECK_LOG="$TMP_DIR/readiness-rollback.log" \
    bash -c '
        source "$1"
        check_gateway_health_once() {
            printf "attempt\n" >> "$READINESS_CHECK_LOG"
            printf "transient health failure\n" >&2
            return 1
        }
        debug_gateway_failure() { :; }
        fail() { printf "%s\n" "$*" >&2; return 1; }
        sleep() { SECONDS=$((SECONDS + $1)); }
        if wait_for_gateway_health "$2" "$3"; then
            exit 98
        fi
        printf "preserve=%s\n" "$PRESERVE_FAILED_STATE"
    ' _ "$DEPLOY_SCRIPT" "$TMP_DIR/readiness-timeout.json" "$TMP_DIR/dns-hosts" \
    > "$TMP_DIR/readiness-rollback-output.log" 2>&1; then
    :
else
    fail 'Readiness rollback-mode test exited unexpectedly'
fi
grep -Fxq 'preserve=0' "$TMP_DIR/readiness-rollback-output.log" || \
    fail 'Health failure without debug mode incorrectly preserved deployment state'
grep -Fq 'deployment rollback will restore prior state.' \
    "$TMP_DIR/readiness-rollback-output.log" || \
    fail 'Health failure without debug mode did not report rollback behavior'
printf 'PASS: failures without debug mode retain normal rollback behavior\n'
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
    OPENVPN_ROUTE_STATE='[{"dst":"172.24.0.0/21","gateway":"10.89.1.2","protocol":"bgp","table":"main"}]' \
    ROUTE_MUTATION_LOG="$TMP_DIR/bgp-route-mutations.log" \
    bash -c 'source "$1"; remove_managed_remote_access_return_routes "$2"' \
    _ "$DEPLOY_SCRIPT" "$TMP_DIR/openvpn-disabled-route.json"
grep -Fxq -- \
    '-4 route del 172.24.0.0/21 via 10.89.1.2 proto 186' \
    "$TMP_DIR/bgp-route-mutations.log" || \
    fail 'The iproute2 bgp alias for protocol 186 was not cleaned'
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
    "$DEPLOY_SCRIPT" "$TMP_DIR/malformed.json" >/dev/null 2>&1; then
    fail 'sequential deployment accepted malformed configuration'
fi
[[ ! -s "$TMP_DIR/host-commands.log" ]] || fail 'sequential deployment ran host commands before rejecting malformed configuration'
printf 'PASS: invalid sequential deployment stops before host commands\n'
for duplicate_config in "$TMP_DIR/duplicate-top-level.json" "$TMP_DIR/duplicate-nested.json"; do
    if PATH="$TMP_DIR/fake-bin:$PATH" HOST_COMMAND_LOG="$TMP_DIR/host-commands.log" \
        "$DEPLOY_SCRIPT" "$duplicate_config" >/dev/null 2>&1; then
        fail 'sequential deployment accepted duplicate JSON keys'
    fi
    [[ ! -s "$TMP_DIR/host-commands.log" ]] || fail 'sequential deployment ran host commands before rejecting duplicate keys'
done
printf 'PASS: duplicate-key sequential deployment failures stop before host commands\n'

before=$(sha256sum "$SAMPLE_CONFIG")
"$DEPLOY_SCRIPT" --validate-config "$SAMPLE_CONFIG" >/dev/null
after=$(sha256sum "$SAMPLE_CONFIG")
[[ "$before" == "$after" ]] || fail 'validation changed the source configuration'
printf 'PASS: validation leaves source configuration unchanged\n'