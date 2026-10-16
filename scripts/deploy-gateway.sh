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
APPLICATION_CONTAINERS_STARTED=()

usage() {
    printf 'Usage: %s --validate-config|--check|--apply [host_config.json]\n' "${0##*/}"
}
prepare_state_directories() {
    install -d -o root -g root -m 0755 "$STATE_DIR" "$STATE_DIR/generated" "$STATE_DIR/dns"
    install -d -o root -g root -m 0700 "$HOST_KEYS_DIR"
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

generate_dns_candidate() {
    local config_path=$1 output_path=$2

    printf '# Managed by scripts/deploy-gateway.sh\n' > "$output_path"
    run_python_module scripts.gateway.dns_records "$config_path" >> "$output_path"
    chmod 0644 "$output_path"
}

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
    local network_lines published_lines template

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
    template=$(<"$UNIT_TEMPLATE")
    template=${template//@@CONFIG_FILE@@/$GENERATED_CONFIG}
    template=${template//@@AUTHORIZED_KEYS@@/$authorized_keys_path}
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

# Ask before starting stopped DNS targets and record starts for failure recovery.
ensure_dns_targets_running() {
    local config_path=$1 container running answer
    local -A checked_containers=()

    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        [[ -n "${checked_containers[$container]+x}" ]] && continue
        checked_containers["$container"]=1

        running=$(podman inspect --format '{{.State.Running}}' "$container") || \
            fail "Cannot inspect configured DNS target container '$container'."
        [[ "$running" == true ]] && continue
        [[ -t 0 ]] || fail "DNS target container '$container' is stopped; rerun --apply in a terminal to choose whether to start it."
        if ! read -r -p "DNS target container '$container' is stopped. Start it? [y/N] " answer; then
            fail "Could not read confirmation for stopped DNS target container '$container'."
        fi
        case "$answer" in
            y|Y|yes|YES|Yes)
                APPLICATION_CONTAINERS_STARTED+=("$container")
                podman start "$container" >/dev/null || fail "Could not start DNS target container '$container'."
                ;;
            *) fail "Stopped DNS target container '$container' was not started; apply cancelled." ;;
        esac
    done < <(jq -r '[.dns_records[].container] | unique[]' "$config_path")
}
# ---------------------------------- #

# Stop application containers started by this apply when deployment fails.
restore_started_application_containers() {
    local container running

    for container in "${APPLICATION_CONTAINERS_STARTED[@]}"; do
        if ! podman container exists "$container" >/dev/null 2>&1; then
            printf '[gateway] ERROR: started application container disappeared before recovery: %s\n' "$container" >&2
            continue
        fi
        running=$(podman inspect --format '{{.State.Running}}' "$container") || {
            printf '[gateway] ERROR: cannot inspect started application container during recovery: %s\n' "$container" >&2
            continue
        }
        [[ "$running" == true ]] || continue
        podman stop "$container" >/dev/null || \
            printf '[gateway] ERROR: could not restore stopped state for application container: %s\n' "$container" >&2
    done
}
# ---------------------------------- #

cleanup_after_apply() {
    local status=$?
    trap - EXIT

    if (( status != 0 && APPLY_MUTATING == 1 )); then
        if (( ROLLBACK_READY == 1 )); then
            rollback_deployment
        else
            printf '[gateway] Apply stopped before activation; additive directories, host keys, networks, or image layers may remain. No data or secrets were removed.\n' >&2
        fi
        restore_started_application_containers
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

apply_deployment() {
    local config_path=$1 previous_container_image='' previous_tagged_image=''
    local current_image_id='' desired_image_id='' unit_changed=0 config_changed=0 inputs_changed=0 dns_changed=0
    local restart_needed=0 network

    "$PREFLIGHT_SCRIPT" --check-gateway "$config_path"
    APPLY_MUTATING=1
    trap cleanup_after_apply EXIT
    ensure_dns_targets_running "$config_path"
    if (( ${#APPLICATION_CONTAINERS_STARTED[@]} > 0 )); then
        "$PREFLIGHT_SCRIPT" --check-gateway "$config_path"
    fi

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
    if (( ${#APPLICATION_CONTAINERS_STARTED[@]} > 0 )); then
        printf '[gateway] Started application containers with operator approval: %s\n' "${APPLICATION_CONTAINERS_STARTED[*]}"
    fi
    printf '[gateway] Service status: %s\n' "$(systemctl is-active "$UNIT_NAME")"
    printf '[gateway] Recovery: journalctl -u %s; rerun --check before another apply.\n' "$UNIT_NAME"
}

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