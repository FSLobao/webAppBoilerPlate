#!/usr/bin/env python3
"""Run the Gateway OpenVPN client with scoped forwarding and route guards.

The module validates profile metadata without opening the profile. OpenVPN is
the only process that consumes its contents. Kernel changes are limited to the
Gateway network namespace and restored when the client exits.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__:
    from .host_config_validation import load_host_config
    from .remote_forwarding import acquire_forwarding, release_forwarding
else:
    from host_config_validation import load_host_config
    from remote_forwarding import acquire_forwarding, release_forwarding

PROFILE_PATH = Path("/run/openvpn/client.ovpn")
TUN_INTERFACE = "tun0"
NFT_TABLE = "gateway_remote_access"
IP_FORWARD_PATH = Path("/proc/sys/net/ipv4/ip_forward")
RUNTIME_STATE_DIRECTORY = Path("/run/gateway/openvpn")
RUNTIME_STATE_PATH = RUNTIME_STATE_DIRECTORY / "state.json"
CONFIG_PATH = "/etc/gateway/generated/config.json"
INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,15}")
HOOK_ACTIONS = {
    "gateway-openvpn-up": "up",
    "gateway-openvpn-down": "down",
    "gateway-openvpn-route-up": "route-up",
}


class RuntimeErrorSafe(RuntimeError):
    """Report a sanitized OpenVPN runtime error."""


def _command(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one local tool without printing its output."""
    try:
        return runner(
            list(arguments),
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise RuntimeErrorSafe(
            f"required runtime command is unavailable: {arguments[0]}"
        ) from error


def _openvpn_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return enabled OpenVPN metadata or reject an inactive invocation."""
    gateway = config.get("gateway")
    remote_access = gateway.get("remote_access") if isinstance(gateway, dict) else None
    openvpn = remote_access.get("openvpn") if isinstance(remote_access, dict) else None
    if not isinstance(openvpn, dict) or openvpn.get("enabled") is not True:
        raise RuntimeErrorSafe("OpenVPN runtime was invoked while disabled.")
    allowed_fields = {
        "enabled",
        "profile_path",
        "client_pool",
    }
    unsupported_fields = set(openvpn) - allowed_fields
    if unsupported_fields:
        raise RuntimeErrorSafe("OpenVPN configuration contains unsupported fields.")
    pool = None
    if "client_pool" in openvpn:
        try:
            pool = ipaddress.IPv4Network(str(openvpn["client_pool"]), strict=True)
        except ValueError as error:
            raise RuntimeErrorSafe(
                "OpenVPN client pool metadata is invalid."
            ) from error
        if pool.prefixlen == 0 or pool.num_addresses < 4:
            raise RuntimeErrorSafe("OpenVPN client pool is not a usable IPv4 range.")
    else:
        logging.getLogger(__name__).warning(
            "OpenVPN client_pool is not configured; assigned prefix cannot be "
            "checked against the client allocation, no managed host return route "
            "will be installed or validated, and symmetric client reply routing "
            "is not guaranteed."
        )
    networks = config.get("networks")
    if not isinstance(networks, list) or not networks:
        raise RuntimeErrorSafe("OpenVPN requires configured Podman networks.")
    for network in networks:
        if not isinstance(network, dict):
            raise RuntimeErrorSafe("Configured Podman network metadata is invalid.")
        try:
            subnet = ipaddress.IPv4Network(network["subnet"], strict=True)
        except (KeyError, ValueError) as error:
            raise RuntimeErrorSafe(
                "Configured Podman network subnet is invalid."
            ) from error
        if pool is not None and pool.overlaps(subnet):
            raise RuntimeErrorSafe(
                "OpenVPN client pool overlaps a configured Podman network."
            )
    return openvpn


def _gateway_interfaces(
    config: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    """Resolve each configured Gateway address to one container interface."""
    networks = config.get("networks")
    if not isinstance(networks, list) or not networks:
        raise RuntimeErrorSafe("OpenVPN requires configured Podman networks.")
    result = _command(["ip", "-j", "-4", "address", "show"], runner=runner)
    if result.returncode != 0:
        raise RuntimeErrorSafe("Could not inspect Gateway network interfaces.")
    try:
        interfaces = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeErrorSafe("Gateway interface output is invalid.") from error
    if not isinstance(interfaces, list):
        raise RuntimeErrorSafe("Gateway interface output is invalid.")

    address_to_interface: dict[str, str] = {}
    for interface in interfaces:
        if not isinstance(interface, dict):
            raise RuntimeErrorSafe("Gateway interface output is invalid.")
        name = interface.get("ifname")
        if not isinstance(name, str) or not INTERFACE_PATTERN.fullmatch(name):
            continue
        address_info = interface.get("addr_info", [])
        if not isinstance(address_info, list):
            raise RuntimeErrorSafe("Gateway interface address output is invalid.")
        for address in address_info:
            if isinstance(address, dict) and address.get("family") == "inet":
                local = address.get("local")
                if isinstance(local, str):
                    address_to_interface[local] = name

    resolved = []
    for network in networks:
        if not isinstance(network, dict):
            raise RuntimeErrorSafe("Configured Podman network metadata is invalid.")
        gateway_address = network.get("gateway_address")
        if not isinstance(gateway_address, str):
            raise RuntimeErrorSafe(
                "OpenVPN requires a Gateway address on every Podman network."
            )
        try:
            address = ipaddress.IPv4Address(gateway_address)
        except ipaddress.AddressValueError as error:
            raise RuntimeErrorSafe(
                "Configured Gateway network address is invalid."
            ) from error
        interface = address_to_interface.get(str(address))
        if interface is None or interface == TUN_INTERFACE:
            raise RuntimeErrorSafe(
                "A configured Gateway network interface is unavailable."
            )
        resolved.append(interface)
    if len(set(resolved)) != len(resolved):
        raise RuntimeErrorSafe(
            "Configured Podman networks do not have distinct interfaces."
        )
    return tuple(resolved)


def _profile_is_safe(
    path: Path, *, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """Check profile ownership and mount flags without reading its contents."""
    try:
        profile_stat = path.lstat()
    except OSError as error:
        raise RuntimeErrorSafe(
            "The configured OpenVPN profile is unavailable."
        ) from error
    if not stat.S_ISREG(profile_stat.st_mode) or path.is_symlink():
        raise RuntimeErrorSafe("The configured OpenVPN profile is not a regular file.")
    if (
        profile_stat.st_uid != 0
        or not (profile_stat.st_mode & 0o400)
        or profile_stat.st_mode & 0o177
    ):
        raise RuntimeErrorSafe(
            "The configured OpenVPN profile must be root-owned and private."
        )
    result = _command(
        ["findmnt", "-n", "-o", "VFS-OPTIONS", "--target", str(path)],
        runner=runner,
    )
    if result.returncode != 0 or "ro" not in {
        option.strip() for option in result.stdout.split(",")
    }:
        raise RuntimeErrorSafe(
            "The configured OpenVPN profile is not mounted read-only."
        )


def _require_tun_capability(tun_path: Path = Path("/dev/net/tun")) -> None:
    """Require the TUN device and effective NET_ADMIN capability."""
    try:
        device_stat = tun_path.stat()
    except OSError as error:
        raise RuntimeErrorSafe("The TUN device is unavailable.") from error
    if not stat.S_ISCHR(device_stat.st_mode):
        raise RuntimeErrorSafe("The TUN device path is not a character device.")
    try:
        status = Path("/proc/self/status").read_text(encoding="ascii")
        capability_line = next(
            line for line in status.splitlines() if line.startswith("CapEff:")
        )
        effective_capabilities = int(capability_line.split()[1], 16)
    except (OSError, StopIteration, ValueError, IndexError) as error:
        raise RuntimeErrorSafe("Could not inspect Gateway capabilities.") from error
    if not effective_capabilities & (1 << 12):
        raise RuntimeErrorSafe("The Gateway lacks the NET_ADMIN capability.")


def build_openvpn_command(
    profile_path: str | Path = PROFILE_PATH,
    *,
    executable: str = "openvpn",
    config_path: str = CONFIG_PATH,
    runtime_id: str | None = None,
) -> list[str]:
    """Build the supervised OpenVPN command with routes delegated to hooks."""
    runtime_id = secrets.token_hex(32) if runtime_id is None else runtime_id
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_id):
        raise RuntimeErrorSafe("OpenVPN runtime ownership metadata is invalid.")
    return [
        executable,
        "--config",
        str(profile_path),
        "--client",
        "--dev",
        TUN_INTERFACE,
        "--topology",
        "subnet",
        "--auth",
        "SHA256",
        "--cipher",
        "AES-256-CBC",
        "--data-ciphers",
        "AES-256-CBC",
        "--remote-cert-tls",
        "server",
        "--ifconfig-noexec",
        "--route-noexec",
        "--block-ipv6",
        "--pull-filter",
        "reject",
        "ifconfig-ipv6",
        "--pull-filter",
        "reject",
        "route-ipv6",
        "--script-security",
        "2",
        "--setenv",
        "GATEWAY_CONFIG",
        config_path,
        "--setenv",
        "GATEWAY_RUNTIME_ID",
        runtime_id,
        "--up",
        "/usr/local/bin/gateway-openvpn-up",
        "--down",
        "/usr/local/bin/gateway-openvpn-down",
        "--route-up",
        "/usr/local/bin/gateway-openvpn-route-up",
        "--up-restart",
        "--auth-nocache",
        "--log",
        "/dev/stderr",
        "--verb",
        "3",
    ]


def _netfilter_rules(interfaces: Sequence[str], runtime_id: str) -> str:
    """Build an exclusively created, runtime-owned forward policy."""
    if not interfaces or any(
        not INTERFACE_PATTERN.fullmatch(name) for name in interfaces
    ):
        raise RuntimeErrorSafe("Gateway forwarding interfaces are invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_id):
        raise RuntimeErrorSafe("OpenVPN runtime ownership metadata is invalid.")
    podman_set = ", ".join(f'"{name}"' for name in interfaces)
    return (
        f"create table inet {NFT_TABLE} {{\n"
        f'  comment "gateway-runtime:{runtime_id}"\n'
        "  chain forward {\n"
        "    type filter hook forward priority -5; policy drop;\n"
        f"    iifname {{ {podman_set} }} oifname {{ {podman_set} }} drop\n"
        "    ct state established,related accept\n"
        f'    iifname "tun*" oifname {{ {podman_set} }} accept\n'
        "  }\n"
        "}\n"
    )


def _owned_nft_table_handle(
    runtime_id: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int | None:
    """Return the verified table handle, or None when the table is absent."""
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_id):
        raise RuntimeErrorSafe("OpenVPN runtime ownership metadata is invalid.")
    tables_result = _command(["nft", "-j", "list", "tables"], runner=runner)
    if tables_result.returncode != 0:
        raise RuntimeErrorSafe("Could not inspect Gateway firewall state.")
    try:
        table_entries = json.loads(tables_result.stdout)["nftables"]
        matching_tables = [
            entry["table"]
            for entry in table_entries
            if isinstance(entry, dict)
            and isinstance(entry.get("table"), dict)
            and entry["table"].get("family") == "inet"
            and entry["table"].get("name") == NFT_TABLE
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeErrorSafe("Gateway firewall listing is invalid.") from error
    if not isinstance(table_entries, list) or len(matching_tables) > 1:
        raise RuntimeErrorSafe("Gateway firewall listing is invalid.")
    if not matching_tables:
        return None

    table_result = _command(
        ["nft", "-j", "-a", "list", "table", "inet", NFT_TABLE],
        runner=runner,
    )
    if table_result.returncode != 0:
        raise RuntimeErrorSafe("Could not verify Gateway firewall ownership.")
    try:
        details = json.loads(table_result.stdout)["nftables"]
        detail_tables = [
            entry["table"]
            for entry in details
            if isinstance(entry, dict)
            and isinstance(entry.get("table"), dict)
            and entry["table"].get("family") == "inet"
            and entry["table"].get("name") == NFT_TABLE
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeErrorSafe("Gateway firewall ownership data is invalid.") from error
    if not isinstance(details, list) or len(detail_tables) != 1:
        raise RuntimeErrorSafe("Gateway firewall ownership data is invalid.")
    table = detail_tables[0]
    handle = table.get("handle")
    if (
        table.get("comment") != f"gateway-runtime:{runtime_id}"
        or isinstance(handle, bool)
        or not isinstance(handle, int)
        or handle < 1
    ):
        raise RuntimeErrorSafe(
            "Gateway firewall table ownership changed or handle is invalid; leaving it untouched."
        )
    return handle


def configure_forwarding(
    interfaces: Sequence[str],
    *,
    runtime_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    forwarding_path: Path = IP_FORWARD_PATH,
) -> str:
    """Acquire shared forwarding and return the original namespace setting."""
    state_directory = (
        RUNTIME_STATE_DIRECTORY.parent / "remote_access"
        if forwarding_path == IP_FORWARD_PATH
        else forwarding_path.parent / "remote_access"
    )
    try:
        return acquire_forwarding(
            runtime_id,
            interfaces,
            runner=runner,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )
    except RuntimeError as error:
        raise RuntimeErrorSafe(str(error)) from error


def restore_forwarding(
    previous_value: str,
    *,
    runtime_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    forwarding_path: Path = IP_FORWARD_PATH,
) -> None:
    """Release one forwarding owner without disrupting other tunnels."""
    state_directory = (
        RUNTIME_STATE_DIRECTORY.parent / "remote_access"
        if forwarding_path == IP_FORWARD_PATH
        else forwarding_path.parent / "remote_access"
    )
    try:
        release_forwarding(
            runtime_id,
            previous_value,
            runner=runner,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )
    except RuntimeError as error:
        raise RuntimeErrorSafe(str(error)) from error


def _cleanup_runtime_attempt(
    runtime_id: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    state_path: Path = RUNTIME_STATE_PATH,
    forwarding_path: Path = IP_FORWARD_PATH,
) -> None:
    """Restore only tunnel and forwarding state recorded by this attempt."""
    state = _read_runtime_state(runtime_id, state_path=state_path)
    if state is None:
        return
    address = f"{state['address']}/{state['prefix']}"
    if state["address"] in _tunnel_addresses(runner=runner):
        result = _command(
            ["ip", "address", "del", address, "dev", TUN_INTERFACE],
            runner=runner,
        )
        if result.returncode not in {0, 2}:
            raise RuntimeErrorSafe("Could not remove the owned OpenVPN tunnel address.")
    if (
        not state["link_was_up"]
        and not _tunnel_addresses(runner=runner)
        and _tunnel_link_is_up(runner=runner)
    ):
        result = _command(
            ["ip", "link", "set", "dev", TUN_INTERFACE, "down"],
            runner=runner,
        )
        if result.returncode != 0:
            raise RuntimeErrorSafe("Could not restore the OpenVPN tunnel link state.")
    restore_forwarding(
        state["previous_forwarding"],
        runtime_id=runtime_id,
        runner=runner,
        forwarding_path=forwarding_path,
    )
    _delete_runtime_state(state_path)


def _sanitized_diagnostic(line: str) -> str | None:
    """Map private OpenVPN output to a fixed, non-sensitive diagnostic."""
    message = line.lower()
    if "initialization sequence completed" in message:
        return "OpenVPN tunnel is connected."
    if (
        "tun/tap" in message
        and any(
            phrase in message
            for phrase in (
                "cannot open",
                "failed",
                "permission",
                "operation not permitted",
            )
        )
    ) or any(
        phrase in message
        for phrase in ("tunsetiff", "cannot ioctl tun", "tun device unavailable")
    ):
        return (
            "OpenVPN could not access the TUN device; check /dev/net/tun and NET_ADMIN."
        )
    if any(
        phrase in message
        for phrase in ("cannot open", "failed to open", "error opening", "no such file")
    ):
        return (
            "OpenVPN could not open a configured external input; "
            "check the root-managed read-only mounts."
        )
    if any(
        phrase in message
        for phrase in ("authentication failed", "auth_failed", "auth failure")
    ):
        return "OpenVPN external authentication failed."
    if any(
        phrase in message
        for phrase in (
            "options error",
            "unrecognized option",
            "unknown option",
            "missing or extra parameter",
        )
    ):
        if "[cmd-line]" in message or "command line" in message:
            return "OpenVPN rejected a Gateway-generated command-line option."
        return "OpenVPN rejected a directive in the external client profile."
    if any(
        phrase in message
        for phrase in (
            "cannot resolve",
            "name resolution",
            "name or service not known",
            "temporary failure in name resolution",
        )
    ):
        return "OpenVPN could not resolve its configured remote endpoint."
    if any(
        phrase in message
        for phrase in (
            "tls error",
            "verify error",
            "certificate verify failed",
            "peer certificate",
        )
    ):
        return "OpenVPN TLS or certificate negotiation failed."
    if any(
        phrase in message
        for phrase in (
            "connection refused",
            "network is unreachable",
            "no route to host",
            "connection timed out",
        )
    ):
        return "OpenVPN could not connect to its configured remote endpoint."
    return None


def _validate_assigned_address(
    environment: Mapping[str, str],
    openvpn: Mapping[str, Any],
    networks: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, int]:
    """Validate the OpenVPN address candidate before configuring TUN."""
    raw_address = environment.get("ifconfig_local")
    raw_netmask = environment.get("ifconfig_remote_netmask")
    interface = environment.get("dev")
    if not isinstance(raw_address, str) or not isinstance(raw_netmask, str):
        raise RuntimeErrorSafe("OpenVPN did not provide a valid tunnel address.")
    if interface != TUN_INTERFACE:
        raise RuntimeErrorSafe("OpenVPN selected an unexpected tunnel interface.")
    try:
        address = ipaddress.IPv4Address(raw_address)
        mask = ipaddress.IPv4Address(raw_netmask)
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
        pool = (
            ipaddress.IPv4Network(str(openvpn["client_pool"]), strict=True)
            if "client_pool" in openvpn
            else None
        )
        assigned_network = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    except (KeyError, ValueError) as error:
        raise RuntimeErrorSafe("OpenVPN tunnel address metadata is invalid.") from error
    if (
        address.is_unspecified
        or address.is_multicast
        or prefix == 0
        or (
            pool is None
            and prefix < 31
            and address
            in (assigned_network.network_address, assigned_network.broadcast_address)
        )
        or (
            pool is not None
            and (
                address not in pool
                or address in (pool.network_address, pool.broadcast_address)
                or prefix != pool.prefixlen
            )
        )
    ):
        if pool is not None:
            raise RuntimeErrorSafe(
                "OpenVPN assigned an address outside the configured client pool."
            )
        raise RuntimeErrorSafe("OpenVPN assigned an invalid tunnel address.")
    for network in networks:
        try:
            subnet = ipaddress.IPv4Network(network["subnet"], strict=True)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeErrorSafe(
                "Configured Podman network subnet is invalid."
            ) from error
        if assigned_network.overlaps(subnet):
            raise RuntimeErrorSafe(
                "OpenVPN assigned tunnel subnet overlaps a configured Podman network."
            )
    return str(address), prefix


def _runtime_id(environment: Mapping[str, str]) -> str:
    """Require the per-process identifier that binds hooks to one attempt."""
    runtime_id = environment.get("GATEWAY_RUNTIME_ID")
    if not isinstance(runtime_id, str) or not re.fullmatch(r"[0-9a-f]{64}", runtime_id):
        raise RuntimeErrorSafe("OpenVPN runtime ownership metadata is invalid.")
    return runtime_id


def _ensure_runtime_state_directory(state_path: Path) -> None:
    """Create and verify a private directory for persistent hook ownership."""
    directory = state_path.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.lstat()
    except OSError as error:
        raise RuntimeErrorSafe(
            "OpenVPN runtime state directory is unavailable."
        ) from error
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory.is_symlink()
        or directory_stat.st_uid != os.geteuid()
        or stat.S_IMODE(directory_stat.st_mode) & 0o077
    ):
        raise RuntimeErrorSafe("OpenVPN runtime state directory is unsafe.")


def _read_runtime_state(
    runtime_id: str, *, state_path: Path = RUNTIME_STATE_PATH
) -> dict[str, Any] | None:
    """Read ownership state only from a private, regular file."""
    try:
        state_path.parent.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeErrorSafe(
            "OpenVPN runtime state directory is unavailable."
        ) from error
    _ensure_runtime_state_directory(state_path)
    try:
        state_stat = state_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeErrorSafe("OpenVPN runtime state is unavailable.") from error
    if (
        not stat.S_ISREG(state_stat.st_mode)
        or state_path.is_symlink()
        or state_stat.st_uid != os.geteuid()
        or stat.S_IMODE(state_stat.st_mode) & 0o077
    ):
        raise RuntimeErrorSafe("OpenVPN runtime state file is unsafe.")
    try:
        descriptor = os.open(state_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, encoding="utf-8") as state_file:
            opened_stat = os.fstat(state_file.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_uid != os.geteuid()
                or stat.S_IMODE(opened_stat.st_mode) & 0o077
            ):
                raise RuntimeErrorSafe("OpenVPN runtime state file is unsafe.")
            state = json.load(state_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeErrorSafe("OpenVPN runtime state is invalid.") from error
    if (
        not isinstance(state, dict)
        or set(state)
        != {
            "runtime_id",
            "address",
            "prefix",
            "link_was_up",
            "previous_forwarding",
        }
        or state.get("runtime_id") != runtime_id
        or not isinstance(state.get("address"), str)
        or isinstance(state.get("prefix"), bool)
        or not isinstance(state.get("prefix"), int)
        or not 0 <= state.get("prefix", -1) <= 32
        or not isinstance(state.get("link_was_up"), bool)
        or not isinstance(state.get("previous_forwarding"), str)
        or state["previous_forwarding"] not in {"0", "1"}
    ):
        raise RuntimeErrorSafe("OpenVPN runtime state does not belong to this attempt.")
    try:
        ipaddress.IPv4Address(state["address"])
    except ipaddress.AddressValueError as error:
        raise RuntimeErrorSafe(
            "OpenVPN runtime state contains an invalid address."
        ) from error
    return state


def _write_runtime_state(
    state: Mapping[str, Any], *, state_path: Path = RUNTIME_STATE_PATH
) -> None:
    """Create one private ownership record without replacing prior state."""
    _ensure_runtime_state_directory(state_path)
    created = False
    try:
        descriptor = os.open(
            state_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
            opened_stat = os.fstat(state_file.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_uid != os.geteuid()
                or stat.S_IMODE(opened_stat.st_mode) & 0o077
            ):
                raise RuntimeErrorSafe("OpenVPN runtime state file is unsafe.")
            json.dump(state, state_file, sort_keys=True)
            state_file.flush()
            os.fsync(state_file.fileno())
    except (OSError, RuntimeErrorSafe) as error:
        if created:
            state_path.unlink(missing_ok=True)
        if isinstance(error, RuntimeErrorSafe):
            raise
        raise RuntimeErrorSafe("Could not record OpenVPN runtime ownership.") from error


def _delete_runtime_state(state_path: Path) -> None:
    """Remove one already-validated ownership record."""
    try:
        state_path.unlink()
    except OSError as error:
        raise RuntimeErrorSafe("Could not remove OpenVPN runtime state.") from error


def _tunnel_addresses(
    *, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> list[str]:
    """Return IPv4 addresses currently present on the managed tunnel."""
    result = _command(
        ["ip", "-j", "-4", "address", "show", "dev", TUN_INTERFACE],
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeErrorSafe("Could not inspect the OpenVPN tunnel interface.")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeErrorSafe("OpenVPN tunnel interface output is invalid.") from error
    if not isinstance(rows, list):
        raise RuntimeErrorSafe("OpenVPN tunnel interface output is invalid.")
    addresses = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("addr_info", []), list):
            raise RuntimeErrorSafe("OpenVPN tunnel interface output is invalid.")
        for item in row.get("addr_info", []):
            if not isinstance(item, dict):
                raise RuntimeErrorSafe("OpenVPN tunnel interface output is invalid.")
            if item.get("family") == "inet":
                address = item.get("local")
                if not isinstance(address, str):
                    raise RuntimeErrorSafe(
                        "OpenVPN tunnel interface output is invalid."
                    )
                addresses.append(address)
    return addresses


def _tunnel_link_is_up(
    *, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> bool:
    """Inspect the managed tunnel link state before changing it."""
    result = _command(
        ["ip", "-j", "link", "show", "dev", TUN_INTERFACE],
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeErrorSafe("Could not inspect the OpenVPN tunnel link.")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeErrorSafe("OpenVPN tunnel link output is invalid.") from error
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("ifname") != TUN_INTERFACE
        or not isinstance(rows[0].get("flags"), list)
    ):
        raise RuntimeErrorSafe("OpenVPN tunnel link output is invalid.")
    return "UP" in rows[0]["flags"]


def _tunnel_up(
    environment: Mapping[str, str],
    config: Mapping[str, Any],
) -> None:
    """Validate candidates before OpenVPN reaches its route-up activation hook."""
    openvpn = _openvpn_config(config)
    _runtime_id(environment)
    _validate_assigned_address(environment, openvpn, config["networks"])
    _validate_route_candidates(environment)


def _tunnel_route_up(
    environment: Mapping[str, str],
    config: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    state_path: Path = RUNTIME_STATE_PATH,
    forwarding_path: Path = IP_FORWARD_PATH,
) -> None:
    """Activate forwarding only after address and all route candidates validate."""
    openvpn = _openvpn_config(config)
    runtime_id = _runtime_id(environment)
    address, prefix = _validate_assigned_address(
        environment, openvpn, config["networks"]
    )
    _validate_route_candidates(environment)
    state = _read_runtime_state(runtime_id, state_path=state_path)
    current_addresses = _tunnel_addresses(runner=runner)
    if state is not None:
        if state["address"] != address or state["prefix"] != prefix:
            raise RuntimeErrorSafe(
                "OpenVPN reconnect changed its owned tunnel address."
            )
        if current_addresses != [address]:
            raise RuntimeErrorSafe("OpenVPN owned tunnel address is no longer present.")
        return
    if current_addresses:
        raise RuntimeErrorSafe(
            "OpenVPN tunnel interface already has an unowned IPv4 address."
        )

    link_was_up = _tunnel_link_is_up(runner=runner)
    interfaces = _gateway_interfaces(config, runner=runner)
    added_address = False
    previous_forwarding: str | None = None
    result = _command(
        ["ip", "address", "add", f"{address}/{prefix}", "dev", TUN_INTERFACE],
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeErrorSafe("Could not configure the OpenVPN tunnel address.")
    added_address = True

    def rollback_activation() -> None:
        """Undo address and forwarding changes from this failed activation."""
        if previous_forwarding is not None:
            restore_forwarding(
                previous_forwarding,
                runtime_id=runtime_id,
                runner=runner,
                forwarding_path=forwarding_path,
            )
        if added_address:
            _command(
                [
                    "ip",
                    "address",
                    "del",
                    f"{address}/{prefix}",
                    "dev",
                    TUN_INTERFACE,
                ],
                runner=runner,
            )
            if not link_was_up:
                _command(
                    ["ip", "link", "set", "dev", TUN_INTERFACE, "down"],
                    runner=runner,
                )

    try:
        if not link_was_up:
            result = _command(
                ["ip", "link", "set", "dev", TUN_INTERFACE, "up"],
                runner=runner,
            )
            if result.returncode != 0:
                raise RuntimeErrorSafe(
                    "Could not activate the OpenVPN tunnel interface."
                )
        previous_forwarding = configure_forwarding(
            interfaces,
            runtime_id=runtime_id,
            runner=runner,
            forwarding_path=forwarding_path,
        )
        _write_runtime_state(
            {
                "runtime_id": runtime_id,
                "address": address,
                "prefix": prefix,
                "link_was_up": link_was_up,
                "previous_forwarding": previous_forwarding,
            },
            state_path=state_path,
        )
    except OSError:
        rollback_activation()
        raise
    except RuntimeErrorSafe:
        rollback_activation()
        raise


def _tunnel_down(
    environment: Mapping[str, str],
    config: Mapping[str, Any],
) -> None:
    """Preserve attempt-owned state across reconnect; supervisor owns cleanup."""
    _openvpn_config(config)
    _runtime_id(environment)


def _validate_route_candidates(environment: Mapping[str, str]) -> None:
    """Reject all profile or server route candidates; none are needed here."""
    if any(key.startswith(("route_ipv6_", "ifconfig_ipv6_")) for key in environment):
        raise RuntimeErrorSafe("OpenVPN IPv6 tunnel or route candidates are rejected.")
    index = 1
    while f"route_network_{index}" in environment:
        raw_network = environment.get(f"route_network_{index}")
        raw_mask = environment.get(f"route_netmask_{index}")
        try:
            if not isinstance(raw_network, str) or not isinstance(raw_mask, str):
                raise TypeError
            candidate = ipaddress.IPv4Network(f"{raw_network}/{raw_mask}", strict=False)
        except (TypeError, ValueError) as error:
            raise RuntimeErrorSafe(
                "OpenVPN supplied invalid route metadata."
            ) from error
        if candidate.prefixlen == 0:
            raise RuntimeErrorSafe("OpenVPN default-route candidates are rejected.")
        raise RuntimeErrorSafe(
            "OpenVPN route candidates are not part of the configured topology."
        )
    if (
        any(key.startswith(("route_network_", "route_netmask_")) for key in environment)
        and index == 1
    ):
        raise RuntimeErrorSafe("OpenVPN route metadata is invalid.")


def run_openvpn(
    config: Mapping[str, Any],
    *,
    executable: str = "openvpn",
    profile_path: Path = PROFILE_PATH,
    config_path: str = CONFIG_PATH,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    """Validate and supervise OpenVPN; emit only fixed safe diagnostics."""
    _openvpn_config(config)
    if shutil.which(executable) is None:
        raise RuntimeErrorSafe("The OpenVPN executable is unavailable.")
    _profile_is_safe(profile_path, runner=runner)
    _require_tun_capability()
    _gateway_interfaces(config, runner=runner)
    runtime_id = secrets.token_hex(32)
    command = build_openvpn_command(
        profile_path,
        executable=executable,
        config_path=config_path,
        runtime_id=runtime_id,
    )
    child = None
    old_handlers = {}
    termination_signals: list[int] = []
    diagnostics: list[str] = []

    def forward_signal(signum: int, _frame: object) -> None:
        if child is not None and child.poll() is None:
            child.send_signal(signum)
        else:
            termination_signals.append(signum)

    def collect_sanitized_diagnostics(stream: Any) -> None:
        for line in stream:
            diagnostic = _sanitized_diagnostic(line)
            if diagnostic is not None and diagnostic not in diagnostics:
                diagnostics.append(diagnostic)
                print(f"[gateway] {diagnostic}", file=sys.stderr, flush=True)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            old_handlers[signum] = signal.signal(signum, forward_signal)
        if termination_signals:
            return 128 + termination_signals[0]
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            close_fds=True,
        )
        if child.stdout is None:
            raise RuntimeErrorSafe("Could not capture OpenVPN diagnostics safely.")
        diagnostic_thread = threading.Thread(
            target=collect_sanitized_diagnostics,
            args=(child.stdout,),
            daemon=True,
        )
        diagnostic_thread.start()
        if termination_signals and child.poll() is None:
            child.send_signal(termination_signals[0])
        status = child.wait()
        diagnostic_thread.join()
        if status != 0 and not diagnostics:
            print(
                f"[gateway] OpenVPN exited with status {status}; "
                "no safe diagnostic matched its output.",
                file=sys.stderr,
            )
        return status
    except OSError as error:
        raise RuntimeErrorSafe("Could not start the OpenVPN client.") from error
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait()
        _cleanup_runtime_attempt(runtime_id, runner=runner)


def _load_config(path: str) -> dict[str, Any]:
    """Load the validated host configuration for OpenVPN hooks."""
    config = load_host_config(path)
    if not isinstance(config, dict):
        raise RuntimeErrorSafe("Gateway configuration is invalid.")
    return config


def main(argv: list[str] | None = None) -> int:
    """Run the OpenVPN client or one protocol lifecycle hook."""
    hook_action = HOOK_ACTIONS.get(Path(sys.argv[0]).name)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "up", "down", "route-up"))
    parser.add_argument("config", nargs="?", default=CONFIG_PATH)
    args = parser.parse_args(argv) if hook_action is None else None
    try:
        action = hook_action or args.action
        config_path = (
            os.environ.get("GATEWAY_CONFIG", CONFIG_PATH)
            if hook_action is not None
            else args.config
        )
        config = _load_config(config_path)
        if action == "run":
            return run_openvpn(config, config_path=config_path)
        if action == "up":
            _tunnel_up(os.environ, config)
        elif action == "down":
            _tunnel_down(os.environ, config)
        elif action == "route-up":
            _tunnel_route_up(os.environ, config)
        else:
            _validate_route_candidates(os.environ)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeErrorSafe,
        json.JSONDecodeError,
    ) as error:
        print(f"[gateway] OpenVPN runtime failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
