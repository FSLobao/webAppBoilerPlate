#!/usr/bin/env python3
"""Allocate and clean up root-owned SSH TUN sessions.

OpenSSH invokes ``authkeys`` before authentication. PAM invokes ``pam`` for
authenticated session open and close. Only PAM provisions TUN devices.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .host_config_validation import load_host_config
    from .remote_forwarding import acquire_forwarding, release_forwarding
else:
    from host_config_validation import load_host_config
    from remote_forwarding import acquire_forwarding, release_forwarding

CONFIG_PATH = Path("/etc/gateway/generated/config.json")
AUTHORIZED_KEYS_PATH = Path("/run/gateway/ssh_tun/authorized_keys")
STATE_DIRECTORY = Path("/run/gateway/ssh_tun/state")
FORWARDING_STATE_DIRECTORY = Path("/run/gateway/remote_access")
ACCOUNT_NAME = "gateway-tunnel"
PAM_COMMAND_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
PENDING_LEASE_SECONDS = 60
CLIENT_ALIVE_INTERVAL = 15
CLIENT_ALIVE_COUNT_MAX = 3
MAX_SESSIONS_LIMIT = 32
FORCED_COMMAND = "/usr/local/lib/gateway/ssh_tun_runtime.py session"
SSH_TUNNEL_STATE = re.compile(r"[A-Za-z0-9_.-]{1,15}")


class TunnelRuntimeError(RuntimeError):
    """Report a safe SSH TUN lifecycle failure."""


@dataclass(frozen=True)
class RuntimePaths:
    """Hold root-managed runtime paths for one tunnel lifecycle."""

    state_directory: Path = STATE_DIRECTORY
    forwarding_state_directory: Path = FORWARDING_STATE_DIRECTORY
    authorized_keys_path: Path = AUTHORIZED_KEYS_PATH


def _enabled_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the enabled SSH TUN runtime inputs."""
    gateway = config.get("gateway")
    remote = gateway.get("remote_access") if isinstance(gateway, dict) else None
    ssh_tun = remote.get("ssh_tun") if isinstance(remote, dict) else None
    if not isinstance(ssh_tun, dict) or ssh_tun.get("enabled") is not True:
        raise TunnelRuntimeError("SSH TUN runtime was invoked while disabled.")
    if set(ssh_tun) != {
        "enabled",
        "account",
        "address_pool",
        "authorized_keys_path",
        "max_sessions",
    }:
        raise TunnelRuntimeError("SSH TUN configuration fields are invalid.")
    if ssh_tun.get("account") != ACCOUNT_NAME:
        raise TunnelRuntimeError(
            "SSH TUN account does not match the restricted account."
        )
    try:
        pool = ipaddress.IPv4Network(str(ssh_tun["address_pool"]), strict=True)
    except (KeyError, ValueError) as error:
        raise TunnelRuntimeError("SSH TUN address pool is invalid.") from error
    max_sessions = ssh_tun.get("max_sessions")
    if (
        isinstance(max_sessions, bool)
        or not isinstance(max_sessions, int)
        or not 1 <= max_sessions <= MAX_SESSIONS_LIMIT
        or pool.prefixlen == 0
        or pool.num_addresses < max_sessions * 2
    ):
        raise TunnelRuntimeError("SSH TUN session capacity or address pool is invalid.")
    key_path = ssh_tun.get("authorized_keys_path")
    if (
        not isinstance(key_path, str)
        or not key_path.startswith("/")
        or "\0" in key_path
        or any(part in {".", ".."} for part in key_path.split("/"))
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", key_path)
    ):
        raise TunnelRuntimeError("SSH TUN authorized-key path is invalid.")
    networks = config.get("networks")
    if not isinstance(networks, list) or not networks:
        raise TunnelRuntimeError("SSH TUN requires configured Podman networks.")
    for network in networks:
        if not isinstance(network, dict) or not isinstance(
            network.get("gateway_address"), str
        ):
            raise TunnelRuntimeError(
                "SSH TUN requires a Gateway address on every Podman network."
            )
        try:
            subnet = ipaddress.IPv4Network(network["subnet"], strict=True)
            address = ipaddress.IPv4Address(network["gateway_address"])
        except (KeyError, ValueError) as error:
            raise TunnelRuntimeError(
                "Configured Podman network data is invalid."
            ) from error
        if address not in subnet or pool.overlaps(subnet):
            raise TunnelRuntimeError(
                "SSH TUN pool or Gateway address conflicts with a Podman network."
            )
    openvpn = remote.get("openvpn") if isinstance(remote, dict) else None
    if isinstance(openvpn, dict) and openvpn.get("enabled") is True:
        try:
            openvpn_pool = ipaddress.IPv4Network(
                str(openvpn["client_pool"]), strict=True
            )
        except (KeyError, ValueError) as error:
            raise TunnelRuntimeError("OpenVPN client pool is invalid.") from error
        if pool.overlaps(openvpn_pool):
            raise TunnelRuntimeError("SSH TUN pool overlaps the OpenVPN client pool.")
    return ssh_tun


def _root_file(path: Path) -> bytes:
    """Read one regular root-owned key file without following symlinks."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise TunnelRuntimeError("SSH TUN authorized-key file is unsafe.")
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()
    except OSError as error:
        raise TunnelRuntimeError(
            "SSH TUN authorized-key file is unavailable."
        ) from error


def _decode_ed25519(value: str) -> bytes:
    """Decode and validate one canonical Ed25519 OpenSSH public-key blob."""
    try:
        decoded = base64.b64decode(value, validate=True)
        key_length = int.from_bytes(decoded[:4], "big")
        key_type = decoded[4 : 4 + key_length]
    except (ValueError, TypeError) as error:
        raise TunnelRuntimeError("SSH TUN public key is malformed.") from error
    if (
        not decoded
        or len(decoded) < 4
        or key_type != b"ssh-ed25519"
        or len(decoded) != 4 + key_length + 4 + 32
        or int.from_bytes(decoded[4 + key_length : 8 + key_length], "big") != 32
    ):
        raise TunnelRuntimeError("SSH TUN public key format is not allowed.")
    return decoded


def _authorized_keys(path: Path) -> dict[str, str]:
    """Load only plain Ed25519 keys from the root-managed key file."""
    try:
        contents = _root_file(path).decode("ascii")
    except UnicodeDecodeError as error:
        raise TunnelRuntimeError("SSH TUN authorized-key file is malformed.") from error
    keys = {}
    for line_number, line in enumerate(contents.splitlines(), start=1):
        fields = line.split(None, 2)
        if not fields or line.lstrip().startswith("#"):
            continue
        if len(fields) < 2 or len(fields) > 3 or fields[0] != "ssh-ed25519":
            raise TunnelRuntimeError(
                f"SSH TUN authorized-key line {line_number} is unsupported."
            )
        decoded = _decode_ed25519(fields[1])
        fingerprint = hashlib.sha256(decoded).hexdigest()
        keys[fields[1]] = fingerprint
    if not keys:
        raise TunnelRuntimeError("SSH TUN authorized-key file contains no keys.")
    return keys


def _endpoint_pair(address: str, port: str) -> tuple[str, int]:
    """Validate and normalize one SSH endpoint."""
    try:
        parsed_address = ipaddress.ip_address(address)
        parsed_port = int(port)
    except ValueError as error:
        raise TunnelRuntimeError("SSH connection endpoint is invalid.") from error
    if "%" in address or not 1 <= parsed_port <= 65535:
        raise TunnelRuntimeError("SSH connection endpoint is invalid.")
    return str(parsed_address), parsed_port


def _connection_id(
    account: str, address_a: str, port_a: str, address_b: str, port_b: str
) -> str:
    """Hash endpoint pairs independent of OpenSSH's endpoint ordering."""
    if account != ACCOUNT_NAME:
        raise TunnelRuntimeError("SSH connection is not for the tunnel account.")
    endpoints = sorted(
        (
            _endpoint_pair(address_a, port_a),
            _endpoint_pair(address_b, port_b),
        )
    )
    if endpoints[0] == endpoints[1]:
        raise TunnelRuntimeError("SSH connection endpoints are identical.")
    encoded = json.dumps([account, endpoints], separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ssh_connection_id(account: str, value: str) -> str:
    """Normalize PAM's client-first SSH_CONNECTION environment value."""
    fields = value.split()
    if len(fields) != 4:
        raise TunnelRuntimeError("PAM SSH connection metadata is invalid.")
    return _connection_id(account, *fields)


def _validate_state_directory(directory: Path) -> None:
    """Create and verify the private root-managed reservation directory."""
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
    except OSError as error:
        raise TunnelRuntimeError("SSH TUN reservation state is unavailable.") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or directory.is_symlink()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise TunnelRuntimeError("SSH TUN reservation state directory is unsafe.")


@contextmanager
def _locked_state(directory: Path):
    """Lock and atomically persist the pending and active reservations."""
    _validate_state_directory(directory)
    lock_path = directory / "state.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        lock_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) & 0o077
        ):
            raise TunnelRuntimeError("SSH TUN reservation lock is unsafe.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state_path = directory / "state.json"
        try:
            info = state_path.lstat()
        except FileNotFoundError:
            state: dict[str, Any] = {"schema_version": 1, "reservations": []}
        else:
            if (
                not stat.S_ISREG(info.st_mode)
                or state_path.is_symlink()
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise TunnelRuntimeError("SSH TUN reservation state file is unsafe.")
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise TunnelRuntimeError(
                    "SSH TUN reservation state is invalid."
                ) from error
            _validate_state(state)
        try:
            yield state
        finally:
            temporary = directory / f"state.{os.getpid()}.{time.monotonic_ns()}.tmp"
            output_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(output_fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state_path)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        os.close(descriptor)
    except OSError as error:
        raise TunnelRuntimeError(
            "Could not update SSH TUN reservation state."
        ) from error


def _validate_state(state: object) -> None:
    """Reject malformed or ambiguous root-owned reservation data."""
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or not isinstance(state.get("reservations"), list)
    ):
        raise TunnelRuntimeError("SSH TUN reservation state is invalid.")
    seen_connections = set()
    seen_slots = set()
    for record in state["reservations"]:
        if (
            not isinstance(record, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("connection_id", "")))
            or record.get("account") != ACCOUNT_NAME
            or record.get("status") not in {"pending", "active"}
            or isinstance(record.get("slot"), bool)
            or not isinstance(record.get("slot"), int)
            or not isinstance(record.get("created_at"), (int, float))
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("key_fingerprint", "")))
            or record["connection_id"] in seen_connections
            or record["slot"] in seen_slots
        ):
            raise TunnelRuntimeError("SSH TUN reservation state is invalid.")
        if record["status"] == "active" and (
            not isinstance(record.get("interface"), str)
            or not SSH_TUNNEL_STATE.fullmatch(record["interface"])
            or not isinstance(record.get("local_address"), str)
            or not isinstance(record.get("peer_address"), str)
            or record.get("previous_forwarding") not in {"0", "1"}
        ):
            raise TunnelRuntimeError("SSH TUN active session state is invalid.")
        seen_connections.add(record["connection_id"])
        seen_slots.add(record["slot"])


def _prune_expired(state: dict[str, Any], now: float) -> None:
    """Remove only unauthenticated reservations past their bounded lease."""
    state["reservations"] = [
        record
        for record in state["reservations"]
        if record["status"] == "active"
        or now - record["created_at"] < PENDING_LEASE_SECONDS
    ]


def _tun_offset(config: Mapping[str, Any]) -> int:
    """Keep OpenVPN's fixed tun0 outside the SSH allocation range."""
    gateway = config.get("gateway")
    remote = gateway.get("remote_access") if isinstance(gateway, dict) else None
    openvpn = remote.get("openvpn") if isinstance(remote, dict) else None
    return 1 if isinstance(openvpn, dict) and openvpn.get("enabled") is True else 0


def _interface_and_addresses(
    config: Mapping[str, Any], slot: int
) -> tuple[str, str, str]:
    """Map one stable slot to its TUN name and point-to-point addresses."""
    ssh_tun = _enabled_config(config)
    pool = ipaddress.IPv4Network(ssh_tun["address_pool"], strict=True)
    offset = slot * 2
    if offset + 1 >= pool.num_addresses:
        raise TunnelRuntimeError("SSH TUN address pool is too small for its sessions.")
    interface_number = slot + _tun_offset(config)
    return (
        f"tun{interface_number}",
        str(pool.network_address + offset),
        str(pool.network_address + offset + 1),
    )


def _run(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    """Run one Gateway networking command without a shell."""
    try:
        return runner(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise TunnelRuntimeError(
            f"required networking command is unavailable: {arguments[0]}"
        ) from error


def _interfaces(
    config: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[str, ...]:
    """Resolve configured Podman gateway addresses to container interfaces."""
    result = _run(["ip", "-j", "-4", "address", "show"], runner=runner)
    if result.returncode != 0:
        raise TunnelRuntimeError("Could not inspect Gateway network interfaces.")
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise TunnelRuntimeError("Gateway interface output is invalid.") from error
    found: dict[str, str] = {}
    if not isinstance(entries, list):
        raise TunnelRuntimeError("Gateway interface output is invalid.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise TunnelRuntimeError("Gateway interface output is invalid.")
        name = entry.get("ifname")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name):
            continue
        addresses = entry.get("addr_info", [])
        if not isinstance(addresses, list):
            raise TunnelRuntimeError("Gateway interface address output is invalid.")
        for address in addresses:
            if (
                isinstance(address, dict)
                and address.get("family") == "inet"
                and isinstance(address.get("local"), str)
            ):
                found[address["local"]] = name
    networks = config["networks"]
    result_names = []
    for network in networks:
        interface = found.get(network["gateway_address"])
        if interface is None or interface.startswith("tun"):
            raise TunnelRuntimeError(
                "A configured Gateway network interface is unavailable."
            )
        result_names.append(interface)
    if len(set(result_names)) != len(result_names):
        raise TunnelRuntimeError(
            "Configured Gateway networks do not have distinct interfaces."
        )
    return tuple(result_names)


def _preflight_interface(
    interface: str,
    peer_address: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Reject interface or route candidates before changing kernel state."""
    links = _run(["ip", "-j", "link", "show"], runner=runner)
    routes = _run(["ip", "-j", "-4", "route", "show", "table", "all"], runner=runner)
    if links.returncode != 0 or routes.returncode != 0:
        raise TunnelRuntimeError("Could not inspect SSH TUN route candidates.")
    try:
        link_entries = json.loads(links.stdout)
        route_entries = json.loads(routes.stdout)
        peer = ipaddress.IPv4Address(peer_address)
    except (json.JSONDecodeError, ValueError) as error:
        raise TunnelRuntimeError(
            "SSH TUN route inspection output is invalid."
        ) from error
    if not isinstance(link_entries, list) or not isinstance(route_entries, list):
        raise TunnelRuntimeError("SSH TUN route inspection output is invalid.")
    if any(
        isinstance(entry, dict) and entry.get("ifname") == interface
        for entry in link_entries
    ):
        raise TunnelRuntimeError(
            "SSH TUN interface already exists; leaving it untouched."
        )
    for route in route_entries:
        if not isinstance(route, dict) or route.get("dst") in {None, "default"}:
            continue
        try:
            destination = ipaddress.ip_network(route["dst"], strict=False)
        except (TypeError, ValueError) as error:
            raise TunnelRuntimeError("Gateway route listing is invalid.") from error
        if destination.version == 4 and peer in destination:
            raise TunnelRuntimeError(
                f"SSH TUN peer {peer} conflicts with an existing Gateway route."
            )


def _tunnel_owner_matches(
    interface: str,
    account: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    """Check that an existing TUN device belongs to the configured account."""
    try:
        account_uid = pwd.getpwnam(account).pw_uid
    except KeyError:
        owner = re.escape(account)
    else:
        owner = rf"(?:{re.escape(account)}|{account_uid})"
    result = _run(["ip", "tuntap", "show", "dev", interface], runner=runner)
    return (
        result.returncode == 0
        and re.search(rf"\buser\s+{owner}(?:\s|$)", result.stdout) is not None
    )


def _create_tunnel(
    interface: str,
    local_address: str,
    peer_address: str,
    *,
    account: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Create and configure one root-owned, account-owned TUN interface."""
    commands = (
        ["ip", "tuntap", "add", "dev", interface, "mode", "tun", "user", account],
        [
            "ip",
            "address",
            "add",
            "local",
            local_address,
            "peer",
            peer_address,
            "dev",
            interface,
        ],
        ["ip", "link", "set", "dev", interface, "up"],
    )
    completed = False
    try:
        for command in commands:
            result = _run(command, runner=runner)
            if result.returncode != 0:
                raise TunnelRuntimeError("Could not configure the SSH TUN interface.")
            completed = True
    except TunnelRuntimeError:
        if completed and _tunnel_owner_matches(interface, account, runner=runner):
            _run(
                ["ip", "tuntap", "del", "dev", interface, "mode", "tun"], runner=runner
            )
        raise


def _interface_matches(
    interface: str,
    local_address: str,
    peer_address: str,
    *,
    account: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    """Verify exact device ownership and point-to-point addresses."""
    if not _tunnel_owner_matches(interface, account, runner=runner):
        return False
    result = _run(
        ["ip", "-j", "-4", "address", "show", "dev", interface],
        runner=runner,
    )
    if result.returncode != 0:
        return False
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(entries, list) or len(entries) != 1:
        return False
    address_info = entries[0].get("addr_info")
    if not isinstance(address_info, list):
        return False
    addresses = [
        item
        for item in address_info
        if isinstance(item, dict) and item.get("family") == "inet"
    ]
    return (
        len(addresses) == 1
        and addresses[0].get("local") == local_address
        and addresses[0].get("peer", addresses[0].get("address")) == peer_address
    )


def _remove_tunnel(
    interface: str,
    local_address: str,
    peer_address: str,
    *,
    account: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Delete only the recorded TUN device and exact account/address mapping."""
    links = _run(["ip", "-j", "link", "show"], runner=runner)
    if links.returncode != 0:
        raise TunnelRuntimeError("Could not inspect SSH TUN cleanup state.")
    try:
        entries = json.loads(links.stdout)
    except json.JSONDecodeError as error:
        raise TunnelRuntimeError("SSH TUN link listing is invalid.") from error
    exists = any(
        isinstance(entry, dict) and entry.get("ifname") == interface
        for entry in entries
    )
    if not exists:
        return
    if not _interface_matches(
        interface,
        local_address,
        peer_address,
        account=account,
        runner=runner,
    ):
        raise TunnelRuntimeError(
            "SSH TUN cleanup ownership changed; leaving the interface untouched."
        )
    deleted = _run(
        ["ip", "tuntap", "del", "dev", interface, "mode", "tun"],
        runner=runner,
    )
    if deleted.returncode != 0:
        raise TunnelRuntimeError("Could not delete the owned SSH TUN interface.")


def _reservation(
    config: Mapping[str, Any],
    account: str,
    connection_id: str,
    key_fingerprint: str,
    *,
    paths: RuntimePaths,
    now: float,
) -> int:
    """Reserve one slot idempotently for a validated public-key connection."""
    ssh_tun = _enabled_config(config)
    with _locked_state(paths.state_directory) as state:
        _prune_expired(state, now)
        for record in state["reservations"]:
            if record["connection_id"] == connection_id:
                if (
                    record["account"] != account
                    or record["key_fingerprint"] != key_fingerprint
                ):
                    raise TunnelRuntimeError(
                        "SSH TUN connection reservation does not match its key."
                    )
                return int(record["slot"])
        occupied = {record["slot"] for record in state["reservations"]}
        slot = next(
            (
                candidate
                for candidate in range(ssh_tun["max_sessions"])
                if candidate not in occupied
            ),
            None,
        )
        if slot is None:
            raise TunnelRuntimeError("SSH TUN session capacity is full.")
        state["reservations"].append(
            {
                "connection_id": connection_id,
                "account": account,
                "slot": slot,
                "status": "pending",
                "created_at": now,
                "key_fingerprint": key_fingerprint,
            }
        )
        return slot


def authorize_key(
    config: Mapping[str, Any],
    account: str,
    key_type: str,
    key_data: str,
    endpoint_a: str,
    port_a: str,
    endpoint_b: str,
    port_b: str,
    *,
    paths: RuntimePaths | None = None,
    now: float | None = None,
) -> str:
    """Validate the configured key before reserving a pending connection slot."""
    if account != ACCOUNT_NAME or key_type != "ssh-ed25519":
        raise TunnelRuntimeError("SSH TUN key is not authorized.")
    _enabled_config(config)
    _decode_ed25519(key_data)
    runtime_paths = RuntimePaths() if paths is None else paths
    fingerprints = _authorized_keys(runtime_paths.authorized_keys_path)
    fingerprint = fingerprints.get(key_data)
    if fingerprint is None:
        raise TunnelRuntimeError("SSH TUN public key is not authorized.")
    connection_id = _connection_id(account, endpoint_a, port_a, endpoint_b, port_b)
    slot = _reservation(
        config,
        account,
        connection_id,
        fingerprint,
        paths=runtime_paths,
        now=time.time() if now is None else now,
    )
    tunnel_number = slot + _tun_offset(config)
    return (
        f'restrict,tunnel="{tunnel_number}",command="{FORCED_COMMAND}" '
        f"ssh-ed25519 {key_data}"
    )


def _tunnel_open(
    config: Mapping[str, Any],
    account: str,
    connection: str,
    *,
    paths: RuntimePaths,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    now: float,
) -> None:
    """Promote one pending reservation after safe TUN setup."""
    _enabled_config(config)
    connection_id = _ssh_connection_id(account, connection)
    interfaces = _interfaces(config, runner=runner)
    created_interface = False
    forwarding_lease: str | None = None
    try:
        with _locked_state(paths.state_directory) as state:
            _prune_expired(state, now)
            record = next(
                (
                    item
                    for item in state["reservations"]
                    if item["connection_id"] == connection_id
                ),
                None,
            )
            if record is None or record["account"] != account:
                raise TunnelRuntimeError(
                    "Authenticated SSH TUN connection has no live key reservation."
                )
            interface, local_address, peer_address = _interface_and_addresses(
                config, record["slot"]
            )
            if record["status"] == "active":
                if not _interface_matches(
                    interface,
                    local_address,
                    peer_address,
                    account=account,
                    runner=runner,
                ):
                    raise TunnelRuntimeError("Active SSH TUN ownership changed.")
                return
            _preflight_interface(interface, peer_address, runner=runner)
            _create_tunnel(
                interface,
                local_address,
                peer_address,
                account=account,
                runner=runner,
            )
            created_interface = True
            previous_forwarding = acquire_forwarding(
                connection_id,
                interfaces,
                runner=runner,
                state_directory=paths.forwarding_state_directory,
            )
            forwarding_lease = previous_forwarding
            record.update(
                status="active",
                interface=interface,
                local_address=local_address,
                peer_address=peer_address,
                previous_forwarding=previous_forwarding,
            )
    except Exception:
        if forwarding_lease is not None:
            release_forwarding(
                connection_id,
                forwarding_lease,
                runner=runner,
                state_directory=paths.forwarding_state_directory,
            )
        if created_interface:
            _remove_tunnel(
                interface,
                local_address,
                peer_address,
                account=account,
                runner=runner,
            )
        raise


def _tunnel_close(
    config: Mapping[str, Any],
    account: str,
    connection: str,
    *,
    paths: RuntimePaths,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    now: float,
) -> None:
    """Remove only resources recorded for the matching PAM connection."""
    connection_id = _ssh_connection_id(account, connection)
    with _locked_state(paths.state_directory) as state:
        _prune_expired(state, now)
        record = next(
            (
                item
                for item in state["reservations"]
                if item["connection_id"] == connection_id
            ),
            None,
        )
        if record is None:
            return
        if record["status"] == "active":
            _remove_tunnel(
                record["interface"],
                record["local_address"],
                record["peer_address"],
                account=account,
                runner=runner,
            )
            release_forwarding(
                connection_id,
                record["previous_forwarding"],
                runner=runner,
                state_directory=paths.forwarding_state_directory,
            )
        state["reservations"].remove(record)


def pam_lifecycle(
    config: Mapping[str, Any],
    environment: Mapping[str, str],
    *,
    paths: RuntimePaths | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: float | None = None,
) -> None:
    """Run the root PAM open or close hook for the dedicated tunnel account."""
    account = environment.get("PAM_USER", "")
    if account != ACCOUNT_NAME:
        return
    action = environment.get("PAM_TYPE")
    connection = environment.get("SSH_CONNECTION")
    if action not in {"open_session", "close_session"} or not connection:
        raise TunnelRuntimeError("PAM SSH TUN lifecycle metadata is invalid.")
    current_time = time.time() if now is None else now
    runtime_paths = RuntimePaths() if paths is None else paths
    if action == "open_session":
        _tunnel_open(
            config,
            account,
            connection,
            paths=runtime_paths,
            runner=runner,
            now=current_time,
        )
    else:
        _tunnel_close(
            config,
            account,
            connection,
            paths=runtime_paths,
            runner=runner,
            now=current_time,
        )


def _hold_for_disconnect(
    environment: Mapping[str, str], config: Mapping[str, Any]
) -> int:
    """Hold only the forced TUN session and reject requested shell commands."""
    original_command = environment.get("SSH_ORIGINAL_COMMAND", "")
    tunnel = environment.get("SSH_TUNNEL", "")
    match = re.fullmatch(r"tun([0-9]+)", tunnel)
    if original_command or match is None:
        return 1
    ssh_tun = _enabled_config(config)
    interface_number = int(match.group(1))
    slot = interface_number - _tun_offset(config)
    if not 0 <= slot < ssh_tun["max_sessions"]:
        return 1
    interface, server_address, client_address = _interface_and_addresses(config, slot)
    if interface != tunnel:
        return 1
    print(
        f"SSH TUN ready: {interface}; configure client local {client_address} "
        f"peer {server_address}."
    )
    sys.stdout.flush()
    while True:
        signal.pause()


def main(argv: list[str] | None = None) -> int:
    """Run the narrow OpenSSH or PAM process adapter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("authkeys", "check", "pam", "session"))
    if argv is None:
        argv = sys.argv[1:]
    if argv in (["-h"], ["--help"]):
        parser.print_help()
        return 0
    if not argv:
        parser.error("an action is required")
    action, arguments = argv[0], argv[1:]
    if action not in {"authkeys", "check", "pam", "session"}:
        parser.error(f"unsupported action: {action}")
    if action == "authkeys":
        if len(arguments) != 4:
            return 1
        account, key_type, key_data, connection = arguments
        endpoints = connection.split()
        if len(endpoints) != 4:
            return 1
        endpoint_a, port_a, endpoint_b, port_b = endpoints
    elif action in {"check", "pam", "session"}:
        if arguments:
            return 1
    try:
        if action == "authkeys":
            if os.geteuid() != 0:
                raise TunnelRuntimeError(
                    "SSH TUN authorization command must run as root."
                )
            config = load_host_config(CONFIG_PATH)
            output = authorize_key(
                config,
                account,
                key_type,
                key_data,
                endpoint_a,
                port_a,
                endpoint_b,
                port_b,
            )
            print(output)
        elif action == "check":
            if os.geteuid() != 0:
                raise TunnelRuntimeError("SSH TUN validation must run as root.")
            config = load_host_config(CONFIG_PATH)
            _enabled_config(config)
            _authorized_keys(AUTHORIZED_KEYS_PATH)
        elif action == "pam":
            if os.geteuid() != 0:
                raise TunnelRuntimeError("SSH TUN PAM hook must run as root.")
            # PAM exec omits sbin paths needed by the fixed networking tools.
            os.environ["PATH"] = PAM_COMMAND_PATH
            config = load_host_config(CONFIG_PATH)
            pam_lifecycle(config, os.environ)
        else:
            config = load_host_config(CONFIG_PATH)
            return _hold_for_disconnect(os.environ, config)
    except (OSError, KeyError, TypeError, ValueError, TunnelRuntimeError) as error:
        print(f"[gateway] SSH TUN lifecycle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
