#!/usr/bin/env bash

# Loads Gateway VPN deployment variables into the current Bash session.
# Usage: source deploy/scripts/load-env.sh
# Global state changed: exports Gateway VPN variables.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf 'Load this file into the current shell: source %s\n' "$0" >&2
  exit 1
fi

export GATEWAY_USER='podman_user'
GATEWAY_HOME=$(getent passwd "${GATEWAY_USER}" | cut -d: -f6)
if [[ -z "${GATEWAY_HOME}" ]]; then
  GATEWAY_HOME="${HOME}"
fi
export GATEWAY_HOME

export ROOTLESS_SUBNET='10.100.0.0/24'
export ROOTLESS_BRIDGE_IP='10.100.0.1'
export ROOTLESS_BRIDGE_IFACE='podman1'
export GATEWAY_IP='10.100.0.2'
export VPN_PREFIX='100.101.0.0/24'
export HEADSCALE_FQDN='rhel9podhost.hv'
export GATEWAY_LAN_IP='192.168.7.164'
export APP_ALIAS='webapp.dev.anatel'
export TLS_STAGE="${GATEWAY_HOME}/tls-stage"
export CA_FILE="${TLS_STAGE}/gateway-dev-ca.crt"
