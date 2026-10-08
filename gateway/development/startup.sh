#!/usr/bin/env bash
set -Eeuo pipefail

readonly CONFIG=/etc/development-gateway/generated/config.json
readonly AUTHORIZED_KEYS=/run/development-gateway/authorized_keys
readonly COCKPIT_PASSWORD=/run/secrets/cockpit-password
readonly HOST_KEY=/run/ssh-host-keys/ssh_host_ed25519_key
readonly HOST_PUBLIC_KEY=/run/ssh-host-keys/ssh_host_ed25519_key.pub
readonly COCKPIT_CERT=/etc/cockpit/ws-certs.d/development-gateway.cert
readonly COCKPIT_KEY=/etc/cockpit/ws-certs.d/development-gateway.key
readonly DNS_HOSTS=/run/development-gateway/dns/hosts

fail() {
    printf '[development-gateway] ERROR: %s\n' "$*" >&2
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

jq -e '
    .schema_version == 1 and
    .gateway.name == "development-gateway" and
    (.gateway.ssh_port | type == "number") and
    (.gateway.cockpit_port | type == "number") and
    (.networks | type == "array") and
    (.dns_records | type == "array")
' "$CONFIG" >/dev/null 2>&1 || fail "Invalid gateway configuration: $CONFIG"

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
' "$CONFIG" > /run/development-gateway/sshd_config
cat >> /run/development-gateway/sshd_config <<EOF
Port 22
HostKey $HOST_KEY
PidFile /run/sshd.pid
UsePAM no
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
AuthorizedKeysFile $AUTHORIZED_KEYS
AllowUsers developer
AllowTcpForwarding local
AllowAgentForwarding no
AllowStreamLocalForwarding no
GatewayPorts no
PermitTunnel no
X11Forwarding no
StrictModes yes
EOF

mkdir -p /run/sshd
chmod 0755 /run/sshd
/usr/sbin/sshd -t -f /run/development-gateway/sshd_config || fail 'OpenSSH configuration validation failed.'
dnsmasq --test --no-resolv --no-hosts --bind-dynamic --addn-hosts="$DNS_HOSTS" >/dev/null || \
    fail 'DNSMasq configuration or generated DNS records are invalid.'

children=()
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

/usr/sbin/sshd -D -e -f /run/development-gateway/sshd_config &
children+=("$!")
dnsmasq --no-daemon --keep-in-foreground --no-resolv --no-hosts \
    --bind-dynamic --addn-hosts="$DNS_HOSTS" &
children+=("$!")
/usr/lib/cockpit/cockpit-ws --port 9090 --address 0.0.0.0 &
children+=("$!")

if wait -n "${children[@]}"; then
    status=0
else
    status=$?
fi
printf '[development-gateway] A supervised service exited with status %s.\n' "$status" >&2
stop_children
exit 1