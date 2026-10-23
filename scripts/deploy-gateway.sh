#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PREFLIGHT_SCRIPT="$SCRIPT_DIR/host-preflight.sh"
source "$PREFLIGHT_SCRIPT"

APPLY_MUTATING=0
ROLLBACK_READY=0
BACKUP_DIR=''
STAGED_CONFIG=''
STAGED_INPUTS=''
STAGED_DNS=''
STAGED_QUADLET=''
STAGED_DEBUG_QUADLET=''
STAGED_DEBUG_DROPIN=''
PREVIOUS_IMAGE_ID=''
SERVICE_WAS_ACTIVE=0
SOCKET_WAS_ACTIVE=0
ACTIVATION_ATTEMPTED=0
NETWORKS_CREATED=()
WIREGUARD_KEY_CREATED=0
WIREGUARD_KEY_PATH=''
WIREGUARD_KERNEL_LOAD_ATTEMPTED=0
GATEWAY_CONFIG_LOCK_FD=''
PRESERVE_FAILED_STATE=0
DEBUG_PRESERVE_ACTIVE=0
DEBUG_DROPIN_DIR_CREATED=0
DEBUG_DROPIN_INSTALLED=0

usage() {
    printf 'Usage: %s --validate-config|--check|--apply [host_config.json] | %s host_config.json\n' \
        "${0##*/}" "${0##*/}"
}
prepare_state_directories() {
    install -d -o root -g root -m 0755 "$STATE_DIR" "$STATE_DIR/generated" "$STATE_DIR/dns"
    install -d -o root -g root -m 0700 "$HOST_KEYS_DIR"
    install -d -o root -g root -m 0700 "$STATE_DIR/wireguard"
    if [[ ! -e "$OWNER_MARKER" ]]; then
        printf '%s\n' 'managed by scripts/deploy-gateway.sh' > "$OWNER_MARKER"
        chmod 0644 "$OWNER_MARKER"
    fi
}

ensure_host_keys() {
    local private_key="$HOST_KEYS_DIR/ssh_host_ed25519_key"
    local public_key="$private_key.pub"

    if [[ ! -e "$private_key" && ! -e "$public_key" ]]; then
        ssh-keygen -q -t ed25519 -N '' -C gateway -f "$private_key" || \
            fail 'Could not create the persistent SSH host key.'
        chmod 0600 "$private_key"
        chmod 0644 "$public_key"
    fi
}

create_declared_networks() {
    local config_path=$1 network subnet status

    while IFS= read -r network; do
        [[ -n "$network" ]] || continue
        status=0
        podman network exists "$network" >/dev/null 2>&1 || status=$?
        case "$status" in
            0) ;;
            1)
                subnet=$(jq -r --arg name "$network" '.networks[] | select(.name == $name) | .subnet' "$config_path")
                podman network create --subnet "$subnet" "$network" >/dev/null || \
                    fail "Could not create declared Podman network '$network'."
                NETWORKS_CREATED+=("$network")
                ;;
            *) fail "Could not inspect declared Podman network '$network'." ;;
        esac
    done < <(jq -r '.networks[].name' "$config_path")
}

# Write config-only pending DNS declarations without probing target containers.
# Arguments: host config path and staged DNS output path. Writes only that output.
generate_dns_candidate() {
    local config_path=$1 output_path=$2 dns_name container

    printf '# Managed by scripts/deploy-gateway.sh\n' > "$output_path"
    while IFS=$'\t' read -r dns_name container; do
        [[ -n "$dns_name" ]] || continue
        printf '# PENDING DNS target: %s (%s readiness/unverified)\n' \
            "$dns_name" "$container" >> "$output_path"
    done < <(jq -r '.dns_records[]? | [.name, .container] | @tsv' "$config_path")
    chmod 0644 "$output_path"
}
# ---------------------------------- #

# Load WireGuard kernel support only when the validated configuration enables it.
# Arguments: validated host configuration path. May load a host kernel module.
# Output: loader status; failures are reported to stderr.
ensure_wireguard_kernel_module() {
    local config_path=$1 wireguard_enabled

    wireguard_enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$config_path")
    [[ "$wireguard_enabled" == true ]] || return 0
    WIREGUARD_KERNEL_LOAD_ATTEMPTED=1
    run_python_module scripts.gateway.wireguard_kernel || \
        fail 'Could not load WireGuard kernel support; check host module availability and policy.'
}
# ---------------------------------- #

# Validate an existing WireGuard server key in a short-lived read-only container.
# Arguments: configured host key path. Reads only that key and never emits its contents.
# Output: validation status only; failures are reported to stderr.
validate_wireguard_server_key() {
    local key_path=$1

    podman run --pull=never --rm --network none --user 0 --userns=host \
        --read-only --cap-drop=all --security-opt=no-new-privileges \
        --env PYTHONDONTWRITEBYTECODE=1 \
        --volume "$key_path:/run/gateway/wireguard/server.key:ro,noexec,nosuid,nodev" \
        --entrypoint /usr/local/bin/gateway-wireguard "$IMAGE" \
        server-key validate || fail "Existing WireGuard server key is invalid: $key_path"
}
# ---------------------------------- #

# Generate a missing WireGuard server key in a short-lived isolated container.
# Arguments: validated host config path. Reads the built image and writes only the configured key.
# Output: status messages only; the private key stays in the helper container and mounted file.
ensure_wireguard_server_key() {
    local config_path=$1 wireguard_enabled key_path key_directory key_filename
    local mode

    wireguard_enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$config_path")
    [[ "$wireguard_enabled" == true ]] || return 0
    key_path=$(jq -r '.gateway.remote_access.wireguard.server_private_key_path' "$config_path")

    if [[ -e "$key_path" || -L "$key_path" ]]; then
        [[ -f "$key_path" && ! -L "$key_path" && -s "$key_path" ]] || \
            fail "Existing WireGuard server key is not a non-empty regular file: $key_path"
        validate_wireguard_server_key "$key_path"
        printf '[gateway] Reusing the configured WireGuard server key; existing client profiles remain valid.\n'
        return 0
    fi

    key_directory=${key_path%/*}
    key_filename=${key_path##*/}
    [[ "$key_directory" != "$key_path" && -n "$key_filename" ]] || \
        fail 'WireGuard server key path must name a file in a directory.'
    if [[ -L "$key_directory" ]]; then
        fail "WireGuard server key directory must not be a symlink: $key_directory"
    elif [[ -e "$key_directory" ]]; then
        [[ -d "$key_directory" ]] || fail "WireGuard server key parent is not a directory: $key_directory"
        mode=$(stat -c %a -- "$key_directory") || fail "Cannot inspect WireGuard server key directory: $key_directory"
        (( (8#$mode & 0022) == 0 )) || \
            fail "WireGuard server key directory must not be group/world writable: $key_directory"
    else
        install -d -o root -g root -m 0700 -- "$key_directory" || \
            fail "Could not create WireGuard server key directory: $key_directory"
    fi

    if ! podman run --pull=never --rm --network none --user 0 --userns=host \
        --read-only --cap-drop=all --security-opt=no-new-privileges \
        --env PYTHONDONTWRITEBYTECODE=1 \
        --volume "$key_directory:/run/gateway/wireguard:rw,noexec,nosuid,nodev" \
        --entrypoint /usr/local/bin/gateway-wireguard "$IMAGE" \
        server-key generate --filename "$key_filename"; then
        if [[ -e "$key_path" || -L "$key_path" ]]; then
            WIREGUARD_KEY_CREATED=1
            WIREGUARD_KEY_PATH=$key_path
        fi
        fail "WireGuard server-key generation failed; an existing key was not overwritten."
    fi

    WIREGUARD_KEY_CREATED=1
    WIREGUARD_KEY_PATH=$key_path
    [[ -f "$key_path" && ! -L "$key_path" && -s "$key_path" ]] || \
        fail "WireGuard server-key helper did not create a regular key file: $key_path"
    printf '[gateway] Generated the persistent WireGuard server key at %s.\n' "$key_path"
}
# ---------------------------------- #

generate_input_metadata() {
    local config_path=$1 output_path=$2 authorized_keys_path host_key_fingerprint
    local authorized_keys_metadata cockpit_password_metadata certificate_metadata private_key_metadata

    authorized_keys_path=$(jq -r '.gateway.authorized_keys_path' "$config_path")
    authorized_keys_metadata=$(stat -c '%u:%g:%a:%d:%i:%s:%y' "$authorized_keys_path")
    cockpit_password_metadata=$(stat -c '%u:%g:%a:%d:%i:%s:%y' "$COCKPIT_PASSWORD_FILE")
    certificate_metadata=$(stat -c '%u:%g:%a:%d:%i:%s:%y' "$COCKPIT_CERT_FILE")
    private_key_metadata=$(stat -c '%u:%g:%a:%d:%i:%s:%y' "$COCKPIT_KEY_FILE")
    host_key_fingerprint=$(ssh-keygen -lf "$HOST_KEYS_DIR/ssh_host_ed25519_key.pub" | awk '{print $2}')

    jq -n \
        --arg authorized_keys "$authorized_keys_metadata" \
        --arg cockpit_password "$cockpit_password_metadata" \
        --arg cockpit_certificate "$certificate_metadata" \
        --arg cockpit_private_key "$private_key_metadata" \
        --arg ssh_host_key_fingerprint "$host_key_fingerprint" \
        '{schema_version: 1, authorized_keys: $authorized_keys, cockpit_password: $cockpit_password,
          cockpit_certificate: $cockpit_certificate, cockpit_private_key: $cockpit_private_key,
          ssh_host_key_fingerprint: $ssh_host_key_fingerprint}' > "$output_path"
    chmod 0644 "$output_path"
}

# Render one owned host route with quiet, exact missing-route cleanup.
# Arguments: IPv4 pool and deterministic Gateway next hop. Writes Quadlet directives to stdout.
# Output: ExecStartPost and ExecStopPost lines for protocol 186.
render_host_return_route() {
    local pool=$1 route_gateway=$2 cleanup_command

    cleanup_command=$(printf \
        'output=$(/usr/sbin/ip -4 route del %s via %s proto 186 2>&1); status=$?; if [ "$status" -eq 2 ] && [ "$output" = "RTNETLINK answers: No such process" ]; then exit 0; fi; [ "$status" -eq 0 ] || { printf "%%s\\n" "$output" >&2; exit "$status"; }' \
        "$pool" "$route_gateway")
    printf 'ExecStartPost=/usr/sbin/ip -4 route add %s via %s proto 186\n' \
        "$pool" "$route_gateway"
    printf "ExecStopPost=-/bin/sh -c '%s'\n" "$cleanup_command"
}
# ---------------------------------- #

render_quadlet_candidate() {
    local config_path=$1 output_path=$2 preserve_failed_container=${3:-false}
    local authorized_keys_path ssh_bind_address cockpit_bind_address ssh_port cockpit_port
    local network_lines published_lines openvpn_volume='' openvpn_runtime=''
    local ssh_tun_volume='' ssh_tun_runtime=''
    local openvpn_host_route='' ssh_tun_host_route=''
    local wireguard_volume='' wireguard_peers_volume='' wireguard_runtime=''
    local wireguard_host_route='' wireguard_module_load='' wireguard_enabled wireguard_key_path
    local wireguard_bind_address wireguard_port wireguard_pool
    local openvpn_enabled ssh_tun_enabled profile_path client_pool route_gateway
    local ssh_tun_pool ssh_tun_keys_path debug_podman_args=''
    local template

    if [[ "$preserve_failed_container" == true ]]; then
        debug_podman_args='PodmanArgs=--rm=false'
    fi
    authorized_keys_path=$(jq -r '.gateway.authorized_keys_path' "$config_path")
    ssh_bind_address=$(jq -r '.gateway.ssh_bind_address // .gateway.bind_address' "$config_path")
    cockpit_bind_address=$(jq -r '.gateway.cockpit_bind_address // .gateway.bind_address' "$config_path")
    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    network_lines=$(jq -r '
        .networks[] |
        "Network=" + .name +
            (if has("gateway_address") then ":ip=" + .gateway_address else "" end)
    ' "$config_path")
    published_lines=$(printf 'PublishPort=%s:%s:22\nPublishPort=%s:%s:9090' \
        "$ssh_bind_address" "$ssh_port" "$cockpit_bind_address" "$cockpit_port")
    openvpn_enabled=$(jq -r '.gateway.remote_access.openvpn.enabled // false' "$config_path")
    client_pool=$(jq -r '.gateway.remote_access.openvpn.client_pool // empty' "$config_path")
    ssh_tun_enabled=$(jq -r '.gateway.remote_access.ssh_tun.enabled // false' "$config_path")
    wireguard_enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$config_path")
    if [[ "$ssh_tun_enabled" == true || "$wireguard_enabled" == true || \
        ( "$openvpn_enabled" == true && -n "$client_pool" ) ]]; then
        route_gateway=$(jq -r '
            [.networks[] | select(has("gateway_address"))] |
            sort_by([
                (.subnet | split("/")[0] | split(".") | map(tonumber)),
                (.subnet | split("/")[1] | tonumber),
                .name
            ]) | .[0].gateway_address // empty
        ' "$config_path")
        [[ -n "$route_gateway" ]] || fail 'Remote access requires a deterministic host return-route next hop.'
    fi
    if [[ "$openvpn_enabled" == true ]]; then
        profile_path=$(jq -r '.gateway.remote_access.openvpn.profile_path' "$config_path")
        openvpn_volume="Volume=${profile_path}:/run/openvpn/client.ovpn:ro"
        openvpn_runtime=$'AddDevice=/dev/net/tun\nAddCapability=NET_ADMIN'
        if [[ -n "$client_pool" ]]; then
            openvpn_host_route=$(render_host_return_route "$client_pool" "$route_gateway")
        fi
    fi
    if [[ "$ssh_tun_enabled" == true ]]; then
        ssh_tun_pool=$(jq -r '.gateway.remote_access.ssh_tun.address_pool' "$config_path")
        ssh_tun_keys_path=$(jq -r '.gateway.remote_access.ssh_tun.authorized_keys_path' "$config_path")
        ssh_tun_volume="Volume=${ssh_tun_keys_path}:/run/gateway/ssh_tun/authorized_keys:ro"
        ssh_tun_runtime=$'AddDevice=/dev/net/tun\nAddCapability=NET_ADMIN'
        if [[ "$openvpn_enabled" == true ]]; then
            ssh_tun_runtime=''
        fi
        ssh_tun_host_route=$(render_host_return_route "$ssh_tun_pool" "$route_gateway")
    fi
    if [[ "$wireguard_enabled" == true ]]; then
        wireguard_key_path=$(jq -r '.gateway.remote_access.wireguard.server_private_key_path' "$config_path")
        wireguard_bind_address=$(jq -r '.gateway.remote_access.wireguard.host_bind_address' "$config_path")
        wireguard_port=$(jq -r '.gateway.remote_access.wireguard.listen_port' "$config_path")
        wireguard_pool=$(jq -r '.gateway.remote_access.wireguard.address_pool' "$config_path")
        wireguard_volume="Volume=${wireguard_key_path}:/run/gateway/wireguard/server.key:ro"
        wireguard_peers_volume="Volume=${STATE_DIR}/wireguard:/var/lib/gateway/wireguard:rw"
        if [[ "$openvpn_enabled" != true && "$ssh_tun_enabled" != true ]]; then
            wireguard_runtime='AddCapability=NET_ADMIN'
        fi
        wireguard_module_load='ExecStartPre=/usr/sbin/modprobe --use-blacklist wireguard'
        published_lines+=$(printf '\nPublishPort=%s:%s:%s/udp' \
            "$wireguard_bind_address" "$wireguard_port" "$wireguard_port")
        wireguard_host_route=$(render_host_return_route "$wireguard_pool" "$route_gateway")
    fi
    template=$(<"$UNIT_TEMPLATE")
    template=${template//@@CONFIG_FILE@@/$GENERATED_CONFIG}
    template=${template//@@AUTHORIZED_KEYS@@/$authorized_keys_path}
    template=${template//@@OPENVPN_VOLUME@@/$openvpn_volume}
    template=${template//@@OPENVPN_RUNTIME@@/$openvpn_runtime}
    template=${template//@@OPENVPN_HOST_ROUTE@@/$openvpn_host_route}
    template=${template//@@SSH_TUN_VOLUME@@/$ssh_tun_volume}
    template=${template//@@SSH_TUN_RUNTIME@@/$ssh_tun_runtime}
    template=${template//@@SSH_TUN_HOST_ROUTE@@/$ssh_tun_host_route}
    template=${template//@@WIREGUARD_VOLUME@@/$wireguard_volume}
    template=${template//@@WIREGUARD_PEERS_VOLUME@@/$wireguard_peers_volume}
    template=${template//@@WIREGUARD_RUNTIME@@/$wireguard_runtime}
    template=${template//@@DEBUG_PODMAN_ARGS@@/$debug_podman_args}
    template=${template//@@WIREGUARD_MODULE_LOAD@@/$wireguard_module_load}
    template=${template//@@WIREGUARD_HOST_ROUTE@@/$wireguard_host_route}
    template=${template//@@NETWORKS@@/$network_lines}
    template=${template//@@PUBLISHED_PORTS@@/$published_lines}
    [[ "$template" != *@@* ]] || fail 'Quadlet template contains an unexpanded placeholder.'
    printf '%s\n' "$template" > "$output_path"
    chmod 0644 "$output_path"
}

# Render systemd overrides that retain the Podman container for failure debugging.
# Arguments: rendered Quadlet candidate and output path. Recreates only owned route cleanup hooks.
render_gateway_debug_dropin() {
    local quadlet_candidate=$1 output_path=$2 line

    {
        printf '%s\n[Service]\nRestart=no\nExecStop=\nExecStopPost=\n' \
            "$GATEWAY_DEBUG_DROPIN_MARKER"
        while IFS= read -r line; do
            case "$line" in
                'ExecStopPost=-/bin/sh -c '*)
                    [[ "$line" == *'/usr/sbin/ip -4 route del '* &&
                        "$line" == *'proto 186 2>&1'* &&
                        "$line" == *'RTNETLINK answers: No such process'* ]] || \
                        fail "Unexpected Gateway stop hook in debug candidate: $line"
                    printf '%s\n' "$line"
                    ;;
                ExecStopPost=*)
                    fail "Unexpected Gateway stop hook in debug candidate: $line"
                    ;;
            esac
        done < "$quadlet_candidate"
    } > "$output_path"
    chmod 0644 "$output_path"
}
# ---------------------------------- #

install_gateway_debug_dropin() {
    local directory_mode

    if [[ -e "$GATEWAY_DEBUG_DROPIN" || -L "$GATEWAY_DEBUG_DROPIN" ]]; then
        gateway_debug_dropin_is_managed || \
            fail "Gateway debug-preserve override is not owned by deployment: $GATEWAY_DEBUG_DROPIN"
    elif [[ -L "$GATEWAY_DEBUG_DROPIN_DIR" ]]; then
        fail "Gateway debug-preserve directory must not be a symlink: $GATEWAY_DEBUG_DROPIN_DIR"
    elif [[ -e "$GATEWAY_DEBUG_DROPIN_DIR" ]]; then
        [[ -d "$GATEWAY_DEBUG_DROPIN_DIR" ]] || \
            fail "Gateway debug-preserve path is not a directory: $GATEWAY_DEBUG_DROPIN_DIR"
        [[ "$(stat -c %u "$GATEWAY_DEBUG_DROPIN_DIR")" == 0 ]] || \
            fail "Gateway debug-preserve directory must be root-owned: $GATEWAY_DEBUG_DROPIN_DIR"
        directory_mode=$(stat -c %a "$GATEWAY_DEBUG_DROPIN_DIR") || \
            fail "Cannot inspect Gateway debug-preserve directory: $GATEWAY_DEBUG_DROPIN_DIR"
        (( (8#$directory_mode & 0022) == 0 )) || \
            fail "Gateway debug-preserve directory must not be group/world writable: $GATEWAY_DEBUG_DROPIN_DIR"
    else
        install -d -o root -g root -m 0755 -- "$GATEWAY_DEBUG_DROPIN_DIR" || \
            fail "Could not create Gateway debug-preserve directory: $GATEWAY_DEBUG_DROPIN_DIR"
        DEBUG_DROPIN_DIR_CREATED=1
    fi

    if [[ ! -e "$GATEWAY_DEBUG_DROPIN" ]] || \
        ! cmp -s -- "$STAGED_DEBUG_DROPIN" "$GATEWAY_DEBUG_DROPIN"; then
        install_atomic_if_changed "$STAGED_DEBUG_DROPIN" "$GATEWAY_DEBUG_DROPIN" 0644 || \
            fail "Could not install Gateway debug-preserve override: $GATEWAY_DEBUG_DROPIN"
    fi
    DEBUG_DROPIN_INSTALLED=1
    DEBUG_PRESERVE_ACTIVE=1
}
# ---------------------------------- #

remove_gateway_debug_dropin() {
    if (( DEBUG_DROPIN_INSTALLED == 1 )); then
        rm -- "$GATEWAY_DEBUG_DROPIN" || fail "Could not remove debug override $GATEWAY_DEBUG_DROPIN."
        DEBUG_DROPIN_INSTALLED=0
    fi
    if (( DEBUG_DROPIN_DIR_CREATED == 1 )); then
        if rmdir -- "$GATEWAY_DEBUG_DROPIN_DIR"; then
            DEBUG_DROPIN_DIR_CREATED=0
        else
            printf '[gateway] Retaining non-empty debug override directory %s.\n' \
                "$GATEWAY_DEBUG_DROPIN_DIR" >&2
            DEBUG_DROPIN_DIR_CREATED=0
        fi
    fi
}
# ---------------------------------- #

normalize_gateway_debug_unit() {
    if ! cmp -s -- "$STAGED_QUADLET" "$QUADLET_FILE"; then
        install_atomic_if_changed "$STAGED_QUADLET" "$QUADLET_FILE" 0644 || \
            fail 'Could not restore the normal Gateway Quadlet after health checks passed.'
    fi
    remove_gateway_debug_dropin
    if ! systemctl daemon-reload; then
        if ! cmp -s -- "$STAGED_DEBUG_QUADLET" "$QUADLET_FILE"; then
            install_atomic_if_changed "$STAGED_DEBUG_QUADLET" "$QUADLET_FILE" 0644 || \
                printf '[gateway] ERROR: could not restore the debug Quadlet candidate.\n' >&2
        fi
        install_gateway_debug_dropin
        systemctl daemon-reload || \
            printf '[gateway] ERROR: systemd could not reload the retained debug override.\n' >&2
        fail 'Systemd could not restore the normal Gateway unit; debug state is preserved.'
    fi
    DEBUG_PRESERVE_ACTIVE=0
    PRESERVE_FAILED_STATE=0
}
# ---------------------------------- #

validate_quadlet_candidate() {
    local candidate=$1 temporary_dir input_dir normal_dir early_dir late_dir generator status

    temporary_dir=$(mktemp -d /var/tmp/gateway-quadlet.XXXXXX)
    input_dir="$temporary_dir/input"
    normal_dir="$temporary_dir/normal"
    early_dir="$temporary_dir/early"
    late_dir="$temporary_dir/late"
    mkdir -p "$input_dir" "$normal_dir" "$early_dir" "$late_dir"
    cp -- "$candidate" "$input_dir/gateway.container"
    if [[ -x /usr/lib/systemd/system-generators/podman-system-generator ]]; then
        generator=/usr/lib/systemd/system-generators/podman-system-generator
    else
        generator=/usr/libexec/podman/quadlet
    fi

    status=0
    QUADLET_UNIT_DIRS="$input_dir" "$generator" -dryrun "$normal_dir" "$early_dir" "$late_dir" \
        > "$temporary_dir/generated-units" 2> "$temporary_dir/generator-errors" || status=$?
    if (( status != 0 )) || ! grep -Fq 'Description=Shared Gateway' "$temporary_dir/generated-units"; then
        cat "$temporary_dir/generator-errors" >&2
        rm -f -- "$input_dir/gateway.container" "$temporary_dir/generated-units" \
            "$temporary_dir/generator-errors"
        rmdir -- "$input_dir" "$normal_dir" "$early_dir" "$late_dir" "$temporary_dir" 2>/dev/null || true
        fail 'Podman Quadlet generator rejected the staged gateway unit.'
    fi

    rm -f -- "$input_dir/gateway.container" "$temporary_dir/generated-units" \
        "$temporary_dir/generator-errors"
    rmdir -- "$input_dir" "$normal_dir" "$early_dir" "$late_dir" "$temporary_dir" || \
        fail 'Could not remove temporary Quadlet validation files.'
}

stage_managed_files() {
    local config_path=$1

    STAGED_CONFIG=$(mktemp "$STATE_DIR/generated/.config.XXXXXX")
    STAGED_INPUTS=$(mktemp "$STATE_DIR/generated/.inputs.XXXXXX")
    STAGED_DNS=$(mktemp "$STATE_DIR/dns/.hosts.XXXXXX")
    STAGED_QUADLET=$(mktemp "$QUADLET_DIR/.gateway.XXXXXX")
    cp -- "$config_path" "$STAGED_CONFIG"
    chmod 0644 "$STAGED_CONFIG"
    generate_input_metadata "$config_path" "$STAGED_INPUTS"
    generate_dns_candidate "$config_path" "$STAGED_DNS"
    render_quadlet_candidate "$config_path" "$STAGED_QUADLET"
}

stage_debug_gateway_files() {
    local config_path=$1

    STAGED_DEBUG_QUADLET=$(mktemp "$QUADLET_DIR/.gateway-debug.XXXXXX")
    render_quadlet_candidate "$config_path" "$STAGED_DEBUG_QUADLET" true
    validate_quadlet_candidate "$STAGED_DEBUG_QUADLET"
    STAGED_DEBUG_DROPIN=$(mktemp /var/tmp/gateway-debug-preserve.XXXXXX)
    render_gateway_debug_dropin "$STAGED_DEBUG_QUADLET" "$STAGED_DEBUG_DROPIN"
}

install_atomic_if_changed() {
    local source=$1 target=$2 mode=$3 temporary

    if [[ -f "$target" ]] && cmp -s -- "$source" "$target"; then
        return 1
    fi
    temporary=$(mktemp "$(dirname -- "$target")/.$(basename -- "$target").XXXXXX")
    install -o root -g root -m "$mode" -- "$source" "$temporary"
    mv -f -- "$temporary" "$target"
    return 0
}

snapshot_file() {
    local target=$1 backup_name=$2

    if [[ -e "$target" ]]; then
        cp -p -- "$target" "$BACKUP_DIR/$backup_name"
    else
        : > "$BACKUP_DIR/$backup_name.absent"
    fi
}

restore_file() {
    local target=$1 backup_name=$2 temporary

    if [[ -f "$BACKUP_DIR/$backup_name" ]]; then
        temporary=$(mktemp "$(dirname -- "$target")/.$(basename -- "$target").rollback.XXXXXX") || return 1
        cp -p -- "$BACKUP_DIR/$backup_name" "$temporary" || return 1
        mv -f -- "$temporary" "$target" || return 1
    elif [[ -f "$BACKUP_DIR/$backup_name.absent" ]]; then
        rm -f -- "$target" || return 1
    else
        return 1
    fi
}

# Restore only the prior active state of the generated Quadlet service.
# Arguments: none. Reads SERVICE_WAS_ACTIVE and ACTIVATION_ATTEMPTED.
# Output: expected absent-unit stop errors are suppressed.
# Return status: nonzero if a previously active service cannot start.
restore_gateway_service_state() {
    if [[ "$SERVICE_WAS_ACTIVE" == 1 ]]; then
        systemctl start "$UNIT_NAME" >/dev/null 2>&1 || {
            printf '[gateway] ERROR: previous gateway service did not recover.\n' >&2
            return 1
        }
    elif [[ "$ACTIVATION_ATTEMPTED" == 1 ]]; then
        systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    fi
}
# ---------------------------------- #

rollback_deployment() {
    local rollback_failed=0

    printf '[gateway] Apply failed; restoring generated files and prior service state.\n' >&2
    if [[ "$ACTIVATION_ATTEMPTED" == 1 ]]; then
        systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    fi

    restore_file "$QUADLET_FILE" quadlet || { printf '[gateway] ERROR: could not restore Quadlet file.\n' >&2; rollback_failed=1; }
    restore_file "$GENERATED_CONFIG" config || { printf '[gateway] ERROR: could not restore generated configuration.\n' >&2; rollback_failed=1; }
    restore_file "$GENERATED_INPUTS" inputs || { printf '[gateway] ERROR: could not restore runtime input metadata.\n' >&2; rollback_failed=1; }
    restore_file "$DNS_HOSTS_FILE" dns || { printf '[gateway] ERROR: could not restore generated DNS records.\n' >&2; rollback_failed=1; }

    if [[ -n "$PREVIOUS_IMAGE_ID" ]]; then
        podman tag "$PREVIOUS_IMAGE_ID" "$IMAGE" >/dev/null 2>&1 || {
            printf '[gateway] ERROR: could not restore the previous image tag.\n' >&2
            rollback_failed=1
        }
    fi

    systemctl daemon-reload >/dev/null 2>&1 || {
        printf '[gateway] ERROR: systemd reload failed during rollback.\n' >&2
        rollback_failed=1
    }
    restore_gateway_service_state || rollback_failed=1

    if [[ "$SOCKET_WAS_ACTIVE" != 1 ]]; then
        systemctl stop podman.socket >/dev/null 2>&1 || true
    fi
    if (( ${#NETWORKS_CREATED[@]} > 0 )); then
        printf '[gateway] Additive networks remain and were not removed: %s\n' "${NETWORKS_CREATED[*]}" >&2
    fi
    printf '[gateway] Persistent SSH host keys and built images remain untouched.\n' >&2
    if (( rollback_failed == 0 )); then
        printf '[gateway] Previous generated files and service state restored.\n' >&2
    else
        printf '[gateway] ERROR: rollback was incomplete; inspect systemd and Podman state before retrying.\n' >&2
    fi
}

test_dns_candidate() {
    local candidate=$1

    podman run --rm --network none \
        --volume "$candidate:/run/gateway/dns/hosts:ro" \
        --entrypoint dnsmasq "$IMAGE" --test --no-resolv --no-hosts \
        --bind-dynamic --addn-hosts=/run/gateway/dns/hosts >/dev/null || \
        fail 'Candidate DNS records failed DNSMasq validation.'
}

# Require each enabled remote-access transport to establish its configured Gateway interface.
# Arguments: validated host configuration path. Inspects only the Gateway container.
# Output: none. Reports missing tunnel readiness to stderr and exits nonzero.
check_gateway_remote_access_health() {
    local config_path=$1 openvpn_enabled wireguard_enabled server_address interface_addresses

    openvpn_enabled=$(jq -r '.gateway.remote_access.openvpn.enabled // false' "$config_path")
    if [[ "$openvpn_enabled" == true ]]; then
        interface_addresses=$(podman exec "$CONTAINER_NAME" ip -j -4 address show dev tun0 2>/dev/null) || \
            fail 'OpenVPN tunnel is not ready: tun0 is absent.'
        jq -e 'any(.[].addr_info[]?; .family == "inet")' \
            <<< "$interface_addresses" >/dev/null || \
            fail 'OpenVPN tunnel is not ready: tun0 has no IPv4 address.'
    fi

    wireguard_enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$config_path")
    if [[ "$wireguard_enabled" == true ]]; then
        server_address=$(jq -r '.gateway.remote_access.wireguard.server_address' "$config_path")
        interface_addresses=$(podman exec "$CONTAINER_NAME" ip -j -4 address show dev wg0 2>/dev/null) || \
            fail 'WireGuard server is not ready: wg0 is absent.'
        jq -e --arg address "$server_address" \
            'any(.[].addr_info[]?; .family == "inet" and .local == $address)' \
            <<< "$interface_addresses" >/dev/null || \
            fail "WireGuard server is not ready: wg0 lacks $server_address."
    fi
}
# ---------------------------------- #

check_gateway_health_once() {
    local config_path=$1 dns_file=$2 ssh_bind_address cockpit_bind_address ssh_port cockpit_port expected_networks attached_networks
    local resolved expected_address dns_name network actual_address

    systemctl is-active --quiet "$UNIT_NAME" || fail "Gateway unit is not active: $UNIT_NAME"
    [[ "$(podman inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" == true ]] || \
        fail "Gateway container is not running: $CONTAINER_NAME"
    check_gateway_remote_access_health "$config_path"

    expected_networks=$(jq -c '[.networks[].name] | sort' "$config_path")
    attached_networks=$(podman inspect --format '{{json .NetworkSettings.Networks}}' "$CONTAINER_NAME") || \
        fail 'Cannot inspect gateway network attachments.'
    jq -e --argjson expected "$expected_networks" 'keys | sort == $expected' <<< "$attached_networks" >/dev/null || \
        fail 'Gateway network attachments differ from the declared application networks.'

    while IFS=' ' read -r network expected_address; do
        [[ -n "$network" && -n "$expected_address" ]] || continue
        actual_address=$(jq -r --arg network "$network" '.[$network].IPAddress // ""' <<< "$attached_networks")
        [[ "$actual_address" == "$expected_address" ]] || \
            fail "Gateway address on network '$network' is '$actual_address'; expected '$expected_address'."
    done < <(jq -r '
        .networks[] | select(has("gateway_address")) |
        "\(.name) \(.gateway_address)"
    ' "$config_path")

    podman exec "$CONTAINER_NAME" /usr/sbin/sshd -t -f /run/gateway/sshd_config || \
        fail 'OpenSSH health check failed.'
    podman exec "$CONTAINER_NAME" dnsmasq --test --no-resolv --no-hosts --bind-dynamic \
        --addn-hosts=/run/gateway/dns/hosts >/dev/null || fail 'DNSMasq health check failed.'
    [[ "$(podman exec --user gateway-admin "$CONTAINER_NAME" podman info --format '{{.Host.Security.Rootless}}')" == false ]] || \
        fail 'Cockpit Podman socket health check did not reach rootful Podman.'

    ssh_bind_address=$(jq -r '.gateway.ssh_bind_address // .gateway.bind_address' "$config_path")
    cockpit_bind_address=$(jq -r '.gateway.cockpit_bind_address // .gateway.bind_address' "$config_path")
    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    if [[ "$ssh_bind_address" == 0.0.0.0 ]]; then ssh_bind_address=127.0.0.1; fi
    if [[ "$cockpit_bind_address" == 0.0.0.0 ]]; then cockpit_bind_address=127.0.0.1; fi
    ssh-keyscan -T 5 -p "$ssh_port" "$ssh_bind_address" >/dev/null 2>&1 || fail 'SSH readiness check failed.'
    curl --silent --show-error --fail --insecure --max-time 5 \
        "https://$cockpit_bind_address:$cockpit_port/" >/dev/null || fail 'Cockpit HTTPS readiness check failed.'

    while IFS=' ' read -r expected_address dns_name; do
        [[ -n "$expected_address" && "$expected_address" != \#* ]] || continue
        resolved=$(podman exec "$CONTAINER_NAME" getent hosts "$dns_name" | awk 'NR == 1 { print $1 }')
        [[ "$resolved" == "$expected_address" ]] || fail "DNS health check returned '$resolved' for '$dns_name'; expected '$expected_address'."
    done < "$dns_file"
}

debug_gateway_failure() {
    local container_status=0 container_running

    printf '[gateway] Podman state for %s:\n' "$CONTAINER_NAME" >&2
    if ! podman ps -a --filter "name=$CONTAINER_NAME" \
        --format '{{.ID}} {{.Names}} {{.Status}} {{.Image}}' >&2; then
        printf '[gateway] ERROR: Podman could not list containers during diagnostics.\n' >&2
    fi
    podman container exists "$CONTAINER_NAME" >/dev/null 2>&1 || container_status=$?
    case "$container_status" in
        0)
            if ! podman inspect \
                --format '{{.State.Status}} exit_code={{.State.ExitCode}} error={{.State.Error}} image={{.Image}}' \
                "$CONTAINER_NAME" >&2; then
                printf '[gateway] ERROR: Podman could not inspect %s.\n' "$CONTAINER_NAME" >&2
            fi
            if ! podman logs --tail 100 "$CONTAINER_NAME" >&2; then
                printf '[gateway] ERROR: Podman could not read logs for %s.\n' "$CONTAINER_NAME" >&2
            fi
            container_running=$(podman inspect --format '{{.State.Running}}' "$CONTAINER_NAME") || \
                container_running=false
            if [[ "$container_running" == true ]]; then
                if ! podman exec "$CONTAINER_NAME" ls -la /run/gateway >&2; then
                    printf '[gateway] ERROR: Podman could not inspect /run/gateway.\n' >&2
                fi
                if ! podman exec "$CONTAINER_NAME" /usr/sbin/sshd -t \
                    -f /run/gateway/sshd_config >&2; then
                    printf '[gateway] ERROR: OpenSSH config is unavailable or invalid inside the container.\n' >&2
                fi
                printf '[gateway] Interactive access: podman exec -it %s /bin/bash\n' \
                    "$CONTAINER_NAME" >&2
            else
                printf '[gateway] Container is stopped but retained; inspect with podman logs and podman inspect.\n' >&2
                printf '[gateway] To retry startup manually: podman start %s\n' "$CONTAINER_NAME" >&2
            fi
            ;;
        1)
            printf '[gateway] Podman no longer has container %s; use the systemd journal for its last startup logs.\n' \
                "$CONTAINER_NAME" >&2
            ;;
        *)
            printf '[gateway] ERROR: Podman could not determine whether container %s exists (status %s).\n' \
                "$CONTAINER_NAME" "$container_status" >&2
            ;;
    esac
    if command -v journalctl >/dev/null 2>&1; then
        if ! journalctl -u "$UNIT_NAME" -n 100 --no-pager >&2; then
            printf '[gateway] ERROR: Could not read the %s journal.\n' "$UNIT_NAME" >&2
        fi
    else
        printf '[gateway] ERROR: journalctl is unavailable; inspect systemd logs manually.\n' >&2
    fi
}
# ---------------------------------- #

wait_for_gateway_health() {
    local config_path=$1 dns_file=$2 timeout_seconds interval_seconds
    local start_seconds=$SECONDS attempt_count=0 attempt_output last_output='' unit_state=''

    timeout_seconds=$(jq -r '.gateway.startup_readiness.timeout_seconds // 60' "$config_path")
    interval_seconds=$(jq -r '.gateway.startup_readiness.interval_seconds // 2' "$config_path")
    while (( attempt_count == 0 || SECONDS - start_seconds < timeout_seconds )); do
        attempt_count=$((attempt_count + 1))
        if attempt_output=$(
            trap - EXIT
            check_gateway_health_once "$config_path" "$dns_file" 2>&1
        ); then
            [[ -z "$attempt_output" ]] || printf '%s\n' "$attempt_output"
            if (( attempt_count > 1 )); then
                printf '[gateway] Health checks passed after %s attempts.\n' "$attempt_count"
            fi
            return 0
        fi

        last_output=$attempt_output
        if [[ "$attempt_output" == *"Gateway unit is not active:"* ]]; then
            unit_state=$(systemctl show --property=ActiveState --value "$UNIT_NAME" 2>/dev/null) || \
                unit_state=unknown
            case "$unit_state" in
                activating|reloading) ;;
                *)
                printf '%s\n' "$attempt_output" >&2
                printf '[gateway] Gateway unit entered state %s; stopping readiness retries.\n' \
                    "$unit_state" >&2
                debug_gateway_failure
                if (( DEBUG_PRESERVE_ACTIVE == 1 )); then
                    PRESERVE_FAILED_STATE=1
                    fail 'Gateway failed during startup; deployment state is preserved for Podman debugging.'
                fi
                fail 'Gateway unit became inactive; deployment rollback will restore prior state.'
                return 1
                ;;
            esac
        fi
        if (( attempt_count == 1 )); then
            printf '[gateway] Waiting for readiness (timeout %ss, interval %ss).\n' \
                "$timeout_seconds" "$interval_seconds"
        fi
        (( SECONDS - start_seconds < timeout_seconds )) || break
        sleep "$interval_seconds"
    done

    [[ -z "$last_output" ]] || printf '%s\n' "$last_output" >&2
    debug_gateway_failure
    if (( DEBUG_PRESERVE_ACTIVE == 1 )); then
        PRESERVE_FAILED_STATE=1
        fail "Gateway did not become healthy within ${timeout_seconds}s after ${attempt_count} attempts; state is preserved for debugging."
    fi
    fail "Gateway did not become healthy within ${timeout_seconds}s after ${attempt_count} attempts; deployment rollback will restore prior state."
}
# ---------------------------------- #

cleanup_after_apply() {
    local status=$?
    trap - EXIT

    if (( status != 0 && APPLY_MUTATING == 1 )); then
        if (( WIREGUARD_KERNEL_LOAD_ATTEMPTED == 1 )); then
            printf '[gateway] WireGuard kernel module remains loaded; it may be shared by other host workloads.\n' >&2
        fi
        if (( WIREGUARD_KEY_CREATED == 1 )); then
            printf '[gateway] Retained the WireGuard server key at %s; reuse it on retry to preserve client profiles.\n' \
                "$WIREGUARD_KEY_PATH" >&2
        fi
        if (( PRESERVE_FAILED_STATE == 1 )); then
            printf '[gateway] Failed state is preserved for Podman debugging; automatic rollback was skipped.\n' >&2
            if (( DEBUG_DROPIN_INSTALLED == 1 )); then
                printf '[gateway] Debug Quadlet remains at %s; systemd override remains at %s.\n' \
                    "$QUADLET_FILE" "$GATEWAY_DEBUG_DROPIN" >&2
            fi
            printf '[gateway] Inspect with: podman ps -a --filter name=%s; podman inspect %s; podman logs %s\n' \
                "$CONTAINER_NAME" "$CONTAINER_NAME" "$CONTAINER_NAME" >&2
            printf '[gateway] A retry reuses retained debug state and removes it after successful health checks.\n' >&2
        elif (( ROLLBACK_READY == 1 )); then
            rollback_deployment
        else
            printf '[gateway] Apply stopped before activation; additive directories, host keys, networks, or image layers may remain. No data or secrets were removed.\n' >&2
        fi
    fi
    [[ -z "$STAGED_CONFIG" ]] || rm -f -- "$STAGED_CONFIG"
    [[ -z "$STAGED_INPUTS" ]] || rm -f -- "$STAGED_INPUTS"
    [[ -z "$STAGED_DNS" ]] || rm -f -- "$STAGED_DNS"
    [[ -z "$STAGED_QUADLET" ]] || rm -f -- "$STAGED_QUADLET"
    [[ -z "$STAGED_DEBUG_QUADLET" ]] || rm -f -- "$STAGED_DEBUG_QUADLET"
    [[ -z "$STAGED_DEBUG_DROPIN" ]] || rm -f -- "$STAGED_DEBUG_DROPIN"
    if (( DEBUG_DROPIN_DIR_CREATED == 1 && DEBUG_DROPIN_INSTALLED == 0 )); then
        rmdir -- "$GATEWAY_DEBUG_DROPIN_DIR" || \
            printf '[gateway] ERROR: could not remove empty debug directory %s.\n' \
                "$GATEWAY_DEBUG_DROPIN_DIR" >&2
    fi
    if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
        rm -f -- "$BACKUP_DIR/quadlet" "$BACKUP_DIR/quadlet.absent" \
            "$BACKUP_DIR/config" "$BACKUP_DIR/config.absent" \
            "$BACKUP_DIR/inputs" "$BACKUP_DIR/inputs.absent" \
            "$BACKUP_DIR/dns" "$BACKUP_DIR/dns.absent"
        rmdir -- "$BACKUP_DIR" 2>/dev/null || true
    fi
    exit "$status"
}
# ---------------------------------- #

# Start or restart a generated Quadlet unit without enabling the transient unit.
# Arguments: 1 if the service was active before apply, otherwise 0.
# Output: none. Activation failures are reported to stderr.
activate_gateway_service() {
    local service_was_active=$1

    ACTIVATION_ATTEMPTED=1
    if [[ "$service_was_active" == 1 ]]; then
        if ! systemctl restart "$UNIT_NAME"; then
            debug_gateway_failure
            fail "Could not restart $UNIT_NAME with the new configuration."
        fi
    else
        if ! systemctl start "$UNIT_NAME"; then
            debug_gateway_failure
            fail "Could not start $UNIT_NAME."
        fi
    fi
}
# ---------------------------------- #

# Remove only inactive remote-access routes with the exact managed tag and next hop.
# Arguments: validated host configuration path. Reads host routes; mutates only matching routes.
# Output: none. Reports inspection or deletion failures to stderr and exits nonzero.
remove_managed_remote_access_return_routes() {
    local config_path=$1 transport enabled pool observed_routes
    local route_gateway

    route_gateway=$(jq -r '
        [.networks[] | select(has("gateway_address"))] |
        sort_by([
            (.subnet | split("/")[0] | split(".") | map(tonumber)),
            (.subnet | split("/")[1] | tonumber),
            .name
        ]) | .[0].gateway_address // empty
    ' "$config_path")
    [[ -n "$route_gateway" ]] || return 0

    for transport in openvpn ssh_tun wireguard; do
        if [[ "$transport" == openvpn ]]; then
            enabled=$(jq -r '.gateway.remote_access.openvpn.enabled // false' "$config_path")
            pool=$(jq -r '.gateway.remote_access.openvpn.client_pool // empty' "$config_path")
        elif [[ "$transport" == wireguard ]]; then
            enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$config_path")
            pool=$(jq -r '.gateway.remote_access.wireguard.address_pool // empty' "$config_path")
        else
            enabled=$(jq -r '.gateway.remote_access.ssh_tun.enabled // false' "$config_path")
            pool=$(jq -r '.gateway.remote_access.ssh_tun.address_pool // empty' "$config_path")
        fi
        [[ "$enabled" == false && -n "$pool" ]] || continue
        observed_routes=$(ip -j -4 route show table all "$pool") || \
            fail "Could not inspect the $transport host return route."
        if jq -e \
            --arg destination "$pool" \
            --arg gateway "$route_gateway" \
            'any(.[]; .dst == $destination and .gateway == $gateway and
                ((.protocol | tostring) == "186" or (.protocol | tostring) == "bgp") and
                (.table == null or .table == "main" or .table == 254) and
                (.type == null or .type == "unicast") and
                (.multipath == null or .multipath == false) and
                ((.nexthops // []) | length == 0))' \
            <<< "$observed_routes" >/dev/null; then
            ip -4 route del "$pool" via "$route_gateway" proto 186 || \
                fail "Could not remove the owned $transport host return route."
        fi
    done
}
# ---------------------------------- #

# Run one preflight CLI stage.
# Arguments: host-preflight arguments. Returns the child process status.
run_preflight_command() {
    "$PREFLIGHT_SCRIPT" "$@"
}
# ---------------------------------- #

# Serialize Gateway mutations and sequential preflight/deployment pipelines.
# Arguments: none. Creates and holds GATEWAY_CONFIG_LOCK until process exit.
acquire_gateway_config_lock() {
    command -v flock >/dev/null 2>&1 || fail 'flock is required to serialize Gateway configuration changes.'
    exec {GATEWAY_CONFIG_LOCK_FD}>"$GATEWAY_CONFIG_LOCK" || fail 'Could not open the Gateway configuration lock.'
    flock -x "$GATEWAY_CONFIG_LOCK_FD" || fail 'Could not lock Gateway configuration for apply.'
}
# ---------------------------------- #

# Reuse only a retained debug override owned by this deployment.
# Arguments: optional debug override path. Reads that path and changes no files.
ensure_no_stale_gateway_debug_state() {
    local debug_dropin=${1:-$GATEWAY_DEBUG_DROPIN}

    if [[ -e "$debug_dropin" || -L "$debug_dropin" ]]; then
        if gateway_debug_dropin_is_managed "$debug_dropin"; then
            printf '[gateway] Reusing retained debug state from %s.\n' "$debug_dropin"
            return 0
        fi
        fail "Gateway debug-preserve path is not owned by deployment: $debug_dropin"
    fi
}
# ---------------------------------- #

# Apply a configuration after the caller acquires the deployment lock.
# Arguments: host config path. This function does not run preflight checks.
apply_deployment_locked() {
    local config_path=$1 previous_container_image='' previous_tagged_image=''
    local current_image_id='' desired_image_id='' unit_changed=0 config_changed=0 inputs_changed=0 dns_changed=0
    local restart_needed=0 network

    ensure_no_stale_gateway_debug_state
    APPLY_MUTATING=1
    trap cleanup_after_apply EXIT
    ensure_wireguard_kernel_module "$config_path"

    if systemctl is-active --quiet "$UNIT_NAME"; then SERVICE_WAS_ACTIVE=1; fi
    if systemctl is-active --quiet podman.socket; then SOCKET_WAS_ACTIVE=1; fi
    if podman container exists "$CONTAINER_NAME" >/dev/null 2>&1; then
        previous_container_image=$(podman inspect --format '{{.Image}}' "$CONTAINER_NAME")
    fi
    if podman image exists "$IMAGE"; then
        previous_tagged_image=$(podman image inspect --format '{{.Id}}' "$IMAGE")
    fi
    PREVIOUS_IMAGE_ID=${previous_container_image:-$previous_tagged_image}

    prepare_state_directories
    podman build --pull=always --file "$GATEWAY_CONTAINERFILE" \
        --tag "$IMAGE" "$GATEWAY_BUILD_CONTEXT" || fail 'Debian gateway image build failed.'
    desired_image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE") || fail 'Cannot inspect the built gateway image.'
    ensure_wireguard_server_key "$config_path"
    ensure_host_keys
    stage_managed_files "$config_path"
    validate_quadlet_candidate "$STAGED_QUADLET"
    test_dns_candidate "$STAGED_DNS"
    stage_debug_gateway_files "$config_path"

    BACKUP_DIR=$(mktemp -d /var/tmp/gateway-backup.XXXXXX)
    snapshot_file "$QUADLET_FILE" quadlet
    snapshot_file "$GENERATED_CONFIG" config
    snapshot_file "$GENERATED_INPUTS" inputs
    snapshot_file "$DNS_HOSTS_FILE" dns
    ROLLBACK_READY=1

    create_declared_networks "$config_path"
    if install_atomic_if_changed "$STAGED_CONFIG" "$GENERATED_CONFIG" 0644; then config_changed=1; fi
    if install_atomic_if_changed "$STAGED_INPUTS" "$GENERATED_INPUTS" 0644; then inputs_changed=1; fi
    if install_atomic_if_changed "$STAGED_DNS" "$DNS_HOSTS_FILE" 0644; then dns_changed=1; fi
    if install_atomic_if_changed "$STAGED_QUADLET" "$QUADLET_FILE" 0644; then unit_changed=1; fi

    if [[ -n "$previous_container_image" && "$previous_container_image" != "$desired_image_id" ]]; then
        restart_needed=1
    fi
    if (( unit_changed == 1 || config_changed == 1 || inputs_changed == 1 )); then restart_needed=1; fi
    if [[ "$SERVICE_WAS_ACTIVE" != 1 ]]; then restart_needed=1; fi

    if (( restart_needed == 1 )); then
        if install_atomic_if_changed "$STAGED_DEBUG_QUADLET" "$QUADLET_FILE" 0644; then
            unit_changed=1
        fi
        install_gateway_debug_dropin
        PRESERVE_FAILED_STATE=1
        systemctl daemon-reload || fail 'systemd failed to reload the Gateway debug-preserve unit.'
        activate_gateway_service "$SERVICE_WAS_ACTIVE"
    elif (( unit_changed == 1 )); then
        systemctl daemon-reload || fail 'systemd failed to reload the generated Quadlet unit.'
    fi
    remove_managed_remote_access_return_routes "$config_path"
    if (( dns_changed == 1 && restart_needed == 0 )); then
        ACTIVATION_ATTEMPTED=1
        podman exec "$CONTAINER_NAME" pkill -HUP dnsmasq || fail 'Could not reload DNSMasq after DNS records changed.'
    fi

    wait_for_gateway_health "$config_path" "$DNS_HOSTS_FILE"
    if (( DEBUG_PRESERVE_ACTIVE == 1 )); then
        normalize_gateway_debug_unit
    fi
    APPLY_MUTATING=0
    ROLLBACK_READY=0

    printf '[gateway] Deployment ready.\n'
    if (( unit_changed || config_changed || dns_changed || restart_needed )); then
        printf '[gateway] Changed: '
        (( unit_changed )) && printf 'Quadlet '
        (( config_changed )) && printf 'configuration '
        (( inputs_changed )) && printf 'runtime inputs '
        (( dns_changed )) && printf 'DNS '
        (( restart_needed )) && printf 'gateway service '
        printf '\n'
    else
        printf '[gateway] No generated files or service restart needed.\n'
    fi
    if (( ${#NETWORKS_CREATED[@]} > 0 )); then
        printf '[gateway] Created application networks: %s\n' "${NETWORKS_CREATED[*]}"
    fi
    printf '[gateway] Service status: %s\n' "$(systemctl is-active "$UNIT_NAME")"
    printf '[gateway] Recovery: journalctl -u %s; rerun --check before another apply.\n' "$UNIT_NAME"
}
# ---------------------------------- #

# Apply a config after the operator has run a successful --check.
# Arguments: host config path. Acquires the deployment lock but runs no preflight.
apply_deployment() {
    local config_path=$1

    acquire_gateway_config_lock
    printf '[gateway] Assuming --check passed; standalone --apply skips preflight.\n'
    apply_deployment_locked "$config_path"
}
# ---------------------------------- #

# Validate, preflight, and apply one config while holding the deployment lock for check and apply.
# Arguments: host config path. Stops at the first failed stage.
deploy_sequentially() {
    local config_path=$1

    run_preflight_command --validate-gateway-config "$config_path" || return
    acquire_gateway_config_lock
    run_preflight_command --check-gateway "$config_path" || return
    apply_deployment_locked "$config_path"
}
# ---------------------------------- #

main() {
    [[ $# -ge 1 ]] || { usage >&2; exit 2; }

    case "$1" in
        --validate-config)
            shift
            [[ $# -le 1 ]] || { usage >&2; exit 2; }
            "$PREFLIGHT_SCRIPT" --validate-gateway-config "${1:-$DEFAULT_CONFIG}"
            ;;
        --check)
            shift
            [[ $# -le 1 ]] || { usage >&2; exit 2; }
            "$PREFLIGHT_SCRIPT" --check-gateway "${1:-$DEFAULT_CONFIG}"
            ;;
        --apply)
            shift
            [[ $# -le 1 ]] || { usage >&2; exit 2; }
            apply_deployment "${1:-$DEFAULT_CONFIG}"
            ;;
        --help|-h)
            usage
            ;;
        *)
            if [[ $# -eq 1 && "$1" != -* ]]; then
                deploy_sequentially "$1"
            else
                usage >&2
                if [[ "$1" == -* ]]; then
                    fail "Unknown option: $1"
                fi
                fail 'Sequential deployment accepts exactly one config filename.'
            fi
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi