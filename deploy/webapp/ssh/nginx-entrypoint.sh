#!/usr/bin/env bash
set -Eeuo pipefail

[[ -s /root/.ssh/authorized_keys ]] || {
  printf 'ERROR: /root/.ssh/authorized_keys is empty or missing.\n' >&2
  exit 1
}

install -d -m 0755 /run/sshd
ssh-keygen -A
/usr/sbin/sshd

exec /docker-entrypoint.sh "$@"
