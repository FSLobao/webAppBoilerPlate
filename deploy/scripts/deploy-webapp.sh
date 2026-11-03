#!/usr/bin/env bash
# Deploy the webapp stack (webapp-db, webapp, app-proxy) with Quadlet .kube units.
#
# Usage: sudo deploy/scripts/deploy-webapp.sh [--no-build]
#
# Idempotent: versioned configuration is reinstalled on every run; secrets and
# volumes are never overwritten or removed. Runs as root on the Podman host.
set -Eeuo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
readonly REPO_ROOT
readonly SOURCE_DIR="${REPO_ROOT}/deploy/webapp"
readonly WEBAPP_ETC=/etc/webapp
readonly SECRETS_DIR="${WEBAPP_ETC}/secrets"
readonly PROXY_ETC=/etc/app-proxy
readonly QUADLET_DIR=/etc/containers/systemd
readonly IMAGE=localhost/webapp:0.1.0
readonly POSTGRES_UID=999
readonly WEBAPP_UID=10001
readonly UNITS=(webapp-db.service webapp.service app-proxy.service)
readonly HEALTH_URL=http://127.0.0.1:8080/webapp/api/health

# Prints a message to stderr and returns 1.
# Arguments: $1 - message.
# Output streams: stderr.
# Return status: 1.
fail() {
  printf 'ERROR: %s\n' "$1" >&2
  return 1
}
# ---------------------------------- #

# Prints a progress line to stdout.
# Arguments: $1 - message.
# Output streams: stdout.
# Return status: 0.
log() {
  printf '==> %s\n' "$1"
}
# ---------------------------------- #

# Checks host prerequisites without changing anything.
# Arguments: none.
# Global state read: SOURCE_DIR, REPO_ROOT.
# Output streams: diagnostics to stderr.
# Return status: 0 when all checks pass, 1 otherwise.
preflight() {
  (( EUID == 0 )) || fail "Run as root (rootful Podman and /etc are required)." || return
  local command_name
  for command_name in podman systemctl curl openssl install; do
    command -v "${command_name}" >/dev/null || fail "Missing command: ${command_name}" || return
  done
  if command -v getenforce >/dev/null; then
    local selinux_mode
    selinux_mode=$(getenforce) || return
    [[ "${selinux_mode}" == "Disabled" ]] \
      || fail "SELinux is ${selinux_mode}; the contract expects Disabled (not changed here)." || return
  fi
  local dns_enabled
  dns_enabled=$(podman network inspect podman --format '{{.DNSEnabled}}') \
    || fail "Default network 'podman' not found." || return
  [[ "${dns_enabled}" == "true" ]] || fail "Network 'podman' has DNS disabled." || return
  [[ -d "${SOURCE_DIR}/kube" && -f "${REPO_ROOT}/webapp/Containerfile" ]] \
    || fail "Repository files not found under ${REPO_ROOT}." || return
  [[ -f "${REPO_ROOT}/webapp/frontend/index.html" ]] \
    || fail "Missing webapp/frontend/index.html." || return
}
# ---------------------------------- #

# Writes a new random secret file unless it already exists.
# Arguments: $1 - path; $2 - owner UID; $3 - value (empty to generate).
# Output streams: stdout progress.
# Return status: 0 on success, nonzero on error.
ensure_secret() {
  local path=$1 owner=$2 value=${3:-}
  if [[ -e "${path}" ]]; then
    chown -- "${owner}:${owner}" "${path}"
    chmod -- 0400 "${path}"
    return 0
  fi
  if [[ -z "${value}" ]]; then
    value=$(openssl rand -hex 24) || return
  fi
  local staged
  staged=$(mktemp --tmpdir="${SECRETS_DIR}" .secret.XXXXXX) || return
  printf '%s' "${value}" > "${staged}"
  chown -- "${owner}:${owner}" "${staged}"
  chmod -- 0400 "${staged}"
  mv -T --no-clobber -- "${staged}" "${path}"
  log "Created secret ${path}"
}
# ---------------------------------- #

# Creates missing secrets; the API password is stored twice with different owners
# because PostgreSQL (UID 999) and the API (UID 10001) each read their own copy.
# Arguments: none.
# Global state read: SECRETS_DIR, POSTGRES_UID, WEBAPP_UID.
# Output streams: stdout progress, stderr diagnostics.
# Return status: 0 on success, nonzero on error.
ensure_secrets() {
  install -d -m 0700 -o root -g root -- "${SECRETS_DIR}"
  local db_volume_exists=false
  podman volume exists webapp-db-data && db_volume_exists=true
  if [[ "${db_volume_exists}" == true && ! -e "${SECRETS_DIR}/postgres-password" ]]; then
    fail "Volume webapp-db-data exists but ${SECRETS_DIR}/postgres-password is missing; restore it." \
      || return
  fi
  ensure_secret "${SECRETS_DIR}/postgres-password" "${POSTGRES_UID}" || return

  local api_password=""
  if [[ -e "${SECRETS_DIR}/api-db-password" ]]; then
    api_password=$(<"${SECRETS_DIR}/api-db-password")
  elif [[ -e "${SECRETS_DIR}/db-init-api-password" ]]; then
    api_password=$(<"${SECRETS_DIR}/db-init-api-password")
  elif [[ "${db_volume_exists}" == true ]]; then
    fail "Volume webapp-db-data exists but the API password files are missing; restore them." \
      || return
  else
    api_password=$(openssl rand -hex 24) || return
  fi
  ensure_secret "${SECRETS_DIR}/db-init-api-password" "${POSTGRES_UID}" "${api_password}" || return
  ensure_secret "${SECRETS_DIR}/api-db-password" "${WEBAPP_UID}" "${api_password}" || return
}
# ---------------------------------- #

# Installs versioned configuration and Quadlet units, replacing older copies.
# Arguments: none.
# Global state read: path constants.
# Output streams: stdout progress.
# Return status: 0 on success, nonzero on error.
install_config() {
  log "Installing configuration"
  install -d -m 0755 -- "${WEBAPP_ETC}/kube" "${WEBAPP_ETC}/db-init" \
    "${PROXY_ETC}/templates" "${PROXY_ETC}/apps.d" "${QUADLET_DIR}"
  install -m 0644 -t "${WEBAPP_ETC}/kube" -- "${SOURCE_DIR}"/kube/*.yaml
  install -m 0644 -t "${WEBAPP_ETC}/db-init" -- "${REPO_ROOT}"/webapp/database/init/*.sql
  install -m 0644 -t "${PROXY_ETC}/templates" -- "${SOURCE_DIR}/nginx/default.conf.template"
  install -m 0644 -t "${PROXY_ETC}/apps.d" -- "${SOURCE_DIR}/nginx/apps.d/webapp.conf"
  install -m 0644 -t "${QUADLET_DIR}" -- "${SOURCE_DIR}"/quadlet/*.kube
}
# ---------------------------------- #

# Creates the image volume owned by the API user. The uid/gid options pin the
# ownership; without them Podman re-chowns the volume to root whenever the NGINX
# pod mounts it, and the API can no longer write images.
# Arguments: none.
# Global state read: WEBAPP_UID.
# Output streams: stdout progress, stderr diagnostics.
# Return status: 0 on success, 1 when an existing volume lacks the options.
ensure_image_volume() {
  if ! podman volume exists webapp-images; then
    podman volume create --opt "o=uid=${WEBAPP_UID},gid=${WEBAPP_UID}" webapp-images >/dev/null
    log "Created volume webapp-images"
    return 0
  fi
  local volume_uid
  volume_uid=$(podman volume inspect webapp-images --format '{{.Options.UID}}') || return
  [[ "${volume_uid}" == "${WEBAPP_UID}" ]] \
    || fail "Volume webapp-images lacks uid=${WEBAPP_UID}; back it up and recreate it." || return
}
# ---------------------------------- #

# Builds the webapp image from the repository root.
# Arguments: none.
# Global state read: REPO_ROOT, IMAGE.
# Output streams: podman build output.
# Return status: podman build status.
build_image() {
  log "Building ${IMAGE}"
  podman build --file "${REPO_ROOT}/webapp/Containerfile" --tag "${IMAGE}" -- "${REPO_ROOT}"
}
# ---------------------------------- #

# Regenerates Quadlet units and (re)starts the stack in dependency order.
# The database is only started, so a deploy does not interrupt it needlessly.
# Arguments: none.
# Global state read: UNITS.
# Output streams: stdout progress, systemd diagnostics.
# Return status: 0 on success, nonzero on error.
start_units() {
  log "Reloading systemd and starting units"
  systemctl daemon-reload
  systemctl start webapp-db.service
  systemctl restart webapp.service app-proxy.service
}
# ---------------------------------- #

# Waits until the API answers healthy through the shared proxy.
# Arguments: none.
# Global state read: HEALTH_URL.
# Output streams: stdout progress, stderr diagnostics.
# Return status: 0 when healthy within 90 s, 1 otherwise.
wait_healthy() {
  local _attempt
  for _attempt in {1..45}; do
    if curl --silent --fail --max-time 3 "${HEALTH_URL}" >/dev/null; then
      log "Healthy: ${HEALTH_URL}"
      return 0
    fi
    sleep 2
  done
  systemctl --no-pager --lines=20 status "${UNITS[@]}" >&2 || true
  fail "API not healthy after 90 s: ${HEALTH_URL}"
}
# ---------------------------------- #

# Entry point.
# Arguments: [--no-build] to reuse the existing image; -h|--help.
# Output streams: stdout progress, stderr diagnostics.
# Return status: 0 on success, nonzero on error.
main() {
  local build=true
  case "${1:-}" in
    "") ;;
    --no-build) build=false ;;
    -h | --help)
      printf 'Usage: %s [--no-build]\n' "$0"
      return 0
      ;;
    *)
      printf 'Usage: %s [--no-build]\n' "$0" >&2
      return 2
      ;;
  esac

  preflight
  if [[ "${build}" == true ]]; then
    build_image
  else
    podman image exists "${IMAGE}" || fail "Image ${IMAGE} not found; run without --no-build."
  fi
  ensure_secrets
  install_config
  ensure_image_volume
  start_units
  wait_healthy
  systemctl --no-pager --plain list-units "${UNITS[@]}"
  log "App: http://localhost:8080/webapp/index.html"
}
# ---------------------------------- #

main "$@"
