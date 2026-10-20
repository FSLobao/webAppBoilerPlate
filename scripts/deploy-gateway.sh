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
PREVIOUS_IMAGE_ID=''
SERVICE_WAS_ACTIVE=0
SERVICE_WAS_ENABLED=0
SOCKET_WAS_ACTIVE=0
ACTIVATION_ATTEMPTED=0
NETWORKS_CREATED=()

usage() {
    printf 'Usage: %s --validate-config|--check|--apply [host_config.json]\n' "${0##*/}"
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

render_quadlet_candidate() {
    local config_path=$1 output_path=$2
    local authorized_keys_path ssh_bind_address cockpit_bind_address ssh_port cockpit_port
    local network_lines published_lines openvpn_volume='' openvpn_runtime=''
    local ssh_tun_volume='' ssh_tun_runtime=''
    local openvpn_host_route='' ssh_tun_host_route=''
    local wireguard_volume='' wireguard_peers_volume='' wireguard_runtime=''
    local wireguard_host_route='' wireguard_enabled wireguard_key_path
    local wireguard_bind_address wireguard_port wireguard_pool
    local openvpn_enabled ssh_tun_enabled profile_path client_pool route_gateway
    local ssh_tun_pool ssh_tun_keys_path
    local template

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
            openvpn_host_route=$(printf \
                'ExecStartPost=/usr/sbin/ip -4 route add %s via %s proto 186\nExecStopPost=-/usr/sbin/ip -4 route del %s via %s proto 186' \
                "$client_pool" "$route_gateway" "$client_pool" "$route_gateway")
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
        ssh_tun_host_route=$(printf \
            'ExecStartPost=/usr/sbin/ip -4 route add %s via %s proto 186\nExecStopPost=-/usr/sbin/ip -4 route del %s via %s proto 186' \
            "$ssh_tun_pool" "$route_gateway" "$ssh_tun_pool" "$route_gateway")
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
        published_lines+=$(printf '\nPublishPort=%s:%s:%s/udp' \
            "$wireguard_bind_address" "$wireguard_port" "$wireguard_port")
        wireguard_host_route=$(printf \
            'ExecStartPost=/usr/sbin/ip -4 route add %s via %s proto 186\nExecStopPost=-/usr/sbin/ip -4 route del %s via %s proto 186' \
            "$wireguard_pool" "$route_gateway" "$wireguard_pool" "$route_gateway")
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
    template=${template//@@WIREGUARD_HOST_ROUTE@@/$wireguard_host_route}
    template=${template//@@NETWORKS@@/$network_lines}
    template=${template//@@PUBLISHED_PORTS@@/$published_lines}
    [[ "$template" != *@@* ]] || fail 'Quadlet template contains an unexpanded placeholder.'
    printf '%s\n' "$template" > "$output_path"
    chmod 0644 "$output_path"
}

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
    if [[ "$SERVICE_WAS_ENABLED" == 1 ]]; then
        systemctl enable "$UNIT_NAME" >/dev/null 2>&1 || rollback_failed=1
    else
        systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true
    fi
    if [[ "$SERVICE_WAS_ACTIVE" == 1 ]]; then
        systemctl start "$UNIT_NAME" >/dev/null 2>&1 || {
            printf '[gateway] ERROR: previous gateway service did not recover.\n' >&2
            rollback_failed=1
        }
    elif [[ "$ACTIVATION_ATTEMPTED" == 1 ]]; then
        systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    fi

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

check_gateway_health() {
    local config_path=$1 dns_file=$2 ssh_bind_address cockpit_bind_address ssh_port cockpit_port expected_networks attached_networks
    local resolved expected_address dns_name network actual_address

    systemctl is-active --quiet "$UNIT_NAME" || fail "Gateway unit is not active: $UNIT_NAME"
    [[ "$(podman inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" == true ]] || \
        fail "Gateway container is not running: $CONTAINER_NAME"

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

cleanup_after_apply() {
    local status=$?
    trap - EXIT

    if (( status != 0 && APPLY_MUTATING == 1 )); then
        if (( ROLLBACK_READY == 1 )); then
            rollback_deployment
        else
            printf '[gateway] Apply stopped before activation; additive directories, host keys, networks, or image layers may remain. No data or secrets were removed.\n' >&2
        fi
    fi
    [[ -z "$STAGED_CONFIG" ]] || rm -f -- "$STAGED_CONFIG"
    [[ -z "$STAGED_INPUTS" ]] || rm -f -- "$STAGED_INPUTS"
    [[ -z "$STAGED_DNS" ]] || rm -f -- "$STAGED_DNS"
    [[ -z "$STAGED_QUADLET" ]] || rm -f -- "$STAGED_QUADLET"
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
                ((.protocol | tostring) == "186") and
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

apply_deployment() {
    local config_path=$1 previous_container_image='' previous_tagged_image=''
    local current_image_id='' desired_image_id='' unit_changed=0 config_changed=0 inputs_changed=0 dns_changed=0
    local restart_needed=0 network lock_fd

    command -v flock >/dev/null 2>&1 || fail 'flock is required to serialize Gateway configuration changes.'
    exec {lock_fd}>"$GATEWAY_CONFIG_LOCK" || fail 'Could not open the Gateway configuration lock.'
    flock -x "$lock_fd" || fail 'Could not lock Gateway configuration for apply.'
    "$PREFLIGHT_SCRIPT" --check-gateway "$config_path"
    APPLY_MUTATING=1
    trap cleanup_after_apply EXIT

    if systemctl is-active --quiet "$UNIT_NAME"; then SERVICE_WAS_ACTIVE=1; fi
    if systemctl is-enabled --quiet "$UNIT_NAME"; then SERVICE_WAS_ENABLED=1; fi
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
    ensure_host_keys
    stage_managed_files "$config_path"
    validate_quadlet_candidate "$STAGED_QUADLET"
    test_dns_candidate "$STAGED_DNS"

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

    if (( unit_changed == 1 )); then
        systemctl daemon-reload || fail 'systemd failed to reload the generated Quadlet unit.'
    fi
    if (( restart_needed == 1 )); then
        ACTIVATION_ATTEMPTED=1
        if [[ "$SERVICE_WAS_ACTIVE" == 1 ]]; then
            systemctl enable "$UNIT_NAME" >/dev/null || fail "Could not enable $UNIT_NAME for reboot recovery."
            systemctl restart "$UNIT_NAME" || fail "Could not restart $UNIT_NAME with the new configuration."
        else
            systemctl enable --now "$UNIT_NAME" || fail "Could not enable and start $UNIT_NAME."
        fi
    elif (( SERVICE_WAS_ENABLED != 1 )); then
        ACTIVATION_ATTEMPTED=1
        systemctl enable "$UNIT_NAME" || fail "Could not enable $UNIT_NAME for reboot recovery."
    fi
    remove_managed_remote_access_return_routes "$config_path"
    if (( dns_changed == 1 && restart_needed == 0 )); then
        ACTIVATION_ATTEMPTED=1
        podman exec "$CONTAINER_NAME" pkill -HUP dnsmasq || fail 'Could not reload DNSMasq after DNS records changed.'
    fi

    check_gateway_health "$config_path" "$DNS_HOSTS_FILE"
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
            usage >&2
            fail "Unknown option: $1"
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi