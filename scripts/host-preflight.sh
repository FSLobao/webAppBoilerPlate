#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    set -Eeuo pipefail
fi

readonly PREFLIGHT_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$PREFLIGHT_SCRIPT_DIR/.." && pwd -P)"
readonly DEFAULT_CONFIG="$REPO_ROOT/config/host_config.json"
readonly GATEWAY_BUILD_CONTEXT="$REPO_ROOT/gateway/development"
readonly GATEWAY_CONTAINERFILE="$GATEWAY_BUILD_CONTEXT/Containerfile"
readonly GATEWAY_STARTUP_SCRIPT="$GATEWAY_BUILD_CONTEXT/startup.sh"
readonly UNIT_TEMPLATE="$REPO_ROOT/deploy/quadlet/gateway.container"
readonly QUADLET_DIR=/etc/containers/systemd
readonly PODMAN_SOCKET=/run/podman/podman.sock
readonly COCKPIT_PASSWORD_FILE=/etc/gateway/cockpit-password
readonly COCKPIT_CERT_FILE=/etc/gateway/tls/gateway.cert
readonly COCKPIT_KEY_FILE=/etc/gateway/tls/gateway.key
readonly STATE_DIR=/var/lib/gateway
readonly GENERATED_CONFIG="$STATE_DIR/generated/config.json"
readonly GENERATED_INPUTS="$STATE_DIR/generated/inputs.json"
readonly DNS_HOSTS_FILE="$STATE_DIR/dns/hosts"
readonly HOST_KEYS_DIR="$STATE_DIR/ssh_host_keys"
readonly QUADLET_FILE="$QUADLET_DIR/gateway.container"
readonly OWNER_MARKER="$STATE_DIR/.managed-by-gateway"
readonly IMAGE=localhost/gateway:1
readonly CONTAINER_NAME=gateway
readonly UNIT_NAME=gateway.service

# Report an operator-facing failure and exit non-zero.
fail() {
    printf '[host-preflight] ERROR: %s\n' "$*" >&2
    exit 1
}
# ---------------------------------- #

# Run a repository Python helper with the repository root on its import path.
run_python_module() {
    local module=$1
    shift
    PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -m "$module" "$@"
}
# ---------------------------------- #

# Validate configuration structure and IPv4 declarations without host changes.
validate_config() {
    local config_path=${1:-$DEFAULT_CONFIG}

    command -v jq >/dev/null 2>&1 || fail 'jq is required for configuration validation.'
    command -v python3 >/dev/null 2>&1 || fail 'python3 is required to validate IPv4 addresses and CIDR overlap.'
    [[ -f "$config_path" && -r "$config_path" ]] || fail "Configuration file is missing or unreadable: $config_path"
    jq empty "$config_path" >/dev/null 2>&1 || fail "Configuration is not valid JSON: $config_path"

    local schema_version
    schema_version=$(jq -r '.schema_version // "missing"' "$config_path")
    [[ "$schema_version" == 1 ]] || fail "Unsupported schema_version '$schema_version'; supported version is 1."

    jq -e '
        def object_with_keys($expected):
            type == "object" and (keys | sort) == ($expected | sort);
        def object_with_allowed_keys($required; $optional):
            . as $object |
            ($object | type == "object") and
            ((($object | keys) - ($required + $optional)) | length == 0) and
            all($required[]; . as $key | $object | has($key));
        def podman_name:
            type == "string" and test("^[A-Za-z0-9][A-Za-z0-9_.-]*$");
        def dns_name:
            type == "string" and length <= 253 and endswith(".dev.internal") and
            (split(".") as $labels |
                ($labels | length) >= 4 and
                all($labels[]; length > 0 and length <= 63 and
                    test("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")));
        def port:
            type == "number" and floor == . and . >= 1 and . <= 65535;
        def route_prefix:
            type == "string" and
            test("^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$");
        def api_prefix($prefix):
            type == "string" and
            startswith($prefix + "/") and endswith("/") and
            test("^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/$");
        def routes_disjoint($routes):
            all($routes[]; . as $route |
                all($routes[]; . as $other |
                    ($route.prefix == $other.prefix) or
                    (((($route.prefix | startswith($other.prefix + "/")) or
                       ($other.prefix | startswith($route.prefix + "/")))) | not)
                )
            );
        (. as $config |
        object_with_allowed_keys(
            ["schema_version", "networks"];
            ["gateway", "application_gateway", "containers", "dns_records"]
        ) and
        $config.schema_version == 1 and
        ($config.networks | type == "array") and
        all($config.networks[];
            object_with_allowed_keys(["name", "subnet"]; ["gateway_address"]) and
            (.name | podman_name) and (.subnet | type == "string") and
            (if has("gateway_address") then (.gateway_address | type == "string") else true end)) and
        ([$config.networks[].name] | length == (unique | length)) and
        (($config.containers // []) | type == "array") and
        all(($config.containers // [])[];
            object_with_keys(["name", "networks"]) and
            (.name | podman_name) and
            (.networks | type == "array" and length > 0 and
                all(.[]; podman_name) and length == (unique | length))) and
        ([($config.containers // [])[] | .name] | length == (unique | length)) and
        (if ($config | has("application_gateway")) then
            ($config.application_gateway as $application_gateway |
                ($application_gateway | object_with_keys(
                    ["enabled", "listen_address", "http_port", "routes"]
                )) and
                ($application_gateway.enabled | type == "boolean") and
                ($application_gateway.listen_address | type == "string" and length > 0) and
                ($application_gateway.http_port | port) and
                ($application_gateway.routes | type == "array") and
                (if $application_gateway.enabled then
                    ($application_gateway.routes | length > 0)
                else true end) and
                all($application_gateway.routes[];
                    object_with_keys([
                        "prefix", "frontend", "frontend_port",
                        "api_prefix", "backend", "backend_port"
                    ]) and
                    (.prefix | route_prefix) and
                    (.frontend | podman_name) and
                    (.frontend_port | port) and
                    (.backend | podman_name) and
                    (.backend_port | port) and
                    (. as $route | .api_prefix | api_prefix($route.prefix))
                ) and
                ([$application_gateway.routes[].prefix] | length == (unique | length)) and
                routes_disjoint($application_gateway.routes) and
                (if $application_gateway.enabled then
                    any(($config.containers // [])[]; .name == "nginx") and
                    all($application_gateway.routes[];
                        . as $route |
                        any(($config.containers // [])[]; .name == $route.frontend) and
                        any(($config.containers // [])[]; .name == $route.backend)
                    )
                else true end)
            )
        else true end) and
        (($config.dns_records // []) | type == "array") and
        all(($config.dns_records // [])[]; object_with_keys(["name", "container", "network"]) and
            (.name | dns_name) and (.container | podman_name) and (.network | podman_name)) and
        ([($config.dns_records // [])[] | .name] | length == (unique | length)) and
        ([$config.networks[].name] as $network_names |
            all(($config.containers // [])[]; . as $container |
                all($container.networks[]; . as $network | $network_names | index($network) != null)) and
            all(($config.dns_records // [])[]; .network as $network | $network_names | index($network) != null) and
            (if ($config | has("gateway")) then
                ($config.gateway |
                    object_with_allowed_keys(
                        ["name", "bind_address", "ssh_port", "cockpit_port", "authorized_keys_path"];
                        ["networks", "ssh_bind_address", "cockpit_bind_address"]
                    ) and
                    (.name | podman_name) and .name == "gateway" and
                    (.bind_address | type == "string" and length > 0) and
                    (if has("ssh_bind_address") then (.ssh_bind_address | type == "string" and length > 0) else true end) and
                    (if has("cockpit_bind_address") then (.cockpit_bind_address | type == "string" and length > 0) else true end) and
                    (.ssh_port | port) and
                    (.cockpit_port | port) and
                    .ssh_port != .cockpit_port and
                    (.authorized_keys_path | type == "string" and
                        test("^/[A-Za-z0-9_./-]+$") and
                        (split("/") | all(.[]; . != "." and . != ".."))) and
                    (if has("networks") then
                        (.networks | type == "array" and all(.[]; podman_name) and length == (unique | length))
                    else true end)) and
                (($config.gateway.networks // $network_names) as $gateway_networks |
                    all($gateway_networks[]; . as $network | $network_names | index($network) != null) and
                    all(($config.dns_records // [])[]; .network as $network | $gateway_networks | index($network) != null))
            else true end))
        )
    ' "$config_path" >/dev/null || fail 'Configuration violates schema version 1, contains duplicate names, or has invalid network/DNS declarations.'

    run_python_module scripts.gateway.config_validation "$config_path"
}
# ---------------------------------- #

# Check host prerequisites, secrets, generated state, ports, networks, and DNS targets without mutation.
check_gateway_host_preflight() {
    local config_path=${1:-$DEFAULT_CONFIG}
    local os_id os_version podman_version podman_rootless selinux_mode
    local authorized_keys_path ssh_port cockpit_port listener mode owner bind_address
    local ssh_bind_address cockpit_bind_address
    local source_asset
    local gateway_managed=0 host_private_key="$HOST_KEYS_DIR/ssh_host_ed25519_key"
    local host_public_key="$HOST_KEYS_DIR/ssh_host_ed25519_key.pub" certificate_public_key private_public_key
    local host_key_fingerprint previous_host_key_fingerprint

    [[ -d "$GATEWAY_BUILD_CONTEXT" && ! -L "$GATEWAY_BUILD_CONTEXT" ]] || \
        fail "Gateway image build context is missing or unsafe: $GATEWAY_BUILD_CONTEXT"
    for source_asset in "$GATEWAY_CONTAINERFILE" "$GATEWAY_STARTUP_SCRIPT" "$UNIT_TEMPLATE"; do
        [[ -f "$source_asset" && -r "$source_asset" && ! -L "$source_asset" ]] || \
            fail "Gateway deployment source asset is missing, unreadable, or unsafe: $source_asset"
    done
    [[ "$EUID" -eq 0 ]] || fail 'Run host preflight as root for rootful Podman checks.'
    [[ -r /etc/os-release ]] || fail 'Cannot identify the host operating system.'
    source /etc/os-release
    os_id=${ID:-unknown}
    os_version=${VERSION_ID:-unknown}
    run_python_module scripts.gateway.host_preflight host-platform "$os_id" "$os_version" || \
        fail "Host deployment requires RHEL 9.8; found $os_id $os_version."

    local tool path expected_mode
    for tool in podman systemctl ss ssh-keygen getenforce stat openssl curl ip install cmp; do
        command -v "$tool" >/dev/null 2>&1 || fail "Required host tool is missing: $tool"
    done
    [[ -d /run/systemd/system ]] || fail 'systemd is not running.'
    [[ -x /usr/lib/systemd/system-generators/podman-system-generator || \
        -x /usr/libexec/podman/quadlet ]] || fail 'The Podman Quadlet systemd generator is missing.'
    systemctl cat podman.socket >/dev/null 2>&1 || fail 'The rootful podman.socket systemd unit is missing.'

    podman_version=$(podman version --format '{{.Client.Version}}') || fail 'Cannot query rootful Podman version.'
    run_python_module scripts.gateway.host_preflight podman-version "$podman_version" || \
        fail "Host deployment requires Podman 5.8.2; found $podman_version."

    podman_rootless=$(podman info --format '{{.Host.Security.Rootless}}') || fail 'Cannot query Podman host security state.'
    [[ "$podman_rootless" == false ]] || fail 'Rootful Podman is required.'
    selinux_mode=$(getenforce 2>/dev/null) || fail 'Cannot query SELinux mode.'
    [[ "$selinux_mode" == Enforcing ]] || fail "SELinux must remain Enforcing; found $selinux_mode."
    if [[ -e "$PODMAN_SOCKET" || -L "$PODMAN_SOCKET" ]]; then
        [[ -S "$PODMAN_SOCKET" && ! -L "$PODMAN_SOCKET" ]] || fail "Rootful Podman socket path is unsafe: $PODMAN_SOCKET"
    elif systemctl is-active --quiet "$UNIT_NAME"; then
        fail "Running gateway has no rootful Podman socket at $PODMAN_SOCKET."
    fi
    [[ -d "$QUADLET_DIR" && ! -L "$QUADLET_DIR" ]] || fail "Quadlet directory is missing or unsafe: $QUADLET_DIR"

    authorized_keys_path=$(jq -r '.gateway.authorized_keys_path' "$config_path")
    case "$authorized_keys_path" in
        "$REPO_ROOT"/*) fail 'Gateway public keys must be stored outside the Git checkout.' ;;
    esac
    [[ -f "$authorized_keys_path" && ! -L "$authorized_keys_path" && -s "$authorized_keys_path" ]] || \
        fail "Gateway authorized_keys file is missing, empty, or not a regular file: $authorized_keys_path"
    owner=$(stat -c %u "$authorized_keys_path")
    mode=$(stat -c %a "$authorized_keys_path")
    [[ "$owner" == 0 ]] || fail "Gateway authorized_keys file must be owned by root: $authorized_keys_path"
    (( (8#$mode & 0022) == 0 )) || fail "Gateway authorized_keys file must not be group/world writable: $authorized_keys_path"
    [[ -n "$(ssh-keygen -lf "$authorized_keys_path" 2>/dev/null)" ]] || \
        fail "Gateway authorized_keys file contains no valid public keys: $authorized_keys_path"

    [[ -f "$COCKPIT_PASSWORD_FILE" && ! -L "$COCKPIT_PASSWORD_FILE" && -s "$COCKPIT_PASSWORD_FILE" ]] || \
        fail "Cockpit password secret is missing, empty, or not a regular file: $COCKPIT_PASSWORD_FILE"
    owner=$(stat -c %u "$COCKPIT_PASSWORD_FILE")
    mode=$(stat -c %a "$COCKPIT_PASSWORD_FILE")
    [[ "$owner" == 0 ]] || fail "Cockpit password secret must be owned by root: $COCKPIT_PASSWORD_FILE"
    (( (8#$mode & 0177) == 0 )) || fail "Cockpit password secret must not be accessible by group or other users: $COCKPIT_PASSWORD_FILE"
    run_python_module scripts.gateway.host_preflight password-file "$COCKPIT_PASSWORD_FILE" || \
        fail 'Cockpit password secret must contain one non-empty line.'

    [[ -f "$COCKPIT_CERT_FILE" && ! -L "$COCKPIT_CERT_FILE" ]] || \
        fail "Cockpit TLS certificate is missing or unsafe: $COCKPIT_CERT_FILE"
    [[ -f "$COCKPIT_KEY_FILE" && ! -L "$COCKPIT_KEY_FILE" ]] || \
        fail "Cockpit TLS private key is missing or unsafe: $COCKPIT_KEY_FILE"
    owner=$(stat -c %u "$COCKPIT_CERT_FILE")
    [[ "$owner" == 0 ]] || fail "Cockpit TLS certificate must be owned by root: $COCKPIT_CERT_FILE"
    owner=$(stat -c %u "$COCKPIT_KEY_FILE")
    mode=$(stat -c %a "$COCKPIT_KEY_FILE")
    [[ "$owner" == 0 ]] || fail "Cockpit TLS private key must be owned by root: $COCKPIT_KEY_FILE"
    (( (8#$mode & 0177) == 0 )) || fail 'Cockpit TLS private key must not be accessible by group or other users.'
    openssl x509 -in "$COCKPIT_CERT_FILE" -noout >/dev/null 2>&1 || fail 'Cockpit TLS certificate is invalid.'
    openssl x509 -in "$COCKPIT_CERT_FILE" -checkend 0 -noout >/dev/null 2>&1 || fail 'Cockpit TLS certificate is expired.'
    openssl pkey -passin pass: -in "$COCKPIT_KEY_FILE" -noout >/dev/null 2>&1 || fail 'Cockpit TLS private key is invalid or encrypted.'
    certificate_public_key=$(openssl x509 -in "$COCKPIT_CERT_FILE" -pubkey -noout 2>/dev/null) || fail 'Cannot read Cockpit TLS certificate public key.'
    private_public_key=$(openssl pkey -passin pass: -in "$COCKPIT_KEY_FILE" -pubout 2>/dev/null) || fail 'Cannot read Cockpit TLS private key public component.'
    [[ "$certificate_public_key" == "$private_public_key" ]] || fail 'Cockpit TLS certificate and private key do not match.'

    local network_count dns_count
    network_count=$(jq '(.gateway.networks // [.networks[].name]) | length' "$config_path")
    dns_count=$(jq '(.dns_records // []) | length' "$config_path")
    (( network_count > 0 )) || fail 'At least one gateway network must be declared before deployment.'
    (( dns_count > 0 )) || fail 'At least one development DNS record must be declared before deployment.'

    for path in "$STATE_DIR" "$STATE_DIR/generated" "$STATE_DIR/dns" "$HOST_KEYS_DIR"; do
        if [[ -e "$path" || -L "$path" ]]; then
            [[ -d "$path" && ! -L "$path" ]] || fail "Persistent state path is not a safe directory: $path"
            owner=$(stat -c %u "$path")
            [[ "$owner" == 0 ]] || fail "Persistent state directory must be owned by root: $path"
            case "$path" in
                "$HOST_KEYS_DIR") expected_mode=700 ;;
                *) expected_mode=755 ;;
            esac
            mode=$(stat -c %a "$path")
            [[ "$mode" == "$expected_mode" ]] || fail "Persistent state directory $path must have mode $expected_mode; found $mode."
        fi
    done
    for path in "$OWNER_MARKER" "$GENERATED_CONFIG" "$GENERATED_INPUTS" "$DNS_HOSTS_FILE" "$QUADLET_FILE"; do
        if [[ -e "$path" || -L "$path" ]]; then
            [[ -f "$path" && ! -L "$path" ]] || fail "Generated state path is not a regular file: $path"
            owner=$(stat -c %u "$path")
            mode=$(stat -c %a "$path")
            [[ "$owner" == 0 && "$mode" == 644 ]] || fail "Generated state file must be root-owned mode 0644: $path"
        fi
    done
    if [[ -e "$OWNER_MARKER" ]]; then
        [[ -f "$OWNER_MARKER" && ! -L "$OWNER_MARKER" && "$(stat -c %u "$OWNER_MARKER")" == 0 ]] || \
            fail "Persistent-state ownership marker is unsafe: $OWNER_MARKER"
        grep -Fqx 'managed by scripts/deploy-gateway.sh' "$OWNER_MARKER" || \
            fail "Persistent-state ownership marker is not recognized: $OWNER_MARKER"
    elif [[ -e "$GENERATED_CONFIG" || -e "$DNS_HOSTS_FILE" ]]; then
        fail "Generated state exists without its ownership marker: $STATE_DIR"
    fi

    if [[ -e "$host_private_key" || -e "$host_public_key" ]]; then
        [[ -f "$host_private_key" && -f "$host_public_key" && ! -L "$host_private_key" && ! -L "$host_public_key" ]] || \
            fail 'Persistent SSH host key pair is incomplete or unsafe; refusing to replace either key.'
        [[ "$(stat -c %u "$host_private_key")" == 0 && "$(stat -c %u "$host_public_key")" == 0 ]] || \
            fail 'Persistent SSH host keys must be owned by root.'
        mode=$(stat -c %a "$host_private_key")
        (( (8#$mode & 0177) == 0 )) || fail 'Persistent SSH host private key permissions are too broad.'
        ssh-keygen -lf "$host_private_key" >/dev/null 2>&1 || fail 'Persistent SSH host private key is invalid.'
        ssh-keygen -lf "$host_public_key" >/dev/null 2>&1 || fail 'Persistent SSH host public key is invalid.'
        private_public_key=$(ssh-keygen -y -P '' -f "$host_private_key" 2>/dev/null | awk '{print $1 " " $2}') || \
            fail 'Cannot read persistent SSH host private key.'
        certificate_public_key=$(awk 'NF {print $1 " " $2; exit}' "$host_public_key")
        [[ "$private_public_key" == "$certificate_public_key" ]] || fail 'Persistent SSH host key pair does not match.'
    fi
    if [[ -e "$GENERATED_INPUTS" ]]; then
        [[ -f "$host_public_key" ]] || fail 'Previously deployed SSH host identity is missing; refusing to generate a replacement.'
        jq -e '.schema_version == 1 and (.ssh_host_key_fingerprint | type == "string")' \
            "$GENERATED_INPUTS" >/dev/null 2>&1 || fail "Stored runtime input metadata is invalid: $GENERATED_INPUTS"
        host_key_fingerprint=$(ssh-keygen -lf "$host_public_key" | awk '{print $2}')
        previous_host_key_fingerprint=$(jq -r '.ssh_host_key_fingerprint' "$GENERATED_INPUTS")
        [[ "$host_key_fingerprint" == "$previous_host_key_fingerprint" ]] || \
            fail 'Persistent SSH host key identity changed; use an explicit host-key rotation procedure.'
    fi

    [[ -e "$QUADLET_FILE" ]] && {
        grep -Fqx 'Description=Shared Gateway' "$QUADLET_FILE" &&
            grep -Fqx 'ContainerName=gateway' "$QUADLET_FILE" ||
            fail "Refusing to replace an unrelated Quadlet file: $QUADLET_FILE"
    }
    local load_state source_path
    load_state=$(systemctl show "$UNIT_NAME" --property=LoadState --value 2>/dev/null || true)
    if [[ -n "$load_state" && "$load_state" != not-found ]]; then
        source_path=$(systemctl show "$UNIT_NAME" --property=SourcePath --value 2>/dev/null || true)
        [[ "$source_path" == "$QUADLET_FILE" ]] || fail "Systemd unit $UNIT_NAME is not generated from $QUADLET_FILE"
    fi
    if podman container exists "$CONTAINER_NAME" >/dev/null 2>&1; then
        local unit_label
        unit_label=$(podman inspect --format '{{ index .Config.Labels "PODMAN_SYSTEMD_UNIT" }}' "$CONTAINER_NAME") || \
            fail "Cannot verify ownership of container $CONTAINER_NAME"
        [[ "$unit_label" == "$UNIT_NAME" ]] || fail "Container name '$CONTAINER_NAME' belongs to another workload."
        gateway_managed=1
    fi

    ssh_bind_address=$(jq -r '.gateway.ssh_bind_address // .gateway.bind_address' "$config_path")
    cockpit_bind_address=$(jq -r '.gateway.cockpit_bind_address // .gateway.bind_address' "$config_path")
    for bind_address in "$ssh_bind_address" "$cockpit_bind_address"; do
        if [[ "$bind_address" != 127.0.0.1 && "$bind_address" != 0.0.0.0 ]]; then
            ip -j -4 address show | jq -e --arg address "$bind_address" \
                'any(.[].addr_info[]; .local == $address)' >/dev/null || \
                fail "Configured management bind address is not assigned to this host: $bind_address"
        fi
    done

    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    for port in "$ssh_port" "$cockpit_port"; do
        listener=$(ss -H -ltn "sport = :$port") || fail "Cannot check whether TCP port $port is available."
        if [[ -n "$listener" && "$gateway_managed" != 1 ]]; then
            fail "TCP port $port is already in use by another service."
        fi
    done

    run_python_module scripts.gateway.host_preflight podman-state \
        --allow-missing-gateway-networks "$config_path"
}
# ---------------------------------- #

# Run generic host checks and include gateway checks when configured.
check_host_preflight() {
    local config_path=${1:-$DEFAULT_CONFIG}

    validate_config "$config_path"
    command -v podman >/dev/null 2>&1 || fail 'podman is required for host preflight.'
    podman version --format '{{.Client.Version}}' >/dev/null || fail 'Cannot query Podman client version.'
    run_python_module scripts.gateway.host_preflight podman-state "$config_path"
}
# ---------------------------------- #

# Require a gateway section for gateway deployment commands.
require_gateway_config() {
    local config_path=$1

    jq -e 'has("gateway")' "$config_path" >/dev/null || \
        fail 'Gateway configuration is required for gateway deployment.'
}
# ---------------------------------- #

# Run configuration validation or read-only host preflight from the command line.
preflight_main() {
    [[ $# -ge 1 ]] || { preflight_usage >&2; exit 2; }

    case "$1" in
        --validate-config)
            shift
            [[ $# -le 1 ]] || { preflight_usage >&2; exit 2; }
            validate_config "${1:-$DEFAULT_CONFIG}"
            printf '[host-preflight] Configuration valid: %s\n' "${1:-$DEFAULT_CONFIG}"
            ;;
        --validate-gateway-config)
            shift
            [[ $# -le 1 ]] || { preflight_usage >&2; exit 2; }
            validate_config "${1:-$DEFAULT_CONFIG}"
            require_gateway_config "${1:-$DEFAULT_CONFIG}"
            printf '[host-preflight] Gateway configuration valid: %s\n' "${1:-$DEFAULT_CONFIG}"
            ;;
        --check)
            shift
            [[ $# -le 1 ]] || { preflight_usage >&2; exit 2; }
            check_host_preflight "${1:-$DEFAULT_CONFIG}"
            printf '[host-preflight] Read-only host preflight passed.\n'
            ;;
        --check-gateway)
            shift
            [[ $# -le 1 ]] || { preflight_usage >&2; exit 2; }
            local config_path=${1:-$DEFAULT_CONFIG}
            validate_config "$config_path"
            require_gateway_config "$config_path"
            check_gateway_host_preflight "$config_path"
            printf '[host-preflight] Gateway deployment preflight passed.\n'
            ;;
        --help|-h)
            preflight_usage
            ;;
        *)
            preflight_usage >&2
            fail "Unknown option: $1"
            ;;
    esac
}
# ---------------------------------- #

preflight_usage() {
    printf 'Usage: %s --validate-config|--validate-gateway-config|--check|--check-gateway [host_config.json]\n' "${0##*/}"
}
# ---------------------------------- #

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    preflight_main "$@"
fi