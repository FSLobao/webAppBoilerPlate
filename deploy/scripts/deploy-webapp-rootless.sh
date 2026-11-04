#!/usr/bin/env bash
# Deploy the webapp stack (webapp-db, webapp, app-proxy) with user Quadlet units.
#
# Usage: deploy/scripts/deploy-webapp-rootless.sh --source DIR [--no-build]
# Stage the repository as root with:
#   git archive HEAD | tar -x -C <dir>
# Then chown the staged tree to podman_user.
#
# Idempotent: generated configuration is reinstalled; secrets and volumes are
# never overwritten or removed. Runs as podman_user with rootless Podman.
set -Eeuo pipefail

readonly EXPECTED_USER=podman_user
readonly EXPECTED_UID=1001
readonly IMAGE=localhost/webapp:0.1.0
readonly POSTGRES_UID=999
readonly WEBAPP_UID=10001
readonly UNITS=(webapp-db.service webapp.service app-proxy.service)
readonly PODS=(webapp-db webapp app-proxy)
readonly BASE_IMAGES=(
  docker.io/library/postgres:18-trixie
  docker.io/library/nginx:1.28-alpine
  ghcr.io/astral-sh/uv:0.9-python3.13-trixie-slim
  docker.io/library/python:3.13-slim-trixie
)
readonly HEALTH_URL=http://127.0.0.1:8080/webapp/api/health

SOURCE_ARG=""
SOURCE_DIR=""
NO_BUILD=false
HOME_DIR=""
CONFIG_DIR=""
KUBE_DIR=""
DB_INIT_DIR=""
PROXY_DIR=""
QUADLET_DIR=""
SECRETS_DIR=""
DB_VOLUME_EXISTS=false
TEMP_FILES=()

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

# Prints usage and the required source-staging instructions.
# Arguments: none.
# Output streams: stdout.
# Return status: 0.
usage() {
  printf 'Usage: %s --source DIR [--no-build]\n' "${0##*/}"
  printf 'Stage the repository as root with:\n'
  printf '  git archive HEAD | tar -x -C <dir>\n'
  printf 'Then chown the staged tree to podman_user.\n'
}
# ---------------------------------- #

# Parses the source directory and optional image-build flag.
# Arguments: CLI arguments.
# Global state changed: SOURCE_ARG, NO_BUILD.
# Output streams: usage and diagnostics on stderr for invalid arguments.
# Return status: 0 on success, 2 for invalid arguments.
parse_args() {
  while (($#)); do
    case "$1" in
      --source)
        if (($# < 2)) || [[ -z "$2" ]]; then
          usage >&2
          fail "--source requires a repository directory."
          return 2
        fi
        [[ -z "${SOURCE_ARG}" ]] || {
          fail "--source may be specified only once."
          return 2
        }
        SOURCE_ARG=$2
        shift 2
        ;;
      --no-build)
        NO_BUILD=true
        shift
        ;;
      *)
        usage >&2
        fail "Unknown option: $1"
        return 2
        ;;
    esac
  done

  [[ -n "${SOURCE_ARG}" ]] || {
    usage >&2
    fail "--source is required."
    return 2
  }
}
# ---------------------------------- #

# Resolves the supplied repository directory without using a default checkout.
# Arguments: none.
# Global state read: SOURCE_ARG.
# Global state changed: SOURCE_DIR.
# Output streams: diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
resolve_source_dir() {
  if ! SOURCE_DIR=$(cd -- "${SOURCE_ARG}" && pwd -P); then
    fail "Cannot read source directory: ${SOURCE_ARG}"
    return 1
  fi
}
# ---------------------------------- #

# Resolves all managed paths beneath the current user's home directory.
# Arguments: none.
# Global state read: HOME.
# Global state changed: HOME_DIR, CONFIG_DIR, KUBE_DIR, DB_INIT_DIR, PROXY_DIR,
#   QUADLET_DIR, SECRETS_DIR.
# Output streams: diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
set_user_paths() {
  [[ -n "${HOME:-}" && "${HOME}" == /* ]] || {
    fail "HOME must be set to an absolute path."
    return 1
  }
  if ! HOME_DIR=$(cd -- "${HOME}" && pwd -P); then
    fail "Cannot access the user's home directory."
    return 1
  fi
  [[ -O "${HOME_DIR}" ]] || {
    fail "The home directory is not owned by podman_user."
    return 1
  }

  CONFIG_DIR="${HOME_DIR}/.config/webapp"
  KUBE_DIR="${CONFIG_DIR}/kube"
  DB_INIT_DIR="${CONFIG_DIR}/db-init"
  PROXY_DIR="${CONFIG_DIR}/proxy"
  QUADLET_DIR="${HOME_DIR}/.config/containers/systemd"
  SECRETS_DIR="${HOME_DIR}/.local/share/webapp/secrets"
}
# ---------------------------------- #

# Checks whether a named Podman volume exists, distinguishing absence from error.
# Arguments: $1 - volume name.
# Output streams: Podman diagnostics on stderr.
# Return status: 0 if present, 1 if absent, 2 on inspection error.
volume_exists() {
  local volume_name=$1
  local command_status
  if podman volume exists "${volume_name}"; then
    return 0
  else
    command_status=$?
  fi

  if ((command_status == 1)); then
    return 1
  fi
  fail "Could not inspect volume ${volume_name}."
  return 2
}
# ---------------------------------- #

# Verifies an existing image volume has the API UID and GID without changing it.
# Arguments: none.
# Global state read: WEBAPP_UID.
# Output streams: Podman diagnostics on stderr.
# Return status: 0 when ownership is correct, nonzero otherwise.
verify_image_volume() {
  local mountpoint
  local owner
  mountpoint=$(podman volume inspect webapp-images --format '{{.Mountpoint}}') || {
    fail "Could not inspect volume webapp-images."
    return 1
  }
  [[ -n "${mountpoint}" && "${mountpoint}" == /* && "${mountpoint}" != / ]] || {
    fail "Volume webapp-images has an invalid mountpoint."
    return 1
  }
  owner=$(podman unshare stat -c '%u:%g' -- "${mountpoint}") || {
    fail "Could not inspect ownership of volume webapp-images."
    return 1
  }
  [[ "${owner}" == "${WEBAPP_UID}:${WEBAPP_UID}" ]] || {
    fail "Volume webapp-images must be owned by ${WEBAPP_UID}:${WEBAPP_UID}; it was not changed."
    return 1
  }
}
# ---------------------------------- #

# Validates source files, user paths, rootless services, network, cgroups, and volumes.
# Arguments: none.
# Global state read: SOURCE_DIR, NO_BUILD, IMAGE, EXPECTED_USER, EXPECTED_UID.
# Global state changed: runtime bus variables, user paths, DB_VOLUME_EXISTS.
# Output streams: diagnostics to stderr.
# Return status: 0 when all checks pass, nonzero otherwise.
preflight() {
  (( EUID != 0 )) || {
    fail "Run as podman_user, not root."
    return 1
  }

  local command_name
  for command_name in podman systemctl curl openssl install loginctl id grep sleep chmod mktemp mv rm stat; do
    command -v "${command_name}" >/dev/null || {
      fail "Missing command: ${command_name}"
      return 1
    }
  done

  local current_user
  local current_uid
  current_user=$(id -un) || return 1
  current_uid=$(id -u) || return 1
  [[ "${current_user}" == "${EXPECTED_USER}" && "${current_uid}" == "${EXPECTED_UID}" ]] || {
    fail "Run as ${EXPECTED_USER} (UID ${EXPECTED_UID}); current user is ${current_user} (UID ${current_uid})."
    return 1
  }
  if [[ -n "${USER:-}" && "${USER}" != "${current_user}" ]]; then
    fail "USER must match the current user ${current_user}."
    return 1
  fi
  USER=${current_user}
  export USER

  if [[ -z "${XDG_RUNTIME_DIR+x}" ]]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
  fi
  export XDG_RUNTIME_DIR
  [[ -e "${XDG_RUNTIME_DIR}/bus" ]] || {
    fail "User bus is missing: ${XDG_RUNTIME_DIR}/bus"
    return 1
  }
  if [[ -z "${DBUS_SESSION_BUS_ADDRESS+x}" ]]; then
    DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
  fi
  export DBUS_SESSION_BUS_ADDRESS

  set_user_paths || return
  validate_source_tree || return
  validate_destination_paths || return

  local linger
  linger=$(loginctl show-user "${USER}" -p Linger) || {
    fail "Could not read linger state for ${USER}."
    return 1
  }
  [[ "${linger}" == Linger=yes ]] || {
    fail "User ${USER} must have Linger=yes."
    return 1
  }

  local system_state
  if system_state=$(systemctl --user is-system-running); then
    :
  elif [[ "${system_state}" != degraded ]]; then
    fail "systemctl --user is not running or degraded (state: ${system_state:-unknown})."
    return 1
  fi
  [[ "${system_state}" == running || "${system_state}" == degraded ]] || {
    fail "systemctl --user is not running or degraded (state: ${system_state:-unknown})."
    return 1
  }

  local network_info
  network_info=$(podman network inspect gateway-vpn --format '{{.DNSEnabled}} {{range .Subnets}}{{.Subnet}}{{end}}') || {
    fail "Could not inspect network gateway-vpn."
    return 1
  }
  [[ "${network_info}" == 'true 10.90.0.0/24' ]] || {
    fail "Network gateway-vpn must have DNS enabled and subnet 10.90.0.0/24 (found: ${network_info})."
    return 1
  }

  local cgroup_manager
  cgroup_manager=$(podman info --format '{{.Host.CgroupManager}}') || {
    fail "Could not read the Podman cgroup manager."
    return 1
  }
  [[ "${cgroup_manager}" == systemd ]] || {
    fail "Podman cgroup manager must be systemd (found: ${cgroup_manager})."
    return 1
  }

  check_existing_volumes || return
  if [[ "${NO_BUILD}" == true ]] && ! podman image exists "${IMAGE}"; then
    fail "Image ${IMAGE} not found; run without --no-build."
    return 1
  fi
}
# ---------------------------------- #

# Validates the required staged repository files without reading secret data.
# Arguments: none.
# Global state read: SOURCE_DIR.
# Output streams: diagnostics to stderr.
# Return status: 0 when valid, nonzero otherwise.
validate_source_tree() {
  [[ -d "${SOURCE_DIR}/deploy/webapp" ]] || {
    fail "Missing deploy/webapp under ${SOURCE_DIR}."
    return 1
  }
  local required_file
  for required_file in \
    webapp/Containerfile \
    webapp/frontend/index.html \
    deploy/webapp/kube/webapp-db.yaml \
    deploy/webapp/kube/webapp.yaml \
    deploy/webapp/kube/app-proxy.yaml \
    deploy/webapp/quadlet/webapp-db.kube \
    deploy/webapp/quadlet/webapp.kube \
    deploy/webapp/quadlet/app-proxy.kube \
    deploy/webapp/nginx/default.conf.template \
    deploy/webapp/nginx/apps.d/webapp.conf; do
    [[ -f "${SOURCE_DIR}/${required_file}" ]] || {
      fail "Missing source file: ${SOURCE_DIR}/${required_file}"
      return 1
    }
  done

  local -a sql_sources=("${SOURCE_DIR}"/webapp/database/init/*.sql)
  [[ -f "${sql_sources[0]}" ]] || {
    fail "Missing SQL init files under ${SOURCE_DIR}/webapp/database/init."
    return 1
  }
}
# ---------------------------------- #

# Rejects symlinked or non-directory parents and non-file generated targets.
# Arguments: none.
# Global state read: all managed path globals, SOURCE_DIR.
# Output streams: diagnostics to stderr.
# Return status: 0 when targets stay within the user's home, nonzero otherwise.
validate_destination_paths() {
  local path
  local -a directories=(
    "${HOME_DIR}/.config"
    "${CONFIG_DIR}"
    "${KUBE_DIR}"
    "${DB_INIT_DIR}"
    "${PROXY_DIR}"
    "${PROXY_DIR}/templates"
    "${PROXY_DIR}/apps.d"
    "${HOME_DIR}/.config/containers"
    "${QUADLET_DIR}"
    "${HOME_DIR}/.local"
    "${HOME_DIR}/.local/share"
    "${HOME_DIR}/.local/share/webapp"
    "${SECRETS_DIR}"
  )
  for path in "${directories[@]}"; do
    if [[ -L "${path}" ]]; then
      fail "Managed directory must not be a symlink: ${path}"
      return 1
    fi
    if [[ -e "${path}" && ! -d "${path}" ]]; then
      fail "Managed path must be a directory: ${path}"
      return 1
    fi
  done

  local -a yaml_sources=("${SOURCE_DIR}"/deploy/webapp/kube/*.yaml)
  local -a quadlet_sources=("${SOURCE_DIR}"/deploy/webapp/quadlet/*.kube)
  local -a sql_sources=("${SOURCE_DIR}"/webapp/database/init/*.sql)
  local -a targets=(
    "${PROXY_DIR}/templates/default.conf.template"
    "${PROXY_DIR}/apps.d/webapp.conf"
    "${SECRETS_DIR}/postgres-password"
    "${SECRETS_DIR}/db-init-api-password"
    "${SECRETS_DIR}/api-db-password"
  )
  local source_file
  for source_file in "${yaml_sources[@]}"; do
    targets+=("${KUBE_DIR}/${source_file##*/}")
  done
  for source_file in "${quadlet_sources[@]}"; do
    targets+=("${QUADLET_DIR}/${source_file##*/}")
  done
  for source_file in "${sql_sources[@]}"; do
    targets+=("${DB_INIT_DIR}/${source_file##*/}")
  done

  for path in "${targets[@]}"; do
    if [[ -L "${path}" ]]; then
      fail "Managed file must not be a symlink: ${path}"
      return 1
    fi
    if [[ -e "${path}" && ! -f "${path}" ]]; then
      fail "Managed path must be a regular file: ${path}"
      return 1
    fi
  done

  if [[ -e "${SECRETS_DIR}" ]]; then
    [[ -O "${SECRETS_DIR}" ]] || {
      fail "Secrets directory must be owned by ${EXPECTED_USER}."
      return 1
    }
  fi
  for path in \
    "${SECRETS_DIR}/postgres-password" \
    "${SECRETS_DIR}/db-init-api-password" \
    "${SECRETS_DIR}/api-db-password"; do
    if [[ -e "${path}" || -L "${path}" ]]; then
      [[ -f "${path}" && ! -L "${path}" ]] || {
        fail "Existing secret must be a regular file: ${path}"
        return 1
      }
    fi
  done
}
# ---------------------------------- #

# Checks existing database and image volumes and their required secrets.
# Arguments: none.
# Global state read: SECRETS_DIR, WEBAPP_UID.
# Global state changed: DB_VOLUME_EXISTS.
# Output streams: Podman diagnostics on stderr.
# Return status: 0 when existing resources are safe, nonzero otherwise.
check_existing_volumes() {
  local command_status
  if volume_exists webapp-db-data; then
    DB_VOLUME_EXISTS=true
  else
    command_status=$?
    ((command_status == 1)) || return "${command_status}"
    DB_VOLUME_EXISTS=false
  fi

  if [[ "${DB_VOLUME_EXISTS}" == true ]]; then
    [[ -f "${SECRETS_DIR}/postgres-password" && ! -L "${SECRETS_DIR}/postgres-password" ]] || {
      fail "Volume webapp-db-data exists but ${SECRETS_DIR}/postgres-password is missing; restore it."
      return 1
    }
    if [[ ! -f "${SECRETS_DIR}/api-db-password" && ! -f "${SECRETS_DIR}/db-init-api-password" ]]; then
      fail "Volume webapp-db-data exists but the API password files are missing; restore them."
      return 1
    fi
  fi

  if volume_exists webapp-images; then
    verify_image_volume || return
  else
    command_status=$?
    ((command_status == 1)) || return "${command_status}"
  fi
}
# ---------------------------------- #

# Writes a transformed YAML or Quadlet copy using an atomic same-directory rename.
# Arguments: $1 - source; $2 - destination; $3 - kube or quadlet.
# Global state read: managed config paths, SECRETS_DIR.
# Output streams: diagnostics to stderr.
# Return status: 0 on success, nonzero otherwise.
write_transformed_copy() {
  local source_file=$1
  local destination=$2
  local copy_kind=$3
  local staged
  local line
  local prefix
  local host_path
  local host_path_pending=false
  staged=$(mktemp --tmpdir="${destination%/*}" .webapp-copy.XXXXXX) || return
  TEMP_FILES+=("${staged}")

  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${copy_kind}" == kube ]]; then
      if [[ "${line}" =~ ^[[:space:]]*hostPath:[[:space:]]*$ ]]; then
        [[ "${host_path_pending}" == false ]] || {
          fail "Nested hostPath in ${source_file}."
          return 1
        }
        host_path_pending=true
      elif [[ "${host_path_pending}" == true ]]; then
        if [[ "${line}" =~ ^([[:space:]]*path:[[:space:]]*)(.*)$ ]]; then
          prefix=${BASH_REMATCH[1]}
          host_path=${BASH_REMATCH[2]}
          case "${host_path}" in
            /etc/webapp/secrets/*)
              host_path="${SECRETS_DIR}/${host_path#/etc/webapp/secrets/}"
              ;;
            /etc/webapp/db-init|/etc/webapp/db-init/*)
              host_path="${DB_INIT_DIR}${host_path#/etc/webapp/db-init}"
              ;;
            /etc/app-proxy/templates|/etc/app-proxy/templates/*)
              host_path="${PROXY_DIR}${host_path#/etc/app-proxy}"
              ;;
            /etc/app-proxy/apps.d|/etc/app-proxy/apps.d/*)
              host_path="${PROXY_DIR}${host_path#/etc/app-proxy}"
              ;;
            *)
              fail "Unsupported hostPath in ${source_file}: ${host_path}"
              return 1
              ;;
          esac
          line="${prefix}${host_path}"
          host_path_pending=false
        else
          fail "Malformed hostPath in ${source_file}."
          return 1
        fi
      fi
    elif [[ "${copy_kind}" == quadlet ]]; then
      line=${line//Network=podman/Network=gateway-vpn}
      line=${line//WantedBy=multi-user.target/WantedBy=default.target}
      line=${line//\/etc\/webapp\/kube/"${KUBE_DIR}"}
      line=${line//\/etc\/app-proxy/"${PROXY_DIR}"}
    else
      fail "Unknown copy type: ${copy_kind}"
      return 1
    fi
    printf '%s\n' "${line}" >> "${staged}" || return
  done < "${source_file}" || return

  [[ "${host_path_pending}" == false ]] || {
    fail "Missing path entry in ${source_file}."
    return 1
  }
  chmod 0644 -- "${staged}" || return
  mv -f -- "${staged}" "${destination}" || return
}
# ---------------------------------- #

# Rejects generated Quadlet copies that still contain an /etc/ path.
# Arguments: $1 - generated unit file.
# Output streams: diagnostics to stderr.
# Return status: 0 when clean, nonzero otherwise.
verify_no_etc_path() {
  local unit_file=$1
  local grep_status
  if grep -Fq -- '/etc/' "${unit_file}"; then
    fail "Generated Quadlet still contains an /etc/ path: ${unit_file}"
    return 1
  else
    grep_status=$?
  fi
  ((grep_status == 1)) || {
    fail "Could not verify generated Quadlet: ${unit_file}"
    return 1
  }
}
# ---------------------------------- #

# Checks every generated YAML hostPath and prints only its path value.
# Arguments: none.
# Global state read: KUBE_DIR.
# Output streams: paths to stdout; diagnostics to stderr.
# Return status: 0 when every YAML has hostPath entries, nonzero otherwise.
report_host_paths() {
  local yaml_file
  local line
  local path
  local host_path_pending
  local found_host_path
  for yaml_file in "${KUBE_DIR}"/*.yaml; do
    [[ -f "${yaml_file}" ]] || {
      fail "No generated kube YAML files found under ${KUBE_DIR}."
      return 1
    }
    host_path_pending=false
    found_host_path=false
    while IFS= read -r line || [[ -n "${line}" ]]; do
      if [[ "${line}" =~ ^[[:space:]]*hostPath:[[:space:]]*$ ]]; then
        [[ "${host_path_pending}" == false ]] || {
          fail "Nested hostPath in ${yaml_file}."
          return 1
        }
        host_path_pending=true
        found_host_path=true
      elif [[ "${host_path_pending}" == true ]]; then
        if [[ "${line}" =~ ^[[:space:]]*path:[[:space:]]*(.*)$ ]]; then
          path=${BASH_REMATCH[1]}
          [[ -n "${path}" ]] || {
            fail "Empty hostPath in ${yaml_file}."
            return 1
          }
          printf '%s\n' "${path}"
          host_path_pending=false
        else
          fail "Malformed hostPath in ${yaml_file}."
          return 1
        fi
      fi
    done < "${yaml_file}" || return
    [[ "${host_path_pending}" == false && "${found_host_path}" == true ]] || {
      fail "No valid hostPath entries found in ${yaml_file}."
      return 1
    }
  done
}
# ---------------------------------- #

# Creates one secret without overwriting an existing file.
# Arguments: $1 - path; $2 - owner UID/GID; $3 - value (empty to generate).
# Global state read: SECRETS_DIR; global state changed: TEMP_FILES.
# Output streams: progress to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
ensure_secret() {
  local path=$1
  local owner=$2
  local value=${3:-}
  local staged
  if [[ -e "${path}" || -L "${path}" ]]; then
    [[ -f "${path}" && ! -L "${path}" ]] || {
      fail "Existing secret must be a regular file: ${path}"
      return 1
    }
    podman unshare chown "${owner}:${owner}" -- "${path}" || return
    podman unshare chmod 0400 -- "${path}" || return
    return 0
  fi

  if [[ -z "${value}" ]]; then
    value=$(openssl rand -hex 24) || return
  fi
  staged=$(mktemp --tmpdir="${SECRETS_DIR}" .secret.XXXXXX) || return
  TEMP_FILES+=("${staged}")
  printf '%s' "${value}" > "${staged}" || return
  podman unshare chown "${owner}:${owner}" -- "${staged}" || return
  podman unshare chmod 0400 -- "${staged}" || return
  mv -T --no-clobber -- "${staged}" "${path}" || return
  [[ ! -e "${staged}" ]] || {
    fail "Secret appeared while creating ${path}; it was not overwritten."
    return 1
  }
  log "Created secret ${path}"
}
# ---------------------------------- #

# Creates missing secrets and preserves the shared API password value.
# Arguments: none.
# Global state read: SECRETS_DIR, POSTGRES_UID, WEBAPP_UID.
# Output streams: progress to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
ensure_secrets() {
  local db_volume_exists=false
  local command_status
  local api_password=""
  install -d -m 0700 -- "${SECRETS_DIR}" || return
  [[ -O "${SECRETS_DIR}" ]] || {
    fail "Secrets directory must be owned by ${EXPECTED_USER}."
    return 1
  }
  chmod 0700 -- "${SECRETS_DIR}" || return

  if volume_exists webapp-db-data; then
    db_volume_exists=true
  else
    command_status=$?
    ((command_status == 1)) || return "${command_status}"
  fi
  if [[ "${db_volume_exists}" == true && ! -e "${SECRETS_DIR}/postgres-password" ]]; then
    fail "Volume webapp-db-data exists but ${SECRETS_DIR}/postgres-password is missing; restore it."
    return 1
  fi
  ensure_secret "${SECRETS_DIR}/postgres-password" "${POSTGRES_UID}" || return

  if [[ -e "${SECRETS_DIR}/api-db-password" ]]; then
    [[ -f "${SECRETS_DIR}/api-db-password" && ! -L "${SECRETS_DIR}/api-db-password" ]] || {
      fail "Existing secret must be a regular file: ${SECRETS_DIR}/api-db-password"
      return 1
    }
    api_password=$(podman unshare cat -- "${SECRETS_DIR}/api-db-password") || return
  elif [[ -e "${SECRETS_DIR}/db-init-api-password" ]]; then
    [[ -f "${SECRETS_DIR}/db-init-api-password" && ! -L "${SECRETS_DIR}/db-init-api-password" ]] || {
      fail "Existing secret must be a regular file: ${SECRETS_DIR}/db-init-api-password"
      return 1
    }
    api_password=$(podman unshare cat -- "${SECRETS_DIR}/db-init-api-password") || return
  elif [[ "${db_volume_exists}" == true ]]; then
    fail "Volume webapp-db-data exists but the API password files are missing; restore them."
    return 1
  else
    api_password=$(openssl rand -hex 24) || return
  fi
  [[ -n "${api_password}" ]] || {
    fail "API password secret is empty; restore it."
    return 1
  }
  ensure_secret "${SECRETS_DIR}/db-init-api-password" "${POSTGRES_UID}" "${api_password}" || return
  ensure_secret "${SECRETS_DIR}/api-db-password" "${WEBAPP_UID}" "${api_password}" || return
}
# ---------------------------------- #

# Installs user-scoped configuration, transformed kube YAML, and Quadlet copies.
# Arguments: none.
# Global state read: source and managed path globals; global state changed: TEMP_FILES.
# Output streams: progress and hostPath list to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
install_config() {
  log "Installing user configuration"
  install -d -m 0755 -- "${KUBE_DIR}" "${DB_INIT_DIR}" \
    "${PROXY_DIR}/templates" "${PROXY_DIR}/apps.d" "${QUADLET_DIR}" || return

  local -a yaml_sources=("${SOURCE_DIR}"/deploy/webapp/kube/*.yaml)
  local -a quadlet_sources=("${SOURCE_DIR}"/deploy/webapp/quadlet/*.kube)
  local source_file
  local destination
  for source_file in "${yaml_sources[@]}"; do
    destination="${KUBE_DIR}/${source_file##*/}"
    write_transformed_copy "${source_file}" "${destination}" kube || return
  done

  install -m 0644 -t "${DB_INIT_DIR}" -- "${SOURCE_DIR}"/webapp/database/init/*.sql || return
  install -m 0644 -- "${SOURCE_DIR}/deploy/webapp/nginx/default.conf.template" \
    "${PROXY_DIR}/templates/default.conf.template" || return
  install -m 0644 -- "${SOURCE_DIR}/deploy/webapp/nginx/apps.d/webapp.conf" \
    "${PROXY_DIR}/apps.d/webapp.conf" || return

  for source_file in "${quadlet_sources[@]}"; do
    destination="${QUADLET_DIR}/${source_file##*/}"
    write_transformed_copy "${source_file}" "${destination}" quadlet || return
    verify_no_etc_path "${destination}" || return
  done

  log "hostPath entries (paths only):"
  report_host_paths
}
# ---------------------------------- #

# Creates the PostgreSQL data volume if absent without changing its ownership.
# Arguments: none.
# Output streams: progress to stdout; Podman diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
ensure_db_volume() {
  local command_status
  if volume_exists webapp-db-data; then
    log "Keeping volume webapp-db-data"
    return 0
  else
    command_status=$?
    ((command_status == 1)) || return "${command_status}"
  fi
  podman volume create webapp-db-data >/dev/null || return
  log "Created volume webapp-db-data"
}
# ---------------------------------- #

# Creates the rootless image volume and initializes only a new volume's ownership.
# Arguments: none.
# Global state read: WEBAPP_UID.
# Output streams: progress to stdout; Podman diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
ensure_image_volume() {
  local command_status
  local mountpoint
  if volume_exists webapp-images; then
    verify_image_volume || return
    log "Keeping volume webapp-images"
    return 0
  else
    command_status=$?
    ((command_status == 1)) || return "${command_status}"
  fi

  # Set ownership at creation to avoid image copy-up resetting it on first mount.
  podman volume create --opt "o=uid=${WEBAPP_UID},gid=${WEBAPP_UID}" webapp-images >/dev/null || return
  log "Created volume webapp-images"
  mountpoint=$(podman volume inspect webapp-images --format '{{.Mountpoint}}') || {
    fail "Could not inspect volume webapp-images after creation."
    return 1
  }
  [[ -n "${mountpoint}" && "${mountpoint}" == /* && "${mountpoint}" != / ]] || {
    fail "Volume webapp-images has an invalid mountpoint."
    return 1
  }
  podman unshare chown -R "${WEBAPP_UID}:${WEBAPP_UID}" -- "${mountpoint}" || return
  verify_image_volume
}
# ---------------------------------- #

# Pulls every base image referenced by the kube YAML and Containerfile.
# Arguments: none.
# Output streams: progress and Podman output.
# Return status: 0 on success, nonzero on error.
pull_base_images() {
  local image
  for image in "${BASE_IMAGES[@]}"; do
    log "Pulling ${image}"
    podman pull --policy=always "${image}" || return
  done
}
# ---------------------------------- #

# Builds the webapp image from the supplied repository root without cache.
# Arguments: none.
# Global state read: SOURCE_DIR, IMAGE.
# Output streams: progress and Podman build output.
# Return status: Podman build status.
build_image() {
  log "Building ${IMAGE}"
  podman build --no-cache --file "${SOURCE_DIR}/webapp/Containerfile" \
    --tag "${IMAGE}" -- "${SOURCE_DIR}"
}
# ---------------------------------- #

# Reloads user systemd and starts the database before restarting the app and proxy.
# Arguments: none.
# Output streams: progress to stdout; systemd diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
start_units() {
  log "Reloading user systemd and starting units"
  systemctl --user daemon-reload || return
  systemctl --user start webapp-db.service || return
  systemctl --user restart webapp.service app-proxy.service
}
# ---------------------------------- #

# Waits up to 45 two-second polls for the API health endpoint.
# Arguments: none.
# Global state read: HEALTH_URL, UNITS.
# Output streams: progress to stdout; unit status and diagnostics to stderr.
# Return status: 0 when healthy, nonzero after timeout.
wait_healthy() {
  local _attempt
  for _attempt in {1..45}; do
    if curl -fsS --max-time 3 "${HEALTH_URL}" >/dev/null 2>&1; then
      log "Healthy: ${HEALTH_URL}"
      return 0
    fi
    sleep 2 || return
  done
  if ! systemctl --user --no-pager --lines=20 status "${UNITS[@]}" >&2; then
    log "systemctl status returned nonzero." >&2
  fi
  fail "API not healthy after 90 s: ${HEALTH_URL}"
}
# ---------------------------------- #

# Reports active states for all three user units and their containers.
# Arguments: none.
# Global state read: UNITS, PODS.
# Output streams: unit and container states to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero on status-query failure.
report_status() {
  local unit
  local pod_name
  local unit_state
  local container_states
  log "Unit states:"
  for unit in "${UNITS[@]}"; do
    unit_state=$(systemctl --user show --property=ActiveState --value "${unit}") || return
    printf '%s: %s\n' "${unit}" "${unit_state}"
  done
  log "Container states:"
  for pod_name in "${PODS[@]}"; do
    container_states=$(podman ps --all --filter "pod=${pod_name}" --format '{{.Names}} {{.State}}') || return
    [[ -n "${container_states}" ]] || {
      fail "No containers found for pod ${pod_name}."
      return 1
    }
    printf '%s\n' "${container_states}"
  done
}
# ---------------------------------- #

# Removes only temporary files created by this invocation.
# Arguments: none.
# Global state read: TEMP_FILES.
# Output streams: cleanup diagnostics to stderr.
# Return status: 0 when cleanup succeeds, nonzero otherwise.
cleanup_temporary_files() {
  local temporary_file
  for temporary_file in "${TEMP_FILES[@]}"; do
    if [[ -e "${temporary_file}" ]] && ! rm -- "${temporary_file}"; then
      printf 'ERROR: Could not remove temporary file %s\n' "${temporary_file}" >&2
      return 1
    fi
  done
}
# ---------------------------------- #

# Coordinates parsing, preflight, image and resource preparation, and startup.
# Arguments: CLI arguments.
# Output streams: progress and final states to stdout; diagnostics to stderr.
# Return status: 0 on success, nonzero on error.
main() {
  if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
    usage
    return 0
  fi

  parse_args "$@" || return
  resolve_source_dir || return
  trap cleanup_temporary_files EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  preflight || return
  pull_base_images
  if [[ "${NO_BUILD}" == true ]]; then
    log "Reusing ${IMAGE}"
  else
    build_image
  fi
  ensure_secrets
  install_config
  ensure_db_volume
  ensure_image_volume
  start_units
  verify_image_volume || return
  wait_healthy
  report_status
  log "App: http://localhost:8080/webapp/index.html"
}
# ---------------------------------- #

main "$@"
