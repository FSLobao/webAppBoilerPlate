#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE_USER=filesvc
readonly INBOX=/mnt/inbox
readonly OUTBOX=/mnt/outbox
readonly EVENTS=/mnt/file-gateway-events
readonly CONFIG_DIR=/etc/file-gateway
readonly HOOK_DIR=/etc/file-gateway/tusd-hooks
readonly QUADLET_DIR=/etc/containers/systemd

log() {
    printf '[file-gateway] %s\n' "$*"
}

TEST_UPLOAD_ID=''
TEST_DOWNLOAD_FILE=''

cleanup_test_artifacts() {
    local exit_status=$?
    trap - EXIT
    if [[ -n "$TEST_UPLOAD_ID" ]]; then
        rm -f -- "$INBOX/$TEST_UPLOAD_ID" "$INBOX/$TEST_UPLOAD_ID.info" \
            "$OUTBOX/$TEST_UPLOAD_ID" "$EVENTS/$TEST_UPLOAD_ID.done" || true
    fi
    [[ -z "$TEST_DOWNLOAD_FILE" ]] || rm -f -- "$TEST_DOWNLOAD_FILE" || true
    exit "$exit_status"
}

fail() {
    printf '[file-gateway] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [[ "$EUID" -eq 0 ]] || fail 'Run this script as root.'
    [[ -d /run/systemd/system ]] || fail 'systemd is not running.'
}

assert_managed_file() {
    local file=$1
    shift
    [[ ! -e "$file" ]] && return 0

    local signature
    for signature in "$@"; do
        grep -Fq -- "$signature" "$file" || fail "Refusing to replace unrelated file: $file"
    done
}

unit_is_loaded() {
    local load_state
    load_state=$(systemctl show "$1" --property=LoadState --value 2>/dev/null || true)
    [[ -n "$load_state" && "$load_state" != not-found ]]
}

unit_matches() {
    local unit=$1
    local description=$2
    local source_path=$3
    local exec_signature=$4
    local actual_description actual_source actual_fragment actual_exec

    unit_is_loaded "$unit" || return 1
    actual_description=$(systemctl show "$unit" --property=Description --value 2>/dev/null || true)
    actual_source=$(systemctl show "$unit" --property=SourcePath --value 2>/dev/null || true)
    actual_fragment=$(systemctl show "$unit" --property=FragmentPath --value 2>/dev/null || true)
    actual_exec=$(systemctl show "$unit" --property=ExecStart --value 2>/dev/null || true)

    if [[ -n "$source_path" && ( "$actual_source" == "$source_path" || "$actual_fragment" == "$source_path" ) ]]; then
        return 0
    fi
    if [[ -n "$description" && "$actual_description" != "$description" ]]; then
        return 1
    fi
    [[ -n "$exec_signature" && "$actual_exec" == *"$exec_signature"* ]]
}

assert_unit_slot_matches() {
    local unit=$1
    local description=$2
    local source_path=$3
    local exec_signature=$4

    if unit_is_loaded "$unit" && ! unit_matches "$unit" "$description" "$source_path" "$exec_signature"; then
        fail "Unit name '$unit' belongs to a different service; refusing to replace it."
    fi
}

stop_matching_unit() {
    local unit=$1
    local description=$2
    local source_path=$3
    local exec_signature=$4

    if unit_matches "$unit" "$description" "$source_path" "$exec_signature"; then
        log "Stopping matching unit $unit"
        systemctl stop "$unit" >/dev/null 2>&1 || true
        systemctl disable "$unit" >/dev/null 2>&1 || true
    fi
}

validate_existing_container() {
    local name=$1
    local image_prefix=$2
    local mount_signature=$3
    local status details image mounts

    podman container exists "$name" >/dev/null 2>&1 && status=0 || status=$?
    case "$status" in
        0) ;;
        1) return 0 ;;
        *) fail "Could not inspect container $name." ;;
    esac

    details=$(podman inspect --format '{{.ImageName}}|{{range .Mounts}}{{.Source}}:{{.Destination}};{{end}}' "$name")
    image=${details%%|*}
    mounts=${details#*|}
    if [[ "$image" != "$image_prefix"* || "$mounts" != *"$mount_signature"* ]]; then
        fail "Container name '$name' is in use by a different workload; refusing to remove it."
    fi
}

remove_matching_container() {
    local name=$1
    if podman container exists "$name" >/dev/null 2>&1; then
        log "Removing matching container $name"
        podman rm --force "$name" >/dev/null
    fi
}

check_existing_deployment_files() {
    assert_managed_file "$QUADLET_DIR/file-gateway.network" 'NetworkName=file-gateway'
    assert_managed_file "$QUADLET_DIR/tusd.container" \
        'ContainerName=tusd' 'Image=docker.io/tusproject/tusd' "Volume=$INBOX:/data"
    assert_managed_file "$QUADLET_DIR/nginx.container" \
        'ContainerName=nginx' 'Image=docker.io/library/nginx' "Volume=$CONFIG_DIR/nginx.conf:/etc/nginx/nginx.conf"
    assert_managed_file /etc/systemd/system/tus-publish.service \
        'Description=Move completed tusd uploads to outbox' 'ExecStart=/usr/local/bin/tus-publish-completed.sh'
    assert_managed_file /etc/systemd/system/tus-publish.path \
        'Description=Watch for completed tusd uploads' 'PathExistsGlob=/mnt/file-gateway-events/*.done'
    assert_managed_file /etc/systemd/system/tus-cleanup.service \
        'Description=Remove expired incomplete tusd uploads' 'ExecStart=/usr/local/bin/tus-cleanup.sh'
    assert_managed_file /etc/systemd/system/tus-cleanup.timer \
        'Description=Hourly cleanup of incomplete tusd uploads' 'OnCalendar=hourly'
}

remove_existing_deployment() {
    assert_unit_slot_matches nginx.service 'nginx file gateway' "$QUADLET_DIR/nginx.container" docker.io/library/nginx
    assert_unit_slot_matches tusd.service 'tusd resumable upload server' "$QUADLET_DIR/tusd.container" docker.io/tusproject/tusd
    assert_unit_slot_matches tus-publish.path 'Watch for completed tusd uploads' \
        /etc/systemd/system/tus-publish.path ''
    assert_unit_slot_matches tus-publish.service 'Move completed tusd uploads to outbox' \
        /etc/systemd/system/tus-publish.service /usr/local/bin/tus-publish-completed.sh
    assert_unit_slot_matches tus-cleanup.timer 'Hourly cleanup of incomplete tusd uploads' \
        /etc/systemd/system/tus-cleanup.timer ''
    assert_unit_slot_matches tus-cleanup.service 'Remove expired incomplete tusd uploads' \
        /etc/systemd/system/tus-cleanup.service /usr/local/bin/tus-cleanup.sh
    assert_unit_slot_matches file-gateway-network.service '' "$QUADLET_DIR/file-gateway.network" 'file-gateway'

    if command -v podman >/dev/null 2>&1; then
        validate_existing_container nginx docker.io/library/nginx \
            '/etc/file-gateway/nginx.conf:/etc/nginx/nginx.conf'
        validate_existing_container tusd docker.io/tusproject/tusd "$INBOX:/data"
    fi

    stop_matching_unit tus-publish.path 'Watch for completed tusd uploads' \
        /etc/systemd/system/tus-publish.path ''
    stop_matching_unit tus-cleanup.timer 'Hourly cleanup of incomplete tusd uploads' \
        /etc/systemd/system/tus-cleanup.timer ''
    stop_matching_unit tus-publish.service 'Move completed tusd uploads to outbox' \
        /etc/systemd/system/tus-publish.service /usr/local/bin/tus-publish-completed.sh
    stop_matching_unit tus-cleanup.service 'Remove expired incomplete tusd uploads' \
        /etc/systemd/system/tus-cleanup.service /usr/local/bin/tus-cleanup.sh
    stop_matching_unit nginx.service 'nginx file gateway' "$QUADLET_DIR/nginx.container" docker.io/library/nginx
    stop_matching_unit tusd.service 'tusd resumable upload server' "$QUADLET_DIR/tusd.container" docker.io/tusproject/tusd
    stop_matching_unit file-gateway-network.service '' "$QUADLET_DIR/file-gateway.network" 'file-gateway'

    if command -v podman >/dev/null 2>&1; then
        remove_matching_container nginx
        remove_matching_container tusd
    fi
}

install_dependencies() {
    command -v apt-get >/dev/null 2>&1 || fail 'This bootstrap script requires Debian or a compatible apt-based system.'
    log 'Installing Podman, jq, and curl'
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y podman jq curl
}

check_platform() {
    local version rootless selinux_mode

    if command -v getenforce >/dev/null 2>&1; then
        if selinux_mode=$(getenforce 2>/dev/null); then
            [[ "$selinux_mode" == Disabled ]] || fail "SELinux must be Disabled; found $selinux_mode."
        fi
    fi

    version=$(podman version --format '{{.Client.Version}}')
    version=${version#v}
    dpkg --compare-versions "$version" ge 4.4 || fail "Podman $version is too old; Quadlet requires 4.4 or newer."

    rootless=$(podman info --format '{{.Host.Security.Rootless}}')
    [[ "$rootless" == false ]] || fail 'Run this deployment with rootful Podman.'
}

create_service_user_and_directories() {
    if ! getent passwd "$SERVICE_USER" >/dev/null; then
        if getent group "$SERVICE_USER" >/dev/null; then
            useradd --system --gid "$SERVICE_USER" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        else
            useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        fi
    fi

    [[ "$(id -gn "$SERVICE_USER")" == "$SERVICE_USER" ]] || \
        fail "The primary group for $SERVICE_USER must also be named $SERVICE_USER."
    SVC_UID=$(id -u "$SERVICE_USER")
    SVC_GID=$(id -g "$SERVICE_USER")
    export SVC_UID SVC_GID

    install -d -o "$SERVICE_USER" -g "$SVC_GID" -m 0750 "$INBOX" "$EVENTS"
    install -d -o "$SERVICE_USER" -g "$SVC_GID" -m 0755 "$OUTBOX"
    install -d -m 0755 "$CONFIG_DIR" "$HOOK_DIR" "$QUADLET_DIR"
    install -d -m 0755 /usr/local/bin
}

write_nginx_configuration() {
    cat > "$CONFIG_DIR/nginx.conf" <<'EOF'
user  nginx;
worker_processes auto;
pid /var/run/nginx.pid;
error_log /dev/stderr warn;

events { worker_connections 1024; }

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    access_log    /dev/stdout;

    server {
        listen 8080;
        server_name _;
        client_max_body_size 2g;

        location /files/ {
            alias /srv/outbox/;
            autoindex off;
            sendfile on;
            tcp_nopush on;
        }

        location /upload/ {
            proxy_pass http://tusd:8080;
            proxy_http_version 1.1;
            proxy_request_buffering off;
            proxy_buffering off;
            proxy_read_timeout 1h;
            proxy_send_timeout 1h;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
}
EOF
}

write_quadlet_units() {
    cat > "$QUADLET_DIR/file-gateway.network" <<'EOF'
[Network]
NetworkName=file-gateway
EOF

    cat > "$QUADLET_DIR/tusd.container" <<EOF
[Unit]
Description=tusd resumable upload server

[Container]
ContainerName=tusd
Image=docker.io/tusproject/tusd:latest
Network=file-gateway.network
User=$SVC_UID
Group=$SVC_GID
Volume=$INBOX:/data
Volume=$EVENTS:/events
Volume=$HOOK_DIR:/hooks:ro
Exec=-upload-dir=/data -base-path=/upload/ -behind-proxy -disable-download -max-size=2147483648 -hooks-dir=/hooks -hooks-enabled-events=post-finish

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    cat > "$QUADLET_DIR/nginx.container" <<'EOF'
[Unit]
Description=nginx file gateway
Requires=tusd.service
After=tusd.service

[Container]
ContainerName=nginx
Image=docker.io/library/nginx:stable
Network=file-gateway.network
PublishPort=8080:8080
Volume=/etc/file-gateway/nginx.conf:/etc/nginx/nginx.conf:ro
Volume=/mnt/outbox:/srv/outbox:ro

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
EOF
}

write_publishing_service() {
    cat > "$HOOK_DIR/post-finish" <<'EOF'
#!/bin/sh
set -eu

case "${TUS_ID:-}" in
    ''|*[!A-Za-z0-9_-]*) echo "Invalid tusd upload ID" >&2; exit 1 ;;
esac

: > "/events/$TUS_ID.done"
printf '{}\n'
EOF
    chmod 0755 "$HOOK_DIR/post-finish"

    cat > /usr/local/bin/tus-publish-completed.sh <<'EOF'
#!/bin/bash
set -eu

INBOX=/mnt/inbox
OUTBOX=/mnt/outbox
EVENTS=/mnt/file-gateway-events
shopt -s nullglob

for event in "$EVENTS"/*.done; do
    id=${event##*/}
    id=${id%.done}
    case "$id" in
        ''|*[!A-Za-z0-9_-]*) echo "Invalid upload event: $event" >&2; exit 1 ;;
    esac

    source="$INBOX/$id"
    info="$source.info"
    destination="$OUTBOX/$id"

    if [ -f "$source" ]; then
        [ -f "$info" ] || { echo "Upload info missing: $info" >&2; exit 1; }
        [ ! -e "$destination" ] || { echo "Destination already exists: $destination" >&2; exit 1; }
        mv -- "$source" "$destination"
    elif [ ! -f "$destination" ]; then
        echo "Upload data missing from inbox and outbox: $id" >&2
        exit 1
    fi

    rm -f -- "$info"
    rm -- "$event"
done
EOF
    chmod 0755 /usr/local/bin/tus-publish-completed.sh

    cat > /etc/systemd/system/tus-publish.service <<'EOF'
[Unit]
Description=Move completed tusd uploads to outbox

[Service]
Type=oneshot
User=filesvc
Group=filesvc
ExecStart=/usr/local/bin/tus-publish-completed.sh
EOF

    cat > /etc/systemd/system/tus-publish.path <<'EOF'
[Unit]
Description=Watch for completed tusd uploads

[Path]
PathExistsGlob=/mnt/file-gateway-events/*.done
Unit=tus-publish.service

[Install]
WantedBy=multi-user.target
EOF
}

write_cleanup_service() {
    cat > /usr/local/bin/tus-cleanup.sh <<'EOF'
#!/bin/bash
set -eu
DIR=/mnt/inbox
MAX_AGE_MIN=1440

for info in "$DIR"/*.info; do
    [ -e "$info" ] || continue
    data=${info%.info}
    [ -f "$data" ] || continue
    [ -n "$(find "$data" -maxdepth 0 -mmin +"$MAX_AGE_MIN")" ] || continue
    expected=$(jq -r '.Size // empty' "$info") || continue
    [ -n "$expected" ] || continue
    if [ "$(stat -c %s "$data")" -lt "$expected" ]; then
        echo "Removing incomplete upload: $data"
        rm -f -- "$data" "$info"
    fi
done
EOF
    chmod 0755 /usr/local/bin/tus-cleanup.sh

    cat > /etc/systemd/system/tus-cleanup.service <<'EOF'
[Unit]
Description=Remove expired incomplete tusd uploads

[Service]
Type=oneshot
User=filesvc
Group=filesvc
ExecStart=/usr/local/bin/tus-cleanup.sh
EOF

    cat > /etc/systemd/system/tus-cleanup.timer <<'EOF'
[Unit]
Description=Hourly cleanup of incomplete tusd uploads

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

start_services() {
    systemctl daemon-reload
    systemctl enable --now tus-publish.path
    systemctl enable --now tus-cleanup.timer
    systemctl start nginx.service
    systemctl is-active --quiet tusd.service || fail 'tusd.service did not start.'
    systemctl is-active --quiet nginx.service || fail 'nginx.service did not start.'
    systemctl is-active --quiet tus-publish.path || fail 'tus-publish.path did not start.'
    systemctl is-active --quiet tus-cleanup.timer || fail 'tus-cleanup.timer did not start.'
    systemctl --no-pager --full status tusd.service nginx.service tus-publish.path tus-cleanup.timer
    podman ps
}

verify_gateway() {
    local headers location upload_id attempt published=0 download_file download_name download_status listing_status
    trap cleanup_test_artifacts EXIT

    curl --fail --silent --show-error --request OPTIONS http://localhost:8080/upload/ --output /dev/null
    headers=$(curl --fail --silent --show-error --dump-header - --output /dev/null \
        --request POST http://localhost:8080/upload/ \
        --header 'Tus-Resumable: 1.0.0' --header 'Upload-Length: 5')
    location=$(awk 'tolower($1) == "location:" { sub(/\r$/, "", $2); print $2; exit }' <<< "$headers")
    [[ -n "$location" ]] || fail 'tusd did not return an upload Location.'
    upload_id=${location##*/}
    [[ "$upload_id" =~ ^[A-Za-z0-9_-]+$ ]] || fail 'Upload URL contains an unexpected ID.'
    TEST_UPLOAD_ID=$upload_id

    curl --fail --silent --show-error --request PATCH "$location" \
        --header 'Tus-Resumable: 1.0.0' --header 'Upload-Offset: 0' \
        --header 'Content-Type: application/offset+octet-stream' --data-binary 'hello' \
        --output /dev/null

    for attempt in {1..10}; do
        if [[ -f "$OUTBOX/$upload_id" && ! -e "$INBOX/$upload_id.info" ]]; then
            published=1
            break
        fi
        sleep 1
    done
    (( published == 1 )) || fail 'Completed upload was not moved to the outbox.'

    local owner
    owner=$(stat -c '%u:%g' "$OUTBOX/$upload_id")
    [[ "$owner" == "$SVC_UID:$SVC_GID" ]] || fail 'Published upload has unexpected ownership.'

    download_file=$(mktemp "$OUTBOX/gateway-bootstrap-test.XXXXXX")
    TEST_DOWNLOAD_FILE=$download_file
    download_name=${download_file##*/}
    printf 'test\n' > "$download_file"
    chown "$SVC_UID:$SVC_GID" "$download_file"
    chmod 0644 "$download_file"

    download_status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        "http://localhost:8080/files/$download_name")
    [[ "$download_status" == 200 ]] || fail "Download check returned HTTP $download_status, expected 200."

    listing_status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        http://localhost:8080/files/)
    [[ "$listing_status" == 403 ]] || fail "Directory listing returned HTTP $listing_status, expected 403."

    /usr/local/bin/tus-cleanup.sh
    log 'TUS upload, publish, download, no-listing, and cleanup checks passed.'
}

main() {
    require_root
    command -v systemctl >/dev/null 2>&1 || fail 'systemctl is required.'
    [[ -d /run/systemd/system ]] || fail 'systemd is not running.'
    command -v apt-get >/dev/null 2>&1 || fail 'This script requires Debian or a compatible apt-based system.'

    install_dependencies
    check_platform
    check_existing_deployment_files
    remove_existing_deployment

    create_service_user_and_directories
    write_nginx_configuration
    write_quadlet_units
    write_publishing_service
    write_cleanup_service
    start_services
    verify_gateway

    log 'File gateway deployment completed. Existing inbox and outbox contents were preserved except expired incomplete uploads removed by the configured cleanup policy.'
}

main "$@"