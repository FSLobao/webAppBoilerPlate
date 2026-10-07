# File Gateway: nginx + tusd on Podman (rootful, Quadlet) – Debian

Single HTTP endpoint on port **8080**:

| Path        | Served by | Purpose                                   | Host folder    |
|-------------|-----------|-------------------------------------------|----------------|
| `/files/…`  | nginx     | Download (static, no directory listing)   | `/mnt/outbox`  |
| `/upload/…` | tusd      | Resumable upload (TUS), max 2 GB          | `/mnt/inbox`   |

Only nginx publishes a port. tusd is reachable only on the internal Podman network. No TLS and no authentication (handled by the upstream HTTPS proxy / secure network).

Run every command as **root**.

For automated setup, run `sudo ./scripts/bootstrap-file-gateway.sh` from the repository root. The script removes matching gateway containers and services before recreating them. It preserves inbox and outbox files, except incomplete uploads older than 24 hours removed by the configured cleanup policy.

---

## 1. Prerequisites

```bash
apt update && apt install -y podman jq
podman --version        # Quadlet requires Podman >= 4.4 (Debian 13 ships 5.x; Debian 12 ships 4.3 -> not enough)
getenforce 2>/dev/null || echo "SELinux not installed"   # must be absent or Disabled
```

No `:Z` / `:z` volume labels are used since SELinux is disabled.

## 2. Service user and host folders

```bash
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin filesvc
export SVC_UID=$(id -u filesvc) SVC_GID=$(id -g filesvc)
echo "UID=$SVC_UID GID=$SVC_GID"

install -d -o filesvc -g filesvc -m 0750 /mnt/inbox     # written by tusd (runs as filesvc)
install -d -o filesvc -g filesvc -m 0755 /mnt/outbox    # read by nginx (stock image, world-readable)
install -d -o filesvc -g filesvc -m 0750 /mnt/file-gateway-events
install -d -m 0755 /etc/file-gateway
install -d -m 0755 /etc/file-gateway/tusd-hooks
```

In rootful Podman there is no UID remapping, so the same UID/GID is used inside the container and on the host. **tusd** and the host-side publish service run as `filesvc`, so uploaded files retain that ownership when moved. **nginx** runs with the stock image defaults (master as root, workers as the image's `nginx` user) and reads `/mnt/outbox` through the world-readable permissions (`0755` folders, `0644` files).

## 3. nginx configuration

```bash
cat > /etc/file-gateway/nginx.conf <<'EOF'
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

        # Download: plain folder mapping, no indexing
        location /files/ {
            alias /srv/outbox/;
            autoindex off;
            sendfile on;
            tcp_nopush on;
        }

        # Upload: TUS
        location /upload/ {
            proxy_pass http://tusd:8080;          # no URI part: path is passed unchanged
            proxy_http_version 1.1;
            proxy_request_buffering off;          # required for TUS
            proxy_buffering off;
            proxy_read_timeout  1h;
            proxy_send_timeout  1h;
            proxy_set_header Host              $host;
            proxy_set_header X-Forwarded-Host  $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        }
    }
}
EOF
```

## 4. Quadlet units

Files go in `/etc/containers/systemd/`. The tusd heredoc below is **unquoted** so `$SVC_UID` / `$SVC_GID` are expanded; run it in the same shell as step 2.

**Network**

```bash
cat > /etc/containers/systemd/file-gateway.network <<'EOF'
[Network]
NetworkName=file-gateway
EOF
```

**tusd** (uploads, internal only)

```bash
cat > /etc/containers/systemd/tusd.container <<EOF
[Unit]
Description=tusd resumable upload server

[Container]
ContainerName=tusd
Image=docker.io/tusproject/tusd:latest
Network=file-gateway.network
User=$SVC_UID
Group=$SVC_GID
Volume=/mnt/inbox:/data
Volume=/mnt/file-gateway-events:/events
Volume=/etc/file-gateway/tusd-hooks:/hooks:ro
Exec=-upload-dir=/data -base-path=/upload/ -behind-proxy -disable-download -max-size=2147483648 -hooks-dir=/hooks -hooks-enabled-events=post-finish

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
EOF
```

`-max-size` = 2 GiB in bytes. `-disable-download` keeps tusd upload-only; downloads go through nginx.

**nginx** (single gateway)

```bash
cat > /etc/containers/systemd/nginx.container <<'EOF'
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
```

Tip: pin image tags (e.g. `tusd:v2.x`, `nginx:1.x`) instead of `latest`/`stable` once the setup is validated.

## 5. Publish completed uploads

tusd supports a `post-finish` file hook. The hook creates a marker, and a systemd path unit starts a oneshot service to move that upload and delete its `.info` file. This avoids polling.

```bash
cat > /etc/file-gateway/tusd-hooks/post-finish <<'EOF'
#!/bin/sh
set -eu

case "${TUS_ID:-}" in
    ''|*[!A-Za-z0-9_-]*) echo "Invalid tusd upload ID" >&2; exit 1 ;;
esac

: > "/events/$TUS_ID.done"
printf '{}\n'
EOF
chmod 0755 /etc/file-gateway/tusd-hooks/post-finish

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
```

The hook runs as `filesvc` in the tusd container. tusd does not retry failed post-finish hooks; the marker remains for manual retry with `systemctl start tus-publish.service`.

## 6. Start and enable

```bash
systemctl daemon-reload                 # Quadlet generates the .service units
systemctl enable --now tus-publish.path
systemctl start nginx.service           # also starts tusd.service and the network
systemctl status tusd.service nginx.service tus-publish.path --no-pager
podman ps
```

Generated units are enabled automatically through the `[Install]` section (start on boot).

## 7. Cleanup of incomplete uploads

tusd's binary has no built-in expiry for local storage, so a systemd timer removes stalled, incomplete uploads (default: no activity for 24 h).

```bash
cat > /usr/local/bin/tus-cleanup.sh <<'EOF'
#!/bin/bash
# Remove incomplete tusd uploads with no data written for MAX_AGE_MIN minutes.
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

systemctl daemon-reload
systemctl enable --now tus-cleanup.timer
```

Completed uploads are never touched. Check the `.info` format against your tusd version with a test upload (step 8) before relying on the cleanup.

## 8. Verification

```bash
# Gateway and TUS capabilities
curl -i -X OPTIONS http://localhost:8080/upload/

# Create a 5-byte upload and send its content
LOC=$(curl -si -X POST http://localhost:8080/upload/ \
      -H "Tus-Resumable: 1.0.0" -H "Upload-Length: 5" \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="location"{print $2}')
echo "Upload URL: $LOC"
curl -i -X PATCH "$LOC" -H "Tus-Resumable: 1.0.0" \
     -H "Upload-Offset: 0" -H "Content-Type: application/offset+octet-stream" \
     --data-binary "hello"
UPLOAD_ID=${LOC##*/}
for attempt in $(seq 1 10); do
    [ -f "/mnt/outbox/$UPLOAD_ID" ] && break
    sleep 1
done
test -f "/mnt/outbox/$UPLOAD_ID" || { echo "Upload was not published" >&2; exit 1; }
test ! -e "/mnt/inbox/$UPLOAD_ID.info" || { echo "Upload info file remains" >&2; exit 1; }
ls -l /mnt/inbox /mnt/outbox

# Download path and no directory listing
echo "test" > /mnt/outbox/test.txt && chown filesvc:filesvc /mnt/outbox/test.txt
curl -i http://localhost:8080/files/test.txt      # 200
curl -i http://localhost:8080/files/              # 403 (no index)

# Manual cleanup run
/usr/local/bin/tus-cleanup.sh
```

The uploaded file should be in `/mnt/outbox` and owned by `filesvc:filesvc`; its matching `.info` file should be gone from `/mnt/inbox`.

## 9. Notes and troubleshooting

- **Inbox vs. outbox:** tusd stores uploads as `<id>` plus `<id>.info` in `/mnt/inbox`. The post-finish hook triggers the service, which moves `<id>` to `/mnt/outbox` and deletes `<id>.info`.
- **Logs:** `journalctl -u tusd.service -u nginx.service -f` or `podman logs nginx`.
- **Download returns 403/404 for an existing file:** nginx workers run as the image's `nginx` user, so files in `/mnt/outbox` must be world-readable (`chmod 0644` files, `0755` folders).
- **Upload URLs wrong behind the future HTTPS proxy:** that proxy must send `X-Forwarded-Proto` / `X-Forwarded-Host`; in `nginx.conf` forward `$http_x_forwarded_proto` and `$http_x_forwarded_host` instead of `$scheme` / `$http_host`.
- **Apply config changes:** edit `/etc/file-gateway/nginx.conf` → `systemctl restart nginx.service`; edit a `.container` file → `systemctl daemon-reload && systemctl restart <name>.service`.
- **Remove everything:** `systemctl stop nginx tusd`, delete the files in `/etc/containers/systemd/`, `systemctl daemon-reload`.
