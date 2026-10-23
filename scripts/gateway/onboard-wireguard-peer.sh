#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
CONFIG_PATH="${REPO_ROOT}/config/host_config.json"

PROFILE_DIRECTORY=""
PROFILE_PATH=""
PROFILE_TEMP=""
ERROR_TEMP=""
PEER_ID=""
PEER_FINGERPRINT=""
PEER_CREATED=0
PROFILE_PUBLISHED=0
ONBOARDING_COMPLETE=0
GENERATION_UNCERTAIN=0

# Report a safe error and stop the host-side onboarding operation.
fail() {
  printf '[wireguard-onboard] ERROR: %s\n' "$*" >&2
  exit 1
}
# ---------------------------------- #

# Remove only this invocation's temporary output and compensate for its peer.
cleanup() {
  local status=$?
  local cleanup_failed=0
  trap - EXIT INT TERM HUP
  set +e

  if (( status != 0 && PEER_CREATED == 1 )); then
    if podman exec --user 0 gateway gateway-wireguard peer revoke \
      "$PEER_ID" \
      --reason "onboarding failed" \
      --expected-fingerprint "$PEER_FINGERPRINT" \
      > /dev/null 2> "${ERROR_TEMP:-/dev/null}"; then
      PEER_CREATED=0
      if (( PROFILE_PUBLISHED == 1 )); then
        if rm -f -- "$PROFILE_PATH"; then
          PROFILE_PUBLISHED=0
        else
          printf '[wireguard-onboard] ERROR: revoked peer profile could not be removed: %s\n' \
            "$PROFILE_PATH" >&2
          cleanup_failed=1
        fi
      fi
      if [[ -n "$PROFILE_TEMP" ]]; then
        if rm -f -- "$PROFILE_TEMP"; then
          PROFILE_TEMP=""
        else
          printf '[wireguard-onboard] ERROR: protected staging could not be removed: %s\n' \
            "$PROFILE_TEMP" >&2
          cleanup_failed=1
        fi
      fi
    else
      printf '[wireguard-onboard] ERROR: automatic revocation failed for peer %s; protected profile staging was retained for recovery.\n' \
        "$PEER_ID" >&2
    fi
  elif (( status != 0 && GENERATION_UNCERTAIN == 1 )); then
    printf '[wireguard-onboard] ERROR: generation state is uncertain for peer %s; inspect peer inventory before retrying.\n' \
      "$PEER_ID" >&2
  fi

  if (( status == 0 || PEER_CREATED == 0 )); then
    if [[ -n "$PROFILE_TEMP" ]]; then
      if rm -f -- "$PROFILE_TEMP"; then
        PROFILE_TEMP=""
      else
        printf '[wireguard-onboard] ERROR: protected staging could not be removed: %s\n' \
          "$PROFILE_TEMP" >&2
        cleanup_failed=1
      fi
    fi
  fi
  if [[ -n "$ERROR_TEMP" ]]; then
    if rm -f -- "$ERROR_TEMP"; then
      ERROR_TEMP=""
    else
      printf '[wireguard-onboard] ERROR: operation diagnostics could not be removed.\n' >&2
      cleanup_failed=1
    fi
  fi

  (( cleanup_failed == 0 )) || status=1
  if (( ONBOARDING_COMPLETE == 0 && status == 0 )); then
    status=1
  fi
  exit "$status"
}
# ---------------------------------- #

# Require safe ownership and permissions on every existing output-path component.
validate_directory_ancestors() {
  local path=$1
  local current="/"
  local component
  local metadata
  local uid
  local gid
  local mode
  local numeric_mode
  local -a components=()

  IFS='/' read -r -a components <<< "${path#/}"
  for component in "${components[@]}"; do
    current="${current%/}/${component}"
    if [[ -L "$current" ]]; then
      fail "profile directory path contains a symbolic link."
    fi
    if [[ ! -e "$current" ]]; then
      break
    fi
    if [[ ! -d "$current" ]]; then
      fail "profile directory path contains a non-directory component."
    fi
    metadata="$(stat -c '%u:%g:%a' -- "$current")" ||
      fail "could not inspect profile directory path."
    IFS=':' read -r uid gid mode <<< "$metadata"
    numeric_mode=$((8#${mode}))
    if [[ "$uid" != 0 || "$gid" != 0 ]] ||
      (( (numeric_mode & 0022) && !(numeric_mode & 01000) )); then
      fail "profile directory ancestors must be root-owned and protected from replacement."
    fi
  done
}
# ---------------------------------- #

# Create or verify the host profile directory with root-only access.
prepare_profile_directory() {
  local configured_path=$1
  local resolved_path
  local metadata

  if [[ "$configured_path" == "/" ]]; then
    fail "client_profiles_path must not be the filesystem root."
  fi
  case "${configured_path}/" in
    "${REPO_ROOT}/"*)
      fail "client_profiles_path must be outside the repository."
      ;;
  esac

  validate_directory_ancestors "$configured_path"
  mkdir -p -- "$configured_path" ||
    fail "could not create profile directory."
  [[ ! -L "$configured_path" && -d "$configured_path" ]] ||
    fail "profile directory must be a real directory."
  resolved_path="$(realpath -e -- "$configured_path")" ||
    fail "could not resolve profile directory."
  [[ "$resolved_path" == "$configured_path" ]] ||
    fail "profile directory path must not use symbolic links or aliases."
  case "${resolved_path}/" in
    "${REPO_ROOT}/"*)
      fail "client_profiles_path must be outside the repository."
      ;;
    /var/lib/gateway/wireguard/*)
      fail "client_profiles_path must be outside the Gateway peer-state mount."
      ;;
  esac
  validate_directory_ancestors "$resolved_path"

  metadata="$(stat -c '%u:%g:%a' -- "$resolved_path")" ||
    fail "could not inspect profile directory permissions."
  [[ "$metadata" == "0:0:700" ]] ||
    fail "profile directory must be root-owned with mode 0700."
  PROFILE_DIRECTORY="$resolved_path"
}
# ---------------------------------- #

# Read and validate peer policy values from the host configuration.
read_peer_configuration() {
  local -a values=()
  local expires_epoch
  local now_epoch

  PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
    python3 -m scripts.gateway.config_validation "$CONFIG_PATH" > /dev/null ||
    fail "host configuration validation failed."
  jq -e '.gateway.remote_access.wireguard.enabled == true' \
    "$CONFIG_PATH" > /dev/null ||
    fail "WireGuard must be enabled in host config."
  mapfile -d '' -t values < <(
    jq -j '
      .gateway.remote_access.wireguard
      | .client_profiles_path,
        .peer_purpose,
        .client_endpoint,
        .approval_reference,
        .expires_at
      | tostring + "\u0000"
    ' "$CONFIG_PATH"
  )
  (( ${#values[@]} == 5 )) ||
    fail "WireGuard peer onboarding settings are incomplete."

  PROFILE_DIRECTORY="${values[0]}"
  PEER_PURPOSE="${values[1]}"
  CLIENT_ENDPOINT="${values[2]}"
  APPROVAL_REFERENCE="${values[3]}"
  PEER_EXPIRY="${values[4]}"
  [[ "$PEER_PURPOSE" != "null" && "$CLIENT_ENDPOINT" != "null" &&
    "$APPROVAL_REFERENCE" != "null" && "$PEER_EXPIRY" != "null" ]] ||
    fail "WireGuard peer onboarding settings are incomplete."
  expires_epoch="$(date -d "$PEER_EXPIRY" +%s)" ||
    fail "WireGuard peer expiry is invalid."
  now_epoch="$(date -u +%s)" ||
    fail "could not read the host clock."
  (( expires_epoch > now_epoch )) ||
    fail "WireGuard peer expiry must be in the future."
}
# ---------------------------------- #

# Extract the generation marker emitted before the one-time profile stream.
read_created_fingerprint() {
  local diagnostics=$1
  local count

  count="$(awk -F '\t' -v peer_id="$PEER_ID" \
    '$1 == "PEER_CREATED" && $2 == peer_id { count += 1 } END { print count + 0 }' \
    "$diagnostics")"
  [[ "$count" == "1" ]] || return 1
  PEER_FINGERPRINT="$(awk -F '\t' -v peer_id="$PEER_ID" \
    '$1 == "PEER_CREATED" && $2 == peer_id { print $3 }' \
    "$diagnostics")"
  [[ "$PEER_FINGERPRINT" =~ ^[0-9a-f]{64}$ ]]
}
# ---------------------------------- #

# Confirm peer status after an approval response reports failure.
peer_is_approved() {
  local state_file=$1

  podman exec --user 0 gateway gateway-wireguard peer list \
    > "$state_file" 2> /dev/null || return 1
  jq -e --arg peer_id "$PEER_ID" --arg fingerprint "$PEER_FINGERPRINT" \
    '.peers | any(.[]; .id == $peer_id and
      .public_fingerprint == $fingerprint and .status == "approved")' \
    "$state_file" > /dev/null
}
# ---------------------------------- #

# Validate arguments, provision one peer, and publish its profile atomically.
main() {
  local device_id=${1:-}
  local owner=${2:-}
  local -a generation_command=()
  local generation_status=0
  local approval_status=0
  local metadata

  (( $# == 2 )) ||
    fail "usage: onboard-wireguard-peer.sh DEVICE_ID OWNER"
  (( EUID == 0 )) || fail "run this command as root."
  [[ "$device_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]] ||
    fail "device ID must use 1-64 letters, numbers, dots, underscores, or hyphens."
  [[ -n "$owner" && ${#owner} -le 128 && ! "$owner" =~ [[:cntrl:]] ]] ||
    fail "owner must be non-empty printable text up to 128 characters."
  for command_name in awk chmod date flock grep jq ln mkdir mktemp podman \
    python3 realpath rm stat; do
    command -v "$command_name" > /dev/null 2>&1 ||
      fail "required command is missing: ${command_name}."
  done
  [[ -f "$CONFIG_PATH" && ! -L "$CONFIG_PATH" ]] ||
    fail "host configuration file is unavailable."

  PEER_ID="$device_id"
  read_peer_configuration
  prepare_profile_directory "$PROFILE_DIRECTORY"
  PROFILE_PATH="${PROFILE_DIRECTORY}/peer-${PEER_ID}.conf"
  [[ ! -e "$PROFILE_PATH" && ! -L "$PROFILE_PATH" ]] ||
    fail "profile already exists; refusing to overwrite it."

  local lock_path="${PROFILE_DIRECTORY}/.onboarding.lock"
  local lock_metadata
  [[ ! -L "$lock_path" ]] || fail "onboarding lock must not be a symbolic link."
  if [[ ! -e "$lock_path" ]]; then
    (set -o noclobber; : > "$lock_path") ||
      fail "could not create onboarding lock."
  fi
  lock_metadata="$(stat -c '%u:%g:%a' -- "$lock_path")" ||
    fail "could not inspect onboarding lock."
  [[ -f "$lock_path" && ! -L "$lock_path" && "$lock_metadata" == "0:0:600" ]] ||
    fail "onboarding lock must be a root-owned regular file with mode 0600."
  exec 9<> "$lock_path" || fail "could not open onboarding lock."
  flock -n 9 || fail "another WireGuard onboarding operation is active."

  trap cleanup EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  PROFILE_TEMP="$(mktemp -- "${PROFILE_DIRECTORY}/.peer-${PEER_ID}.XXXXXXXX")" ||
    fail "could not create protected profile staging."
  ERROR_TEMP="$(mktemp -- "${PROFILE_DIRECTORY}/.error-${PEER_ID}.XXXXXXXX")" ||
    fail "could not create protected error staging."
  chmod 0600 -- "$PROFILE_TEMP" "$ERROR_TEMP" ||
    fail "could not secure temporary files."
  metadata="$(stat -c '%u:%g:%a' -- "$PROFILE_TEMP")" ||
    fail "could not inspect profile staging permissions."
  [[ "$metadata" == "0:0:600" ]] ||
    fail "profile staging must be root-owned with mode 0600."

  generation_command=(
    podman exec --user 0 gateway gateway-wireguard peer generate
    --id "$PEER_ID"
    --owner "$owner"
    --purpose "$PEER_PURPOSE"
    --endpoint "$CLIENT_ENDPOINT"
    --profile-stdout
  )
  GENERATION_UNCERTAIN=1
  if "${generation_command[@]}" > "$PROFILE_TEMP" 2> "$ERROR_TEMP"; then
    generation_status=0
  else
    generation_status=$?
  fi
  if read_created_fingerprint "$ERROR_TEMP"; then
    PEER_CREATED=1
  fi
  if (( generation_status != 0 )); then
    if (( PEER_CREATED == 0 )); then
      fail "peer generation failed with status ${generation_status}; check peer inventory before retrying."
    fi
    fail "peer generation failed with status ${generation_status}."
  fi
  (( PEER_CREATED == 1 )) ||
    fail "peer generation returned no verified creation marker."
  GENERATION_UNCERTAIN=0
  [[ -s "$PROFILE_TEMP" ]] ||
    fail "peer generation returned an empty profile."
  grep -Eq '^\[Interface\]$' "$PROFILE_TEMP" ||
    fail "generated profile has an invalid format."
  grep -Eq '^PrivateKey = [A-Za-z0-9+/]{43}=$' "$PROFILE_TEMP" ||
    fail "generated profile has an invalid private-key entry."
  grep -Eq '^\[Peer\]$' "$PROFILE_TEMP" ||
    fail "generated profile has an invalid peer section."

  if podman exec --user 0 gateway gateway-wireguard peer approve \
    "$PEER_ID" \
    --approval-reference "$APPROVAL_REFERENCE" \
    --expires-at "$PEER_EXPIRY" \
    --expected-fingerprint "$PEER_FINGERPRINT" \
    > /dev/null 2> "$ERROR_TEMP"; then
    approval_status=0
  else
    approval_status=$?
  fi
  if (( approval_status != 0 )) &&
    ! peer_is_approved "$ERROR_TEMP"; then
    fail "peer approval failed with status ${approval_status}."
  fi

  if ! ln -- "$PROFILE_TEMP" "$PROFILE_PATH"; then
    fail "could not publish profile without overwriting an existing file."
  fi
  PROFILE_PUBLISHED=1
  rm -- "$PROFILE_TEMP" ||
    fail "profile was published but staging cleanup failed."
  PROFILE_TEMP=""
  ONBOARDING_COMPLETE=1
  printf 'Created WireGuard profile: %s\n' "$PROFILE_PATH"
}
# ---------------------------------- #

main "$@"
