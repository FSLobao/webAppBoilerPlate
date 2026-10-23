#!/usr/bin/env bash
set -Eeuo pipefail

readonly CONFIG=/etc/gateway/generated/config.json
readonly AUTHORIZED_KEYS=/run/gateway/authorized_keys
readonly SSH_TUN_AUTHORIZED_KEYS=/run/gateway/ssh_tun/authorized_keys
readonly COCKPIT_PASSWORD=/run/secrets/cockpit-password
readonly HOST_KEY=/run/ssh-host-keys/ssh_host_ed25519_key
readonly HOST_PUBLIC_KEY=/run/ssh-host-keys/ssh_host_ed25519_key.pub
readonly COCKPIT_CERT=/etc/cockpit/ws-certs.d/gateway.cert
readonly COCKPIT_KEY=/etc/cockpit/ws-certs.d/gateway.key
readonly DNS_HOSTS=/run/gateway/dns/hosts
readonly WIREGUARD_KEY=/run/gateway/wireguard/server.key
readonly WIREGUARD_STATE=/var/lib/gateway/wireguard

fail() {
    printf '[gateway] ERROR: %s\n' "$*" >&2
    exit 1
}

require_file() {
    local path=$1
    [[ -f "$path" && -r "$path" && ! -L "$path" ]] || fail "Required read-only file is missing or unsafe: $path"
}

require_root_owned() {
    local path=$1
    [[ "$(stat -c %u "$path")" == 0 ]] || fail "Mounted input must be owned by root: $path"
}

require_private_mode() {
    local path=$1 mode
    mode=$(stat -c %a "$path")
    (( (8#$mode & 0177) == 0 )) || fail "Mounted private input has unsafe permissions: $path"
}

require_read_only_mount() {
    local path=$1 options
    options=$(findmnt -n -o VFS-OPTIONS --target "$path") || fail "Cannot inspect mount mode: $path"
    case ",$options," in
        *,ro,*) ;;
        *) fail "Required input is not mounted read-only: $path" ;;
    esac
}

require_file "$CONFIG"
require_file "$AUTHORIZED_KEYS"
require_file "$COCKPIT_PASSWORD"
require_file "$HOST_KEY"
require_file "$HOST_PUBLIC_KEY"
require_file "$COCKPIT_CERT"
require_file "$COCKPIT_KEY"
require_file "$DNS_HOSTS"
for path in "$CONFIG" "$AUTHORIZED_KEYS" "$COCKPIT_PASSWORD" "$HOST_KEY" \
    "$HOST_PUBLIC_KEY" "$COCKPIT_CERT" "$COCKPIT_KEY" "$DNS_HOSTS"; do
    require_root_owned "$path"
done
for path in "$COCKPIT_PASSWORD" "$HOST_KEY" "$COCKPIT_KEY"; do
    require_private_mode "$path"
done
for path in "$AUTHORIZED_KEYS" "$CONFIG" "$HOST_PUBLIC_KEY" "$COCKPIT_CERT" "$DNS_HOSTS"; do
    mode=$(stat -c %a "$path")
    (( (8#$mode & 0022) == 0 )) || fail "Mounted input must not be group/world writable: $path"
done
for path in "$CONFIG" "$AUTHORIZED_KEYS" "$COCKPIT_PASSWORD" "$HOST_KEY" \
    "$HOST_PUBLIC_KEY" "$COCKPIT_CERT" "$COCKPIT_KEY" "$DNS_HOSTS"; do
    require_read_only_mount "$path"
done

python3 /usr/local/lib/gateway/host_config_validation.py "$CONFIG" >/dev/null || \
    fail "Invalid Gateway host configuration; duplicate keys, gateway.networks, and application_gateway are rejected: $CONFIG"

jq -e '
    .schema_version == 1 and
    .gateway.name == "gateway" and
    (.gateway.ssh_port | type == "number") and
    (.gateway.cockpit_port | type == "number") and
    (.networks | type == "array") and
    ((.gateway.remote_access.openvpn.enabled // false) | type == "boolean") and
    ((.gateway.remote_access.ssh_tun.enabled // false) | type == "boolean") and
    (.dns_records | type == "array")
' "$CONFIG" >/dev/null 2>&1 || fail "Invalid gateway configuration: $CONFIG"
openvpn_enabled=$(jq -r '.gateway.remote_access.openvpn.enabled // false' "$CONFIG")
ssh_tun_enabled=$(jq -r '.gateway.remote_access.ssh_tun.enabled // false' "$CONFIG")
wireguard_enabled=$(jq -r '.gateway.remote_access.wireguard.enabled // false' "$CONFIG")
[[ "$wireguard_enabled" == true || "$wireguard_enabled" == false ]] || \
    fail 'WireGuard enabled setting must be boolean.'
if [[ "$wireguard_enabled" == true ]]; then
    require_file "$WIREGUARD_KEY"
    require_root_owned "$WIREGUARD_KEY"
    require_private_mode "$WIREGUARD_KEY"
    require_read_only_mount "$WIREGUARD_KEY"
    [[ -d "$WIREGUARD_STATE" && ! -L "$WIREGUARD_STATE" && \
        "$(stat -c %u "$WIREGUARD_STATE")" == 0 ]] || \
        fail 'WireGuard peer storage must be a root-owned mounted directory.'
    mode=$(stat -c %a "$WIREGUARD_STATE")
    (( (8#$mode & 0077) == 0 )) || fail 'WireGuard peer storage permissions are unsafe.'
    findmnt -n -o VFS-OPTIONS --target "$WIREGUARD_STATE" | grep -qvE '(^|,)ro(,|$)' || \
        fail 'WireGuard peer storage must be writable.'
fi
use_pam=no
allow_users=developer
if [[ "$ssh_tun_enabled" == true ]]; then
    require_file "$SSH_TUN_AUTHORIZED_KEYS"
    require_root_owned "$SSH_TUN_AUTHORIZED_KEYS"
    mode=$(stat -c %a "$SSH_TUN_AUTHORIZED_KEYS")
    (( (8#$mode & 0022) == 0 )) || fail 'SSH TUN public keys must not be group/world writable.'
    require_read_only_mount "$SSH_TUN_AUTHORIZED_KEYS"
    python3 /usr/local/lib/gateway/ssh_tun_runtime.py check || \
        fail 'SSH TUN configuration or root-managed public keys are invalid.'
    use_pam=yes
    allow_users='developer gateway-tunnel'
fi

[[ -n "$(ssh-keygen -lf "$AUTHORIZED_KEYS" 2>/dev/null)" ]] || fail 'No valid gateway public keys are mounted.'
ssh-keygen -lf "$HOST_KEY" >/dev/null 2>&1 || fail 'Persistent SSH host private key is invalid.'
ssh-keygen -lf "$HOST_PUBLIC_KEY" >/dev/null 2>&1 || fail 'Persistent SSH host public key is invalid.'
derived_host_public_key=$(ssh-keygen -y -P '' -f "$HOST_KEY" 2>/dev/null | awk '{print $1 " " $2}') || fail 'Cannot read persistent SSH host private key.'
stored_host_public_key=$(awk 'NF {print $1 " " $2; exit}' "$HOST_PUBLIC_KEY")
[[ "$derived_host_public_key" == "$stored_host_public_key" ]] || fail 'Persistent SSH host key pair does not match.'
openssl x509 -in "$COCKPIT_CERT" -noout >/dev/null 2>&1 || fail 'Cockpit TLS certificate is invalid.'
openssl pkey -passin pass: -in "$COCKPIT_KEY" -noout >/dev/null 2>&1 || fail 'Cockpit TLS private key is invalid or encrypted.'
cmp -s <(openssl x509 -in "$COCKPIT_CERT" -pubkey -noout) \
    <(openssl pkey -passin pass: -in "$COCKPIT_KEY" -pubout 2>/dev/null) || fail 'Cockpit TLS certificate and private key do not match.'

cockpit_password=$(<"$COCKPIT_PASSWORD")
[[ -n "$cockpit_password" && "$cockpit_password" != *$'\n'* ]] || fail 'Cockpit password secret must contain one non-empty line.'
printf 'gateway-admin:%s\n' "$cockpit_password" | chpasswd || fail 'Could not configure the Cockpit login.'
unset cockpit_password

jq -r '
    [.dns_records[].name + ":22"] as $targets |
    if ($targets | length) == 0 then "PermitOpen none"
    else "PermitOpen " + ($targets | join(" ")) end
' "$CONFIG" > /run/gateway/sshd_config
cat >> /run/gateway/sshd_config <<EOF
Port 22
HostKey $HOST_KEY
PidFile /run/sshd.pid
UsePAM $use_pam
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
AuthorizedKeysFile $AUTHORIZED_KEYS
AllowTcpForwarding local
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
PermitTunnel no
X11Forwarding no
StrictModes yes
AllowUsers $allow_users
EOF
if [[ "$ssh_tun_enabled" == true ]]; then
    cat >> /run/gateway/sshd_config <<'EOF'
AuthorizedKeysCommand /usr/local/lib/gateway/ssh_tun_runtime.py authkeys %u %t %k %C
AuthorizedKeysCommandUser root
Match User gateway-tunnel
    AuthorizedKeysFile none
    AuthenticationMethods publickey
    ForceCommand /usr/local/lib/gateway/ssh_tun_runtime.py session
    PermitTunnel point-to-point
    AllowTcpForwarding no
    AllowAgentForwarding no
    AllowStreamLocalForwarding no
    X11Forwarding no
    PermitTTY no
    PermitUserRC no
    ClientAliveInterval 15
    ClientAliveCountMax 3
EOF
fi

mkdir -p /run/sshd
chmod 0755 /run/sshd
/usr/sbin/sshd -t -f /run/gateway/sshd_config || fail 'OpenSSH configuration validation failed.'
dnsmasq --test --no-resolv --no-hosts --bind-dynamic --addn-hosts="$DNS_HOSTS" >/dev/null || \
    fail 'DNSMasq configuration or generated DNS records are invalid.'

children=()
child_names=()
stop_children() {
    local child
    trap - TERM INT HUP
    for child in "${children[@]}"; do
        kill -TERM "$child" 2>/dev/null || true
    done
    for child in "${children[@]}"; do
        wait "$child" 2>/dev/null || true
    done
}
shutdown() {
    stop_children
    exit 0
}
trap shutdown TERM INT HUP

/usr/sbin/sshd -D -e -f /run/gateway/sshd_config &
children+=("$!")
child_names+=("OpenSSH")
dnsmasq --no-daemon --keep-in-foreground --no-resolv --no-hosts \
    --bind-dynamic --addn-hosts="$DNS_HOSTS" &
children+=("$!")
child_names+=("DNSMasq")
/usr/lib/cockpit/cockpit-ws --port 9090 --address 0.0.0.0 &
children+=("$!")
child_names+=("Cockpit")
if [[ "$openvpn_enabled" == true ]]; then
    python3 /usr/local/lib/gateway/openvpn_runtime.py run "$CONFIG" &
    children+=("$!")
    child_names+=("OpenVPN")
fi
if [[ "$wireguard_enabled" == true ]]; then
    if [[ -e "$WIREGUARD_STATE/critical-failure" || -L "$WIREGUARD_STATE/critical-failure" ]]; then
        if python3 /usr/local/lib/gateway/wireguard.py fail-stop "$CONFIG"; then
            printf '[gateway] WireGuard fail-stop marker detected; firewall drop installed; WireGuard remains disabled pending operator recovery.\n' >&2
        else
            printf '[gateway] CRITICAL: WireGuard fail-stop marker detected; runtime remains disabled; firewall drop installation failed and kernel interface state is unverified.\n' >&2
        fi
    else
        python3 /usr/local/lib/gateway/wireguard.py run "$CONFIG" &
        children+=("$!")
        child_names+=("WireGuard")
    fi
fi

exited_child=''
if wait -n -p exited_child "${children[@]}"; then
    status=0
else
    status=$?
fi
exited_name=unknown
for child_index in "${!children[@]}"; do
    if [[ "${children[$child_index]}" == "$exited_child" ]]; then
        exited_name=${child_names[$child_index]}
        break
    fi
done
printf '[gateway] Supervised service %s (pid %s) exited with status %s.\n' \
    "$exited_name" "$exited_child" "$status" >&2
stop_children
exit 1