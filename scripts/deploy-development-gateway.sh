#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly DEFAULT_CONFIG="$REPO_ROOT/config/development-gateway.json"
readonly QUADLET_DIR=/etc/containers/systemd
readonly PODMAN_SOCKET=/run/podman/podman.sock
readonly COCKPIT_PASSWORD_FILE=/etc/development-gateway/cockpit-password
readonly COCKPIT_CERT_FILE=/etc/development-gateway/tls/development-gateway.cert
readonly COCKPIT_KEY_FILE=/etc/development-gateway/tls/development-gateway.key
readonly STATE_DIR=/var/lib/development-gateway
readonly GENERATED_CONFIG="$STATE_DIR/generated/config.json"
readonly GENERATED_INPUTS="$STATE_DIR/generated/inputs.json"
readonly DNS_HOSTS_FILE="$STATE_DIR/dns/hosts"
readonly HOST_KEYS_DIR="$STATE_DIR/ssh_host_keys"
readonly QUADLET_FILE="$QUADLET_DIR/development-gateway.container"
readonly OWNER_MARKER="$STATE_DIR/.managed-by-development-gateway"
readonly UNIT_TEMPLATE="$REPO_ROOT/deploy/quadlet/development-gateway.container"
readonly IMAGE=localhost/development-gateway:1
readonly CONTAINER_NAME=development-gateway
readonly UNIT_NAME=development-gateway.service

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

fail() {
    printf '[development-gateway] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf 'Usage: %s --validate-config|--check|--apply [config.json]\n' "${0##*/}"
}

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
        object_with_keys(["schema_version", "gateway", "networks", "dns_records"]) and
        .schema_version == 1 and
        (.gateway | object_with_keys(["name", "bind_address", "ssh_port", "cockpit_port", "authorized_keys_path"]) and
            (.name | podman_name) and .name == "development-gateway" and
            (.bind_address | type == "string" and length > 0) and
            (.ssh_port | port) and
            (.cockpit_port | port) and
            .ssh_port != .cockpit_port and
            (.authorized_keys_path | type == "string" and
                test("^/[A-Za-z0-9_./-]+$") and
                (split("/") | all(.[]; . != "." and . != "..")))) and
        (.networks | type == "array") and
        all(.networks[]; object_with_keys(["name", "subnet"]) and
            (.name | podman_name) and (.subnet | type == "string")) and
        ([.networks[].name] | length == (unique | length)) and
        (.dns_records | type == "array") and
        all(.dns_records[]; object_with_keys(["name", "container", "network"]) and
            (.name | dns_name) and (.container | podman_name) and (.network | podman_name)) and
        ([.dns_records[].name] | length == (unique | length)) and
        ([.networks[].name] as $networks |
            all(.dns_records[]; .network as $network | $networks | index($network) != null))
    ' "$config_path" >/dev/null 2>&1 || fail 'Configuration violates schema version 1, contains duplicate names, or has invalid network/DNS declarations.'

    python3 - "$config_path" <<'PY'
import ipaddress
import json
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    bind_address = ipaddress.ip_address(config["gateway"]["bind_address"])
    if bind_address.version != 4:
        raise ValueError("gateway.bind_address must be an IPv4 address")

    networks = []
    for entry in config["networks"]:
        subnet = ipaddress.ip_network(entry["subnet"], strict=True)
        if subnet.version != 4:
            raise ValueError(f"network '{entry['name']}' subnet must be IPv4")
        for known_name, known_subnet in networks:
            if subnet.overlaps(known_subnet):
                raise ValueError(
                    f"network '{entry['name']}' subnet {subnet} overlaps "
                    f"network '{known_name}' subnet {known_subnet}"
                )
        networks.append((entry["name"], subnet))
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
    print(f"[development-gateway] ERROR: invalid address/network declaration: {error}", file=sys.stderr)
    sys.exit(1)
PY
}

check_host_preflight() {
    local config_path=${1:-$DEFAULT_CONFIG}
    local os_id os_version podman_version podman_rootless selinux_mode
    local authorized_keys_path ssh_port cockpit_port listener mode owner bind_address
    local gateway_managed=0 host_private_key="$HOST_KEYS_DIR/ssh_host_ed25519_key"
    local host_public_key="$HOST_KEYS_DIR/ssh_host_ed25519_key.pub" certificate_public_key private_public_key
    local host_key_fingerprint previous_host_key_fingerprint

    validate_config "$config_path"
    [[ "$EUID" -eq 0 ]] || fail 'Run host preflight as root for rootful Podman checks.'
    [[ -r /etc/os-release ]] || fail 'Cannot identify the host operating system.'
    source /etc/os-release
    os_id=${ID:-unknown}
    os_version=${VERSION_ID:-unknown}
    [[ "$os_id" == rhel && ( "$os_version" == 9 || "$os_version" == 9.* ) ]] || \
        fail "Host deployment requires RHEL 9; found $os_id $os_version."

    local tool path expected_mode
    for tool in podman systemctl ss ssh-keygen getenforce stat openssl curl ip install cmp; do
        command -v "$tool" >/dev/null 2>&1 || fail "Required host tool is missing: $tool"
    done
    [[ -d /run/systemd/system ]] || fail 'systemd is not running.'
    [[ -x /usr/lib/systemd/system-generators/podman-system-generator || \
        -x /usr/libexec/podman/quadlet ]] || fail 'The Podman Quadlet systemd generator is missing.'
    systemctl cat podman.socket >/dev/null 2>&1 || fail 'The rootful podman.socket systemd unit is missing.'

    podman_version=$(podman version --format '{{.Client.Version}}') || fail 'Cannot query rootful Podman version.'
    python3 - "$podman_version" <<'PY' || fail "Podman $podman_version is unsupported; Quadlet requires Podman 4.4 or newer."
import sys

try:
    version = tuple(int(part) for part in sys.argv[1].lstrip("v").split(".")[:2])
except ValueError:
    sys.exit(1)
sys.exit(0 if version >= (4, 4) else 1)
PY

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
    python3 - "$COCKPIT_PASSWORD_FILE" <<'PY' || fail 'Cockpit password secret must contain one non-empty line.'
import pathlib
import sys

password = pathlib.Path(sys.argv[1]).read_bytes().rstrip(b"\n")
sys.exit(0 if password and b"\n" not in password and b"\r" not in password and b"\0" not in password else 1)
PY

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
    network_count=$(jq '.networks | length' "$config_path")
    dns_count=$(jq '.dns_records | length' "$config_path")
    (( network_count > 0 )) || fail 'At least one application network must be declared before deployment.'
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
        grep -Fqx 'managed by scripts/deploy-development-gateway.sh' "$OWNER_MARKER" || \
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
        grep -Fqx 'Description=Shared Development Gateway' "$QUADLET_FILE" &&
            grep -Fqx 'ContainerName=development-gateway' "$QUADLET_FILE" ||
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

    bind_address=$(jq -r '.gateway.bind_address' "$config_path")
    if [[ "$bind_address" != 127.0.0.1 ]]; then
        ip -j -4 address show | jq -e --arg address "$bind_address" \
            'any(.[].addr_info[]; .local == $address)' >/dev/null || \
            fail "Configured management bind address is not assigned to this host: $bind_address"
    fi

    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    for port in "$ssh_port" "$cockpit_port"; do
        listener=$(ss -H -ltn "sport = :$port") || fail "Cannot check whether TCP port $port is available."
        if [[ -n "$listener" && "$gateway_managed" != 1 ]]; then
            fail "TCP port $port is already in use by another service."
        fi
    done

    python3 - "$config_path" <<'PY'
import ipaddress
import json
import subprocess
import sys

def run_json(*args):
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(args)}")
    return json.loads(result.stdout)

def network_subnets(network):
    raw = network.get("subnets", [])
    if isinstance(raw, dict):
        raw = [raw]
    return [ipaddress.ip_network(item["subnet"], strict=True) for item in raw if item.get("subnet")]

try:
    with open(sys.argv[1], encoding="utf-8") as config_file:
        config = json.load(config_file)

    names_output = subprocess.run(
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        check=True, capture_output=True, text=True
    ).stdout
    existing = {}
    for name in names_output.splitlines():
        details = run_json("podman", "network", "inspect", name)[0]
        existing[name] = network_subnets(details)

    declared = {entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
                for entry in config["networks"]}
    for name, subnet in declared.items():
        if name in existing:
            ipv4_subnets = [current for current in existing[name] if current.version == 4]
            if ipv4_subnets != [subnet]:
                raise ValueError(
                    f"existing Podman network '{name}' does not match declared subnet {subnet}"
                )
        for existing_name, subnets in existing.items():
            if existing_name == name:
                continue
            for existing_subnet in subnets:
                if subnet.overlaps(existing_subnet):
                    raise ValueError(
                        f"declared network '{name}' subnet {subnet} overlaps existing "
                        f"Podman network '{existing_name}' subnet {existing_subnet}"
                    )

    for record in config["dns_records"]:
        result = subprocess.run(
            ["podman", "container", "exists", record["container"]],
            check=False, capture_output=True, text=True
        )
        if result.returncode == 1:
            print(f"[development-gateway] PENDING DNS target: {record['name']} ({record['container']} is absent)")
            continue
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"cannot inspect container '{record['container']}'")

        container = run_json("podman", "inspect", "--type", "container", record["container"])[0]
        attached = container.get("NetworkSettings", {}).get("Networks", {})
        if record["network"] not in attached:
            raise ValueError(
                f"container '{record['container']}' is not attached to declared network '{record['network']}'"
            )
        if not container.get("State", {}).get("Running", False):
            print(f"[development-gateway] PENDING DNS target: {record['name']} ({record['container']} is stopped)")
            continue
        address = attached[record["network"]].get("IPAddress", "")
        parsed_address = ipaddress.ip_address(address) if address else None
        if parsed_address is None or parsed_address.version != 4 or parsed_address not in declared[record["network"]]:
            raise ValueError(
                f"running container '{record['container']}' has no valid IPv4 address in declared network '{record['network']}': {address}"
            )
except (OSError, KeyError, TypeError, ValueError, RuntimeError,
        subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print(f"[development-gateway] ERROR: host network preflight failed: {error}", file=sys.stderr)
    sys.exit(1)
PY
}

prepare_state_directories() {
    install -d -o root -g root -m 0755 "$STATE_DIR" "$STATE_DIR/generated" "$STATE_DIR/dns"
    install -d -o root -g root -m 0700 "$HOST_KEYS_DIR"
    if [[ ! -e "$OWNER_MARKER" ]]; then
        printf '%s\n' 'managed by scripts/deploy-development-gateway.sh' > "$OWNER_MARKER"
        chmod 0644 "$OWNER_MARKER"
    fi
}

ensure_host_keys() {
    local private_key="$HOST_KEYS_DIR/ssh_host_ed25519_key"
    local public_key="$private_key.pub"

    if [[ ! -e "$private_key" && ! -e "$public_key" ]]; then
        ssh-keygen -q -t ed25519 -N '' -C development-gateway -f "$private_key" || \
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

    printf '# Managed by scripts/deploy-development-gateway.sh\n' > "$output_path"
    python3 - "$config_path" >> "$output_path" <<'PY'
import ipaddress
import json
import subprocess
import sys

def run_json(*args):
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(args)}")
    return json.loads(result.stdout)

try:
    with open(sys.argv[1], encoding="utf-8") as config_file:
        config = json.load(config_file)
    networks = {entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
                for entry in config["networks"]}

    for record in config["dns_records"]:
        exists = subprocess.run(
            ["podman", "container", "exists", record["container"]],
            check=False, capture_output=True, text=True
        )
        if exists.returncode == 1:
            print(f"[development-gateway] PENDING DNS target: {record['name']} ({record['container']} is absent)", file=sys.stderr)
            continue
        if exists.returncode:
            raise RuntimeError(exists.stderr.strip() or f"cannot inspect container '{record['container']}'")

        container = run_json("podman", "inspect", "--type", "container", record["container"])[0]
        attached = container.get("NetworkSettings", {}).get("Networks", {})
        if record["network"] not in attached:
            raise ValueError(
                f"container '{record['container']}' is not attached to declared network '{record['network']}'"
            )
        if not container.get("State", {}).get("Running", False):
            print(f"[development-gateway] PENDING DNS target: {record['name']} ({record['container']} is stopped)", file=sys.stderr)
            continue

        address = attached[record["network"]].get("IPAddress", "")
        parsed_address = ipaddress.ip_address(address)
        if parsed_address.version != 4 or parsed_address not in networks[record["network"]]:
            raise ValueError(
                f"container '{record['container']}' has an invalid address on '{record['network']}': {address}"
            )
        print(f"{parsed_address} {record['name']}")
except (OSError, KeyError, TypeError, ValueError, RuntimeError,
        subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print(f"[development-gateway] ERROR: DNS generation failed: {error}", file=sys.stderr)
    sys.exit(1)
PY
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
    local authorized_keys_path bind_address ssh_port cockpit_port network_lines published_lines template

    authorized_keys_path=$(jq -r '.gateway.authorized_keys_path' "$config_path")
    bind_address=$(jq -r '.gateway.bind_address' "$config_path")
    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    network_lines=$(jq -r '.networks[] | "Network=" + .name' "$config_path")
    published_lines=$(printf 'PublishPort=%s:%s:22\nPublishPort=%s:%s:9090' \
        "$bind_address" "$ssh_port" "$bind_address" "$cockpit_port")
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

    temporary_dir=$(mktemp -d /var/tmp/development-gateway-quadlet.XXXXXX)
    input_dir="$temporary_dir/input"
    normal_dir="$temporary_dir/normal"
    early_dir="$temporary_dir/early"
    late_dir="$temporary_dir/late"
    mkdir -p "$input_dir" "$normal_dir" "$early_dir" "$late_dir"
    cp -- "$candidate" "$input_dir/development-gateway.container"
    if [[ -x /usr/lib/systemd/system-generators/podman-system-generator ]]; then
        generator=/usr/lib/systemd/system-generators/podman-system-generator
    else
        generator=/usr/libexec/podman/quadlet
    fi

    status=0
    QUADLET_UNIT_DIRS="$input_dir" "$generator" -dryrun "$normal_dir" "$early_dir" "$late_dir" \
        > "$temporary_dir/generated-units" 2> "$temporary_dir/generator-errors" || status=$?
    if (( status != 0 )) || ! grep -Fq 'Description=Shared Development Gateway' "$temporary_dir/generated-units"; then
        cat "$temporary_dir/generator-errors" >&2
        rm -f -- "$input_dir/development-gateway.container" "$temporary_dir/generated-units" \
            "$temporary_dir/generator-errors"
        rmdir -- "$input_dir" "$normal_dir" "$early_dir" "$late_dir" "$temporary_dir" 2>/dev/null || true
        fail 'Podman Quadlet generator rejected the staged gateway unit.'
    fi

    rm -f -- "$input_dir/development-gateway.container" "$temporary_dir/generated-units" \
        "$temporary_dir/generator-errors"
    rmdir -- "$input_dir" "$normal_dir" "$early_dir" "$late_dir" "$temporary_dir" || \
        fail 'Could not remove temporary Quadlet validation files.'
}

stage_managed_files() {
    local config_path=$1

    STAGED_CONFIG=$(mktemp "$STATE_DIR/generated/.config.XXXXXX")
    STAGED_INPUTS=$(mktemp "$STATE_DIR/generated/.inputs.XXXXXX")
    STAGED_DNS=$(mktemp "$STATE_DIR/dns/.hosts.XXXXXX")
    STAGED_QUADLET=$(mktemp "$QUADLET_DIR/.development-gateway.XXXXXX")
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

    printf '[development-gateway] Apply failed; restoring generated files and prior service state.\n' >&2
    if [[ "$ACTIVATION_ATTEMPTED" == 1 ]]; then
        systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    fi

    restore_file "$QUADLET_FILE" quadlet || { printf '[development-gateway] ERROR: could not restore Quadlet file.\n' >&2; rollback_failed=1; }
    restore_file "$GENERATED_CONFIG" config || { printf '[development-gateway] ERROR: could not restore generated configuration.\n' >&2; rollback_failed=1; }
    restore_file "$GENERATED_INPUTS" inputs || { printf '[development-gateway] ERROR: could not restore runtime input metadata.\n' >&2; rollback_failed=1; }
    restore_file "$DNS_HOSTS_FILE" dns || { printf '[development-gateway] ERROR: could not restore generated DNS records.\n' >&2; rollback_failed=1; }

    if [[ -n "$PREVIOUS_IMAGE_ID" ]]; then
        podman tag "$PREVIOUS_IMAGE_ID" "$IMAGE" >/dev/null 2>&1 || {
            printf '[development-gateway] ERROR: could not restore the previous image tag.\n' >&2
            rollback_failed=1
        }
    fi

    systemctl daemon-reload >/dev/null 2>&1 || {
        printf '[development-gateway] ERROR: systemd reload failed during rollback.\n' >&2
        rollback_failed=1
    }
    if [[ "$SERVICE_WAS_ENABLED" == 1 ]]; then
        systemctl enable "$UNIT_NAME" >/dev/null 2>&1 || rollback_failed=1
    else
        systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true
    fi
    if [[ "$SERVICE_WAS_ACTIVE" == 1 ]]; then
        systemctl start "$UNIT_NAME" >/dev/null 2>&1 || {
            printf '[development-gateway] ERROR: previous gateway service did not recover.\n' >&2
            rollback_failed=1
        }
    elif [[ "$ACTIVATION_ATTEMPTED" == 1 ]]; then
        systemctl stop "$UNIT_NAME" >/dev/null 2>&1 || true
    fi

    if [[ "$SOCKET_WAS_ACTIVE" != 1 ]]; then
        systemctl stop podman.socket >/dev/null 2>&1 || true
    fi
    if (( ${#NETWORKS_CREATED[@]} > 0 )); then
        printf '[development-gateway] Additive networks remain and were not removed: %s\n' "${NETWORKS_CREATED[*]}" >&2
    fi
    printf '[development-gateway] Persistent SSH host keys and built images remain untouched.\n' >&2
    if (( rollback_failed == 0 )); then
        printf '[development-gateway] Previous generated files and service state restored.\n' >&2
    else
        printf '[development-gateway] ERROR: rollback was incomplete; inspect systemd and Podman state before retrying.\n' >&2
    fi
}

test_dns_candidate() {
    local candidate=$1

    podman run --rm --network none \
        --volume "$candidate:/run/development-gateway/dns/hosts:ro" \
        --entrypoint dnsmasq "$IMAGE" --test --no-resolv --no-hosts \
        --bind-dynamic --addn-hosts=/run/development-gateway/dns/hosts >/dev/null || \
        fail 'Candidate DNS records failed DNSMasq validation.'
}

check_gateway_health() {
    local config_path=$1 dns_file=$2 bind_address ssh_port cockpit_port expected_networks attached_networks
    local resolved expected_address dns_name

    systemctl is-active --quiet "$UNIT_NAME" || fail "Gateway unit is not active: $UNIT_NAME"
    [[ "$(podman inspect --format '{{.State.Running}}' "$CONTAINER_NAME")" == true ]] || \
        fail "Gateway container is not running: $CONTAINER_NAME"

    expected_networks=$(jq -c '[.networks[].name] | sort' "$config_path")
    attached_networks=$(podman inspect --format '{{json .NetworkSettings.Networks}}' "$CONTAINER_NAME") || \
        fail 'Cannot inspect gateway network attachments.'
    jq -e --argjson expected "$expected_networks" 'keys | sort == $expected' <<< "$attached_networks" >/dev/null || \
        fail 'Gateway network attachments differ from the declared application networks.'

    podman exec "$CONTAINER_NAME" /usr/sbin/sshd -t -f /run/development-gateway/sshd_config || \
        fail 'OpenSSH health check failed.'
    podman exec "$CONTAINER_NAME" dnsmasq --test --no-resolv --no-hosts --bind-dynamic \
        --addn-hosts=/run/development-gateway/dns/hosts >/dev/null || fail 'DNSMasq health check failed.'
    [[ "$(podman exec --user gateway-admin "$CONTAINER_NAME" podman info --format '{{.Host.Security.Rootless}}')" == false ]] || \
        fail 'Cockpit Podman socket health check did not reach rootful Podman.'

    bind_address=$(jq -r '.gateway.bind_address' "$config_path")
    ssh_port=$(jq -r '.gateway.ssh_port' "$config_path")
    cockpit_port=$(jq -r '.gateway.cockpit_port' "$config_path")
    if [[ "$bind_address" == 0.0.0.0 ]]; then bind_address=127.0.0.1; fi
    ssh-keyscan -T 5 -p "$ssh_port" "$bind_address" >/dev/null 2>&1 || fail 'SSH readiness check failed.'
    curl --silent --show-error --fail --insecure --max-time 5 \
        "https://$bind_address:$cockpit_port/" >/dev/null || fail 'Cockpit HTTPS readiness check failed.'

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
            printf '[development-gateway] Apply stopped before activation; additive directories, host keys, networks, or image layers may remain. No data or secrets were removed.\n' >&2
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

apply_deployment() {
    local config_path=$1 previous_container_image='' previous_tagged_image=''
    local current_image_id='' desired_image_id='' unit_changed=0 config_changed=0 inputs_changed=0 dns_changed=0
    local restart_needed=0 network

    check_host_preflight "$config_path"
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
    podman build --pull=always --file "$REPO_ROOT/gateway/development/Containerfile" \
        --tag "$IMAGE" "$REPO_ROOT/gateway/development" || fail 'Debian gateway image build failed.'
    desired_image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE") || fail 'Cannot inspect the built gateway image.'
    ensure_host_keys
    stage_managed_files "$config_path"
    validate_quadlet_candidate "$STAGED_QUADLET"
    test_dns_candidate "$STAGED_DNS"

    BACKUP_DIR=$(mktemp -d /var/tmp/development-gateway-backup.XXXXXX)
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

    printf '[development-gateway] Deployment ready.\n'
    if (( unit_changed || config_changed || dns_changed || restart_needed )); then
        printf '[development-gateway] Changed: '
        (( unit_changed )) && printf 'Quadlet '
        (( config_changed )) && printf 'configuration '
        (( inputs_changed )) && printf 'runtime inputs '
        (( dns_changed )) && printf 'DNS '
        (( restart_needed )) && printf 'gateway service '
        printf '\n'
    else
        printf '[development-gateway] No generated files or service restart needed.\n'
    fi
    if (( ${#NETWORKS_CREATED[@]} > 0 )); then
        printf '[development-gateway] Created application networks: %s\n' "${NETWORKS_CREATED[*]}"
    fi
    printf '[development-gateway] Service status: %s\n' "$(systemctl is-active "$UNIT_NAME")"
    printf '[development-gateway] Recovery: journalctl -u %s; rerun --check before another apply.\n' "$UNIT_NAME"
}

main() {
    [[ $# -ge 1 ]] || { usage >&2; exit 2; }

    case "$1" in
        --validate-config)
            shift
            [[ $# -le 1 ]] || { usage >&2; exit 2; }
            validate_config "${1:-$DEFAULT_CONFIG}"
            printf '[development-gateway] Configuration valid: %s\n' "${1:-$DEFAULT_CONFIG}"
            ;;
        --check)
            shift
            [[ $# -le 1 ]] || { usage >&2; exit 2; }
            check_host_preflight "${1:-$DEFAULT_CONFIG}"
            printf '[development-gateway] Read-only host preflight passed.\n'
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

main "$@"