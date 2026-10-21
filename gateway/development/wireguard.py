#!/usr/bin/env python3
"""Run the Gateway WireGuard server and root-only key/peer administration CLI.

The server reconciles only public peer metadata stored under
``/var/lib/gateway/wireguard``. Peer private keys exist only in memory during
profile generation and are written once to a verified direct terminal.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__:
    from .host_config_validation import load_host_config
    from .remote_forwarding import (
        ForwardingError,
        ForwardingRollbackError,
        acquire_forwarding,
        release_forwarding,
    )
else:
    from host_config_validation import load_host_config
    from remote_forwarding import (
        ForwardingError,
        ForwardingRollbackError,
        acquire_forwarding,
        release_forwarding,
    )

CONFIG_PATH = Path("/etc/gateway/generated/config.json")
SERVER_KEY_PATH = Path("/run/gateway/wireguard/server.key")
STATE_DIRECTORY = Path("/var/lib/gateway/wireguard")
PEERS_PATH = STATE_DIRECTORY / "peers.json"
INTERFACE = "wg0"
OWNER_ID = hashlib.sha256(b"gateway-wireguard").hexdigest()
PEER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
KEY_PATTERN = re.compile(r"[A-Za-z0-9+/]{43}=")
SERVER_KEY_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}")
# Linux asm-generic/ioctls.h defines TIOCGDEV as _IOR('T', 0x32, unsigned int).
LINUX_TIOCGDEV = 0x80045432
FAIL_STOP_TABLE = "gateway_wireguard_fail_stop"
FAIL_STOP_OWNERSHIP_PREFIX = "gateway-wireguard-fail-stop-v1:"


class WireGuardError(RuntimeError):
    """Report a sanitized WireGuard operation failure."""


def _run(arguments: list[str], *, input_text: str | None = None) -> str:
    """Run a networking command without a shell or secret-bearing diagnostics."""
    try:
        result = subprocess.run(
            arguments,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WireGuardError(
            f"required WireGuard command failed to start: {arguments[0]}"
        ) from error
    if result.returncode:
        raise WireGuardError(f"WireGuard command failed: {arguments[0]}")
    return result.stdout.strip()


def _generate_server_key(filename: str) -> None:
    """Create a private server key atomically without replacing an existing key."""
    if filename in {".", ".."} or not SERVER_KEY_FILENAME_PATTERN.fullmatch(filename):
        raise WireGuardError("WireGuard server-key filename is invalid.")
    directory = SERVER_KEY_PATH.parent
    try:
        directory_stat = directory.lstat()
    except OSError as error:
        raise WireGuardError(
            "WireGuard server-key output directory is unavailable."
        ) from error
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory.is_symlink()
        or directory_stat.st_uid != os.geteuid()
        or stat.S_IMODE(directory_stat.st_mode) & 0o022
    ):
        raise WireGuardError("WireGuard server-key output directory is unsafe.")
    key_path = directory / filename
    try:
        key_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise WireGuardError(
            "Could not inspect WireGuard server-key destination."
        ) from error
    else:
        raise WireGuardError(
            "WireGuard server key already exists; refusing to replace it."
        )
    private_key = _run(["wg", "genkey"])
    if not KEY_PATTERN.fullmatch(private_key):
        raise WireGuardError("WireGuard generated an invalid server key.")
    public_key = _run(["wg", "pubkey"], input_text=private_key)
    if not KEY_PATTERN.fullmatch(public_key):
        raise WireGuardError("WireGuard generated an invalid server public key.")
    try:
        with tempfile.TemporaryDirectory(
            prefix=".wireguard-server-key-", dir=directory
        ) as temporary_directory:
            temporary_path = Path(temporary_directory) / "server.key"
            descriptor = os.open(
                temporary_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
                os.fchmod(key_file.fileno(), 0o600)
                key_file.write(f"{private_key}\n")
                key_file.flush()
                os.fsync(key_file.fileno())
            try:
                os.link(temporary_path, key_path)
            except FileExistsError as error:
                raise WireGuardError(
                    "WireGuard server key already exists; refusing to replace it."
                ) from error
            directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except WireGuardError:
        raise
    except OSError as error:
        raise WireGuardError(
            "Could not create the WireGuard server key safely."
        ) from error


def _validate_server_key_metadata(key_path: Path) -> None:
    """Validate server-key file ownership and permissions without reading it."""
    try:
        key_stat = key_path.lstat()
    except OSError as error:
        raise WireGuardError("Mounted WireGuard server key is unavailable.") from error
    if (
        not stat.S_ISREG(key_stat.st_mode)
        or key_path.is_symlink()
        or key_stat.st_uid != 0
        or key_stat.st_size == 0
        or stat.S_IMODE(key_stat.st_mode) & 0o077
        or not stat.S_IMODE(key_stat.st_mode) & 0o400
    ):
        raise WireGuardError("Mounted WireGuard server key is unsafe.")


def _validate_server_key_file() -> None:
    """Verify the mounted server key without displaying private material."""
    _validate_server_key_metadata(SERVER_KEY_PATH)
    try:
        key_contents = SERVER_KEY_PATH.read_text(encoding="ascii")
    except OSError as error:
        raise WireGuardError(
            "Could not read the mounted WireGuard server key."
        ) from error
    private_key = key_contents.removesuffix("\n")
    if not KEY_PATTERN.fullmatch(private_key):
        raise WireGuardError("Mounted WireGuard server key is invalid.")
    _run(["wg", "pubkey"], input_text=private_key)


def _enabled(config: dict[str, Any]) -> dict[str, Any]:
    """Return validated enabled WireGuard configuration."""
    remote = config.get("gateway", {}).get("remote_access", {})
    wireguard = remote.get("wireguard")
    fields = {
        "enabled",
        "host_bind_address",
        "listen_port",
        "address_pool",
        "server_address",
        "dns_server",
        "server_private_key_path",
    }
    if (
        not isinstance(wireguard, dict)
        or set(wireguard) != fields
        or wireguard.get("enabled") is not True
    ):
        raise WireGuardError("WireGuard is disabled in the Gateway configuration.")
    try:
        pool = ipaddress.IPv4Network(wireguard["address_pool"], strict=True)
        server = ipaddress.IPv4Address(wireguard["server_address"])
        resolver = ipaddress.IPv4Address(wireguard["dns_server"])
        bind = ipaddress.IPv4Address(wireguard["host_bind_address"])
    except (
        ipaddress.AddressValueError,
        ipaddress.NetmaskValueError,
        TypeError,
    ):  # fmt: skip
        raise WireGuardError("WireGuard IPv4 configuration is invalid.") from None
    if (
        pool.prefixlen == 0
        or pool.num_addresses < 4
        or server in (pool.network_address, pool.broadcast_address)
        or server.is_unspecified
        or server.is_multicast
        or isinstance(wireguard["listen_port"], bool)
        or not isinstance(wireguard["listen_port"], int)
        or not 1 <= wireguard["listen_port"] <= 65535
    ):
        raise WireGuardError("WireGuard address pool or UDP port is invalid.")
    if bind.is_multicast:
        raise WireGuardError("WireGuard host bind address is invalid.")
    networks = config.get("networks")
    if not isinstance(networks, list) or not networks:
        raise WireGuardError("WireGuard requires configured Podman networks.")
    resolver_is_gateway = False
    for item in networks:
        try:
            network = ipaddress.IPv4Network(item["subnet"], strict=True)
        except (
            KeyError,
            TypeError,
            ipaddress.AddressValueError,
            ipaddress.NetmaskValueError,
        ):
            raise WireGuardError(
                "Configured Podman network metadata is invalid."
            ) from None
        if pool.overlaps(network) or server in network:
            raise WireGuardError("WireGuard addresses conflict with a Podman network.")
        if item.get("gateway_address") == str(resolver):
            resolver_is_gateway = True
    if not resolver_is_gateway and resolver != server:
        raise WireGuardError(
            "WireGuard DNS resolver is not a configured Gateway or server address."
        )
    other = remote.get("openvpn", {})
    ssh_tun = remote.get("ssh_tun", {})
    for metadata, field in ((other, "client_pool"), (ssh_tun, "address_pool")):
        if isinstance(metadata, dict) and field in metadata:
            try:
                if pool.overlaps(ipaddress.IPv4Network(metadata[field], strict=True)):
                    raise WireGuardError(
                        "WireGuard peer pool overlaps another remote pool."
                    )
            except (
                TypeError,
                ipaddress.AddressValueError,
                ipaddress.NetmaskValueError,
            ):  # fmt: skip
                raise WireGuardError("Another remote-access pool is invalid.") from None
    return wireguard


def _safe_state_directory() -> None:
    """Create and verify root-only persistent peer state storage."""
    try:
        STATE_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        details = STATE_DIRECTORY.lstat()
    except OSError as error:
        raise WireGuardError("WireGuard peer storage is unavailable.") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or STATE_DIRECTORY.is_symlink()
        or details.st_uid != 0
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise WireGuardError("WireGuard peer storage permissions are unsafe.")


def _fail_stop_marker_path() -> Path:
    """Return the fixed fail-stop marker path inside persistent peer storage."""
    return STATE_DIRECTORY / "critical-failure"


def _assert_no_fail_stop_marker() -> None:
    """Reject WireGuard operations while a persistent critical marker exists."""
    try:
        _safe_state_directory()
        _fail_stop_marker_path().lstat()
    except FileNotFoundError:
        return
    except (OSError, WireGuardError) as error:
        raise WireGuardError(
            "CRITICAL: WireGuard fail-stop state cannot be checked; refusing runtime operation."
        ) from error
    raise WireGuardError(
        "CRITICAL: WireGuard fail-stop marker exists; operator recovery is required."
    )


def _require_fail_stop_marker() -> str:
    """Verify the persistent fail-stop marker before installing firewall drops."""
    marker = _fail_stop_marker_path()
    try:
        _safe_state_directory()
        descriptor = os.open(
            marker,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, WireGuardError) as error:
        raise WireGuardError(
            "CRITICAL: WireGuard fail-stop marker cannot be verified."
        ) from error

    contents = bytearray()
    try:
        details = os.fstat(descriptor)
        while len(contents) < 129:
            chunk = os.read(descriptor, 129 - len(contents))
            if not chunk:
                break
            contents.extend(chunk)
    except OSError as error:
        raise WireGuardError(
            "CRITICAL: WireGuard fail-stop marker cannot be verified."
        ) from error
    finally:
        try:
            os.close(descriptor)
        except OSError as error:
            raise WireGuardError(
                "CRITICAL: WireGuard fail-stop marker cannot be verified."
            ) from error

    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != 0
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise WireGuardError("CRITICAL: WireGuard fail-stop marker is unsafe.")
    prefix = FAIL_STOP_OWNERSHIP_PREFIX.encode("ascii")
    marker_contents = bytes(contents)
    if (
        len(marker_contents) != len(prefix) + 33
        or not marker_contents.startswith(prefix)
        or marker_contents[-1:] != b"\n"
        or not re.fullmatch(rb"[0-9a-f]{32}\n", marker_contents[len(prefix) :])
    ):
        raise WireGuardError("CRITICAL: WireGuard fail-stop marker is invalid.")
    return marker_contents[len(prefix) : -1].decode("ascii")


def _fail_stop_rule_statements(port: int) -> dict[str, list[str]]:
    """Return the exact firewall statements required for fail-stop."""
    return {
        "input": [
            f'iifname "{INTERFACE}" drop',
            f"udp dport {port} drop",
        ],
        "forward": [
            f'iifname "{INTERFACE}" drop',
            f'oifname "{INTERFACE}" drop',
        ],
        "output": [
            f'oifname "{INTERFACE}" drop',
            f"meta l4proto udp udp sport {port} drop",
        ],
    }


def _verify_fail_stop_table(port: int, ownership_token: str) -> None:
    """Verify ownership, hooks, rules, and handles on an existing table."""
    listing = _run(["nft", "-a", "list", "table", "inet", FAIL_STOP_TABLE])
    expected_rules = _fail_stop_rule_statements(port)
    expected_chains = set(expected_rules)
    observed_rules: dict[str, list[str]] = {}
    observed_declarations: dict[str, list[str]] = {}
    current_chain: str | None = None
    found_table = False
    found_table_comment = False
    table_closed = False

    for raw_line in listing.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if table_closed:
            raise WireGuardError(
                "CRITICAL: existing WireGuard fail-stop table is invalid."
            )
        if not found_table:
            match = re.fullmatch(
                rf"table inet {FAIL_STOP_TABLE} \{{ # handle ([1-9][0-9]*)",
                line,
            )
            if match is None:
                raise WireGuardError(
                    "CRITICAL: existing WireGuard fail-stop table is invalid."
                )
            found_table = True
            continue
        if (
            current_chain is None
            and line == f'comment "{FAIL_STOP_OWNERSHIP_PREFIX}{ownership_token}";'
        ):
            if found_table_comment:
                raise WireGuardError(
                    "CRITICAL: existing WireGuard fail-stop table is invalid."
                )
            found_table_comment = True
            continue
        chain_match = re.fullmatch(
            r"chain ([A-Za-z_][A-Za-z0-9_]*) \{ # handle ([1-9][0-9]*)",
            line,
        )
        if current_chain is None and chain_match is not None:
            current_chain = chain_match.group(1)
            if current_chain not in expected_chains or current_chain in observed_rules:
                raise WireGuardError(
                    "CRITICAL: existing WireGuard fail-stop table is invalid."
                )
            observed_rules[current_chain] = []
            observed_declarations[current_chain] = []
            continue
        if current_chain is not None and line == "}":
            current_chain = None
            continue
        if current_chain is None and line == "}":
            table_closed = True
            continue
        if current_chain is not None:
            declaration = re.fullmatch(
                r"type filter hook (input|forward|output) priority (?:-300|raw); "
                r"policy accept;",
                line,
            )
            if declaration is not None:
                observed_declarations[current_chain].append(line)
                continue
            rule_match = re.fullmatch(r"(.+?) # handle ([1-9][0-9]*)", line)
            if rule_match is not None:
                observed_rules[current_chain].append(rule_match.group(1))
                continue
        raise WireGuardError("CRITICAL: existing WireGuard fail-stop table is invalid.")

    if (
        not found_table
        or not found_table_comment
        or not table_closed
        or current_chain is not None
        or set(observed_rules) != expected_chains
        or any(
            observed_rules[chain] != expected_rules[chain]
            or observed_declarations[chain]
            not in (
                [f"type filter hook {chain} priority -300; policy accept;"],
                [f"type filter hook {chain} priority raw; policy accept;"],
            )
            for chain in expected_chains
        )
    ):
        raise WireGuardError("CRITICAL: existing WireGuard fail-stop table is invalid.")


def _install_fail_stop_drop(wireguard: dict[str, Any]) -> None:
    """Install exclusive fail-stop drops or verify the existing owned table."""
    token = _require_fail_stop_marker()
    port = wireguard["listen_port"]
    tables = _run(["nft", "list", "tables"])
    if f"table inet {FAIL_STOP_TABLE}" in tables.splitlines():
        _verify_fail_stop_table(port, token)
        return

    rules = [
        (
            f"add table inet {FAIL_STOP_TABLE} "
            f'{{ comment "{FAIL_STOP_OWNERSHIP_PREFIX}{token}"; }}'
        )
    ]
    rules.extend(
        f"add chain inet {FAIL_STOP_TABLE} {chain} "
        "{ type filter hook "
        f"{chain} priority -300; policy accept; }}"
        for chain in _fail_stop_rule_statements(port)
    )
    rules.extend(
        f"add rule inet {FAIL_STOP_TABLE} {chain} {statement}"
        for chain, statements in _fail_stop_rule_statements(port).items()
        for statement in statements
    )
    try:
        _run(["nft", "-f", "-"], input_text="\n".join(rules) + "\n")
    except WireGuardError:
        tables = _run(["nft", "list", "tables"])
        if f"table inet {FAIL_STOP_TABLE}" not in tables.splitlines():
            raise
        _verify_fail_stop_table(port, token)


def _fail_stop_forwarding_rollback(wireguard: dict[str, Any]) -> str:
    """Persist WireGuard fail-stop state and attempt every local shutdown step."""
    failures: list[str] = []
    try:
        _create_fail_stop_marker()
    except WireGuardError:
        failures.append("marker")
    try:
        _install_fail_stop_drop(wireguard)
    except WireGuardError:
        failures.append("drop_policy")
    try:
        _run(["ip", "link", "del", "dev", INTERFACE])
    except WireGuardError:
        failures.append("interface")
    if failures:
        return (
            "CRITICAL: shared forwarding rollback failed; "
            "WireGuard fail-stop is incomplete; operator recovery is required."
        )
    return (
        "CRITICAL: shared forwarding rollback failed; WireGuard fail-stop drops "
        "are installed and wg0 was removed."
    )


def _create_fail_stop_marker() -> None:
    """Atomically persist a root-only marker that prevents automatic recovery."""
    marker = _fail_stop_marker_path()
    contents = f"{FAIL_STOP_OWNERSHIP_PREFIX}{uuid.uuid4().hex}\n".encode("ascii")
    try:
        _safe_state_directory()
        descriptor = os.open(
            marker,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except FileExistsError:
        _require_fail_stop_marker()
        return
    except (OSError, WireGuardError) as error:
        raise WireGuardError(
            "CRITICAL: could not create the WireGuard fail-stop marker; "
            "runtime state may remain active."
        ) from error

    try:
        os.fchmod(descriptor, 0o600)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != 0
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            raise OSError("unsafe fail-stop marker metadata")
        remaining = memoryview(contents)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("could not write the fail-stop marker")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as error:
        raise WireGuardError(
            "CRITICAL: could not safely persist the WireGuard fail-stop marker; "
            "runtime state may remain active."
        ) from error
    finally:
        try:
            os.close(descriptor)
        except OSError as error:
            raise WireGuardError(
                "CRITICAL: could not safely persist the WireGuard fail-stop marker; "
                "runtime state may remain active."
            ) from error

    try:
        directory_fd = os.open(
            STATE_DIRECTORY,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            details = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(details.st_mode)
                or details.st_uid != 0
                or stat.S_IMODE(details.st_mode) & 0o077
            ):
                raise OSError("unsafe WireGuard state directory")
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise WireGuardError(
            "CRITICAL: could not safely persist the WireGuard fail-stop marker; "
            "runtime state may remain active."
        ) from error


def _read_peers() -> dict[str, Any]:
    """Read public peer metadata and reject unsafe or malformed state."""
    _safe_state_directory()
    try:
        details = PEERS_PATH.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "peers": [], "audit": []}
    except OSError as error:
        raise WireGuardError("WireGuard peer inventory is unavailable.") from error
    if (
        not stat.S_ISREG(details.st_mode)
        or PEERS_PATH.is_symlink()
        or details.st_uid != 0
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise WireGuardError("WireGuard peer inventory permissions are unsafe.")
    try:
        state = json.loads(PEERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WireGuardError("WireGuard peer inventory is invalid.") from error
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or not isinstance(state.get("peers"), list)
        or not isinstance(state.get("audit"), list)
    ):
        raise WireGuardError("WireGuard peer inventory is invalid.")
    identifiers: set[str] = set()
    public_keys: set[str] = set()
    for peer in state["peers"]:
        if (
            not isinstance(peer, dict)
            or not isinstance(peer.get("id"), str)
            or not PEER_ID_PATTERN.fullmatch(peer["id"])
            or peer["id"] in identifiers
            or not isinstance(peer.get("public_key"), str)
            or not KEY_PATTERN.fullmatch(peer["public_key"])
            or peer["public_key"] in public_keys
            or not isinstance(peer.get("address"), str)
            or peer.get("status") not in {"pending", "approved", "revoked"}
        ):
            raise WireGuardError("WireGuard peer inventory is invalid.")
        identifiers.add(peer["id"])
        public_keys.add(peer["public_key"])
    return state


def _write_peers(state: dict[str, Any]) -> None:
    """Atomically replace peer metadata without persisting private keys."""
    temporary = STATE_DIRECTORY / f".peers.{os.getpid()}.{time.time_ns()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, PEERS_PATH)
        directory_fd = os.open(STATE_DIRECTORY, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise WireGuardError(
            "Could not safely update WireGuard peer inventory."
        ) from error


def _locked_state() -> tuple[int, dict[str, Any]]:
    """Acquire the inventory lock and load its state."""
    _safe_state_directory()
    try:
        descriptor = os.open(
            STATE_DIRECTORY / "peers.lock",
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != 0
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise WireGuardError("WireGuard peer lock permissions are unsafe.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor, _read_peers()
    except OSError as error:
        raise WireGuardError("Could not lock WireGuard peer inventory.") from error


def _audit(
    state: dict[str, Any], operation: str, peer: dict[str, Any], detail: str
) -> None:
    """Append a secret-free operation record with container administrator UID."""
    state["audit"].append(
        {
            "time": datetime.now(UTC).isoformat(),
            "actor_uid": os.geteuid(),
            "operation": operation,
            "peer_id": peer["id"],
            "public_fingerprint": hashlib.sha256(
                peer["public_key"].encode("ascii")
            ).hexdigest(),
            "detail": detail,
        }
    )


def _peer_address(
    wireguard: dict[str, Any], peers: list[dict[str, Any]]
) -> ipaddress.IPv4Address:
    """Select the first unused host address in the explicitly configured pool."""
    pool = ipaddress.IPv4Network(wireguard["address_pool"], strict=True)
    server = ipaddress.IPv4Address(wireguard["server_address"])
    occupied = {ipaddress.IPv4Address(server)}
    for peer in peers:
        try:
            address = ipaddress.IPv4Address(peer["address"])
        except (KeyError, ipaddress.AddressValueError) as error:
            raise WireGuardError(
                "WireGuard peer address metadata is invalid."
            ) from error
        if address not in pool or address in occupied:
            raise WireGuardError(
                "WireGuard peer addresses are duplicated or outside the pool."
            )
        occupied.add(address)
    for address in pool.hosts():
        if address not in occupied:
            return address
    raise WireGuardError("WireGuard peer address pool is exhausted.")


def _validate_profile_endpoint(endpoint: str) -> str:
    """Validate the host used by a generated client profile."""
    try:
        ipaddress.IPv4Address(endpoint)
        return endpoint
    except ipaddress.AddressValueError:
        if (
            not endpoint
            or len(endpoint) > 253
            or any(
                not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label
                )
                for label in endpoint.rstrip(".").split(".")
            )
        ):
            raise WireGuardError("WireGuard endpoint is invalid.") from None
        return endpoint


def _profile(
    config: dict[str, Any],
    wireguard: dict[str, Any],
    private_key: str,
    peer: dict[str, Any],
    endpoint: str,
) -> str:
    """Build one IPv4-only split-tunnel profile using the supplied endpoint."""
    networks = [
        ipaddress.IPv4Network(entry["subnet"], strict=True)
        for entry in config["networks"]
    ]
    resolver = ipaddress.IPv4Address(wireguard["dns_server"])
    allowed = list(dict.fromkeys(str(network) for network in networks))
    if not any(resolver in network for network in networks):
        allowed.append(f"{resolver}/32")
    server_public = _run(
        ["wg", "pubkey"], input_text=Path(SERVER_KEY_PATH).read_text(encoding="ascii")
    )
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {peer['address']}/32\n"
        f"# Split DNS resolver; apply OS-specific dev.anatel settings: {resolver}\n\n"
        "[Peer]\n"
        f"PublicKey = {server_public}\n"
        f"Endpoint = {endpoint}:{wireguard['listen_port']}\n"
        f"AllowedIPs = {', '.join(allowed)}\n"
        "PersistentKeepalive = 25\n"
    )


def _activate_peer(peer: dict[str, Any]) -> None:
    """Install one public key and exact Gateway-namespace peer route."""
    _assert_no_fail_stop_marker()
    _run(
        [
            "wg",
            "set",
            INTERFACE,
            "peer",
            peer["public_key"],
            "allowed-ips",
            f"{peer['address']}/32",
        ]
    )
    try:
        _run(
            [
                "ip",
                "-4",
                "route",
                "add",
                f"{peer['address']}/32",
                "dev",
                INTERFACE,
                "proto",
                "186",
            ]
        )
    except WireGuardError:
        try:
            _run(["wg", "set", INTERFACE, "peer", peer["public_key"], "remove"])
        except WireGuardError:
            try:
                _remove_peer_route(peer)
            except WireGuardError:
                pass
            try:
                _run(["ip", "link", "del", "dev", INTERFACE])
                status = "wg0 was deleted"
            except WireGuardError:
                try:
                    _run(["ip", "link", "set", "dev", INTERFACE, "down"])
                    status = "wg0 was taken down"
                except WireGuardError:
                    status = None
            if status is None:
                marker_status = "fail-stop marker could not be recorded"
                try:
                    _create_fail_stop_marker()
                    marker_status = "fail-stop marker recorded"
                except WireGuardError:
                    pass
                nft_status = "peer-specific nft drop rule could not be installed"
                try:
                    _install_peer_drop_rule(peer)
                    nft_status = "peer-specific nft drop rule installed"
                except WireGuardError:
                    pass
                message = (
                    "CRITICAL: wg0 could not be deleted or taken down after peer "
                    f"rollback failed; {marker_status}; {nft_status}. Peer approval "
                    "remains pending. Live tunnel traffic may remain active and "
                    "requires immediate operator recovery."
                )
            else:
                message = (
                    f"CRITICAL: {status} after peer rollback failed; peer approval "
                    "remains pending and WireGuard runtime is unhealthy."
                )
            raise WireGuardError(message) from None
        raise


def _install_peer_drop_rule(peer: dict[str, Any]) -> None:
    """Block one peer's decrypted packets in both input and forward paths."""
    try:
        address = ipaddress.IPv4Address(peer["address"])
    except (KeyError, ipaddress.AddressValueError) as error:
        raise WireGuardError(
            "Cannot install a drop rule for invalid peer metadata."
        ) from error
    rules = (
        "add table inet gateway_wireguard_fail_stop\n"
        "add chain inet gateway_wireguard_fail_stop input "
        "{ type filter hook input priority -300; policy accept; }\n"
        "add chain inet gateway_wireguard_fail_stop forward "
        "{ type filter hook forward priority -300; policy accept; }\n"
        f"add rule inet gateway_wireguard_fail_stop input iifname "
        f'"{INTERFACE}" ip saddr {address} drop\n'
        f"add rule inet gateway_wireguard_fail_stop forward iifname "
        f'"{INTERFACE}" ip saddr {address} drop\n'
    )
    _run(["nft", "-f", "-"], input_text=rules)


def _remove_peer_route(peer: dict[str, Any]) -> None:
    """Remove only the exact tagged route owned by one peer."""
    destination = f"{peer['address']}/32"
    try:
        routes = json.loads(
            _run(["ip", "-j", "-4", "route", "show", "exact", destination])
        )
    except json.JSONDecodeError as error:
        raise WireGuardError("Gateway peer route inspection is invalid.") from error
    if not routes:
        return
    if not isinstance(routes, list) or any(
        not isinstance(route, dict)
        or route.get("dst") != destination
        or route.get("dev") != INTERFACE
        or str(route.get("protocol")) != "186"
        for route in routes
    ):
        raise WireGuardError("Peer route ownership changed; leaving it untouched.")
    _run(
        [
            "ip",
            "-4",
            "route",
            "del",
            destination,
            "dev",
            INTERFACE,
            "proto",
            "186",
        ]
    )


def _deactivate_peer(peer: dict[str, Any]) -> None:
    """Remove one peer key and its exact tagged Gateway route."""
    _run(["wg", "set", INTERFACE, "peer", peer["public_key"], "remove"])
    _remove_peer_route(peer)


def _assert_interface_up() -> None:
    """Fail the supervised server when wg0 is missing or no longer up."""
    _assert_no_fail_stop_marker()
    try:
        records = json.loads(_run(["ip", "-j", "link", "show", "dev", INTERFACE]))
    except json.JSONDecodeError as error:
        raise WireGuardError("WireGuard runtime health check is invalid.") from error
    if (
        not isinstance(records, list)
        or len(records) != 1
        or not isinstance(records[0], dict)
        or records[0].get("ifname") != INTERFACE
        or not isinstance(records[0].get("flags"), list)
        or "UP" not in records[0]["flags"]
    ):
        raise WireGuardError(
            "CRITICAL: wg0 is missing or down; WireGuard runtime is unhealthy."
        )


def _direct_tty() -> int:
    """Open a controlling terminal matching process input and output devices."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise WireGuardError("One-time profile delivery requires a direct terminal.")
    descriptor = -1
    try:
        input_device = bytearray(4)
        output_device = bytearray(4)
        fcntl.ioctl(sys.stdin.fileno(), LINUX_TIOCGDEV, input_device, True)
        fcntl.ioctl(sys.stdout.fileno(), LINUX_TIOCGDEV, output_device, True)
        descriptor = os.open(
            "/dev/tty",
            os.O_WRONLY | os.O_NOCTTY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        terminal = os.fstat(descriptor)
        terminal_device = bytearray(4)
        fcntl.ioctl(descriptor, LINUX_TIOCGDEV, terminal_device, True)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise WireGuardError(
            "Could not verify a direct one-time delivery terminal."
        ) from error
    try:
        foreground = os.tcgetpgrp(descriptor) == os.getpgrp()
    except OSError as error:
        os.close(descriptor)
        raise WireGuardError(
            "Could not verify the foreground delivery terminal."
        ) from error
    if (
        not stat.S_ISCHR(terminal.st_mode)
        or not os.isatty(descriptor)
        or not foreground
        or input_device != terminal_device
        or output_device != terminal_device
    ):
        os.close(descriptor)
        raise WireGuardError("One-time profile delivery requires the direct terminal.")
    return descriptor


def _write_profile_once(profile: str, descriptor: int) -> None:
    """Write profile bytes once to the verified terminal without retry output."""
    payload = profile.encode("ascii")
    try:
        written = os.write(descriptor, payload)
    except OSError as error:
        raise WireGuardError(
            "One-time profile delivery failed; revoke this pending peer."
        ) from error
    finally:
        os.close(descriptor)
    if written != len(payload):
        raise WireGuardError(
            "One-time profile delivery was incomplete; revoke this pending peer."
        )


def generate_peer(
    config: dict[str, Any], peer_id: str, owner: str, purpose: str, endpoint: str
) -> tuple[str, str, int]:
    """Create pending metadata and return one profile only in memory.

    Args:
        config: Validated Gateway host configuration.
        peer_id: Unique peer identifier.
        owner: Approved device or user owner.
        purpose: Reason for the peer's access.
        endpoint: Reachable IPv4 address or DNS name for client profiles.

    Returns:
        One-time profile, public-key fingerprint, and verified terminal descriptor.

    Raises:
        WireGuardError: If inputs, peer state, or terminal delivery setup is invalid.
    """
    wireguard = _enabled(config)
    endpoint = _validate_profile_endpoint(endpoint)
    if os.geteuid() != 0:
        raise WireGuardError("WireGuard peer administration requires container root.")
    if not PEER_ID_PATTERN.fullmatch(peer_id):
        raise WireGuardError(
            "Peer ID must use 1-64 letters, digits, dots, underscores, or hyphens."
        )
    if (
        not owner.strip()
        or len(owner) > 128
        or not purpose.strip()
        or len(purpose) > 256
    ):
        raise WireGuardError(
            "Peer owner and purpose must be non-empty, bounded metadata."
        )
    _run(["ip", "link", "show", "dev", INTERFACE])
    terminal = _direct_tty()
    try:
        descriptor, state = _locked_state()
    except WireGuardError:
        os.close(terminal)
        raise
    private_key = ""
    peer: dict[str, Any] | None = None
    stored = False
    try:
        if any(entry["id"] == peer_id for entry in state["peers"]):
            raise WireGuardError(
                "Peer ID already exists; revoke it before reusing the ID."
            )
        private_key = _run(["wg", "genkey"])
        public_key = _run(["wg", "pubkey"], input_text=private_key)
        if not KEY_PATTERN.fullmatch(private_key) or not KEY_PATTERN.fullmatch(
            public_key
        ):
            raise WireGuardError("WireGuard generated invalid key material.")
        if any(entry["public_key"] == public_key for entry in state["peers"]):
            raise WireGuardError("Generated WireGuard public key already exists.")
        peer = {
            "id": peer_id,
            "owner": owner.strip(),
            "purpose": purpose.strip(),
            "address": str(_peer_address(wireguard, state["peers"])),
            "public_key": public_key,
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
        }
        state["peers"].append(peer)
        _audit(
            state,
            "generate-pending",
            peer,
            "profile generated for one-time terminal delivery",
        )
        _write_peers(state)
        stored = True
        profile = _profile(config, wireguard, private_key, peer, endpoint)
    except (OSError, WireGuardError) as error:
        os.close(terminal)
        if stored and peer is not None:
            fingerprint = hashlib.sha256(peer["public_key"].encode("ascii")).hexdigest()
            raise WireGuardError(
                f"Could not prepare the profile for pending peer {peer_id}, public "
                f"fingerprint {fingerprint}; revoke it and do not retry."
            ) from error
        raise
    finally:
        os.close(descriptor)
    return (
        profile,
        hashlib.sha256(peer["public_key"].encode("ascii")).hexdigest(),
        terminal,
    )


def _expiry(value: str) -> str:
    """Validate and normalize a future UTC expiry timestamp."""
    try:
        expires = datetime.fromisoformat(value)
    except ValueError as error:
        raise WireGuardError(
            "Expiry must be an ISO-8601 timestamp with a UTC offset."
        ) from error
    if (
        expires.tzinfo is None
        or expires.utcoffset() is None
        or expires <= datetime.now(UTC)
    ):
        raise WireGuardError("Expiry must be a future timezone-aware timestamp.")
    return expires.astimezone(UTC).isoformat()


def approve_peer(
    config: dict[str, Any], peer_id: str, approval_reference: str, expires_at: str
) -> str:
    """Activate one pending peer after explicit approval metadata is supplied."""
    if os.geteuid() != 0:
        raise WireGuardError("WireGuard peer administration requires container root.")
    if (
        not PEER_ID_PATTERN.fullmatch(peer_id)
        or not approval_reference.strip()
        or len(approval_reference) > 128
    ):
        raise WireGuardError("Peer ID and approval reference are required.")
    expiry = _expiry(expires_at)
    wireguard = _enabled(config)
    descriptor, state = _locked_state()
    try:
        peer = next((entry for entry in state["peers"] if entry["id"] == peer_id), None)
        if peer is None or peer["status"] != "pending":
            raise WireGuardError("Only an existing pending peer can be approved.")
        pool = ipaddress.IPv4Network(wireguard["address_pool"], strict=True)
        if ipaddress.IPv4Address(peer["address"]) not in pool:
            raise WireGuardError("Pending peer address is outside the configured pool.")
        _run(["ip", "link", "show", "dev", INTERFACE])
        _activate_peer(peer)
        peer["status"] = "approved"
        peer["approval_reference"] = approval_reference.strip()[:128]
        peer["expires_at"] = expiry
        _audit(state, "approve", peer, "approved peer activated")
        try:
            _write_peers(state)
        except WireGuardError:
            try:
                _deactivate_peer(peer)
            except WireGuardError:
                _run(["ip", "link", "set", "dev", INTERFACE, "down"])
            raise
        return hashlib.sha256(peer["public_key"].encode("ascii")).hexdigest()
    finally:
        os.close(descriptor)


def revoke_peer(peer_id: str, reason: str) -> str:
    """Revoke exactly one peer and persist only public metadata."""
    if os.geteuid() != 0:
        raise WireGuardError("WireGuard peer administration requires container root.")
    if not PEER_ID_PATTERN.fullmatch(peer_id) or not reason.strip():
        raise WireGuardError("Peer ID and revocation reason are required.")
    descriptor, state = _locked_state()
    try:
        peer = next((entry for entry in state["peers"] if entry["id"] == peer_id), None)
        if peer is None or peer["status"] == "revoked":
            raise WireGuardError("Peer does not exist or is already revoked.")
        was_approved = peer["status"] == "approved"
        peer["status"] = "revoked"
        peer["revoked_at"] = datetime.now(UTC).isoformat()
        peer["revocation_reason"] = reason.strip()[:256]
        _audit(state, "revoke", peer, "peer disabled in inventory")
        _write_peers(state)
        if was_approved:
            try:
                _deactivate_peer(peer)
            except WireGuardError:
                try:
                    _run(["ip", "link", "set", "dev", INTERFACE, "down"])
                except WireGuardError:
                    raise WireGuardError(
                        "Peer is revoked in inventory, but WireGuard could not be disabled."
                    )
                raise WireGuardError(
                    "Peer is revoked in inventory; wg0 was disabled after removal failed."
                )
        return hashlib.sha256(peer["public_key"].encode("ascii")).hexdigest()
    finally:
        os.close(descriptor)


def _valid_approved_peers(
    state: dict[str, Any], wireguard: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return approved peers whose explicit expiry has not passed."""
    now = datetime.now(UTC)
    result = []
    pool = ipaddress.IPv4Network(wireguard["address_pool"], strict=True)
    occupied: set[ipaddress.IPv4Address] = set()
    for peer in state["peers"]:
        try:
            address = ipaddress.IPv4Address(peer["address"])
        except (KeyError, ipaddress.AddressValueError) as error:
            raise WireGuardError(
                "WireGuard peer address metadata is invalid."
            ) from error
        if address not in pool or address in occupied:
            raise WireGuardError(
                "WireGuard peer addresses are duplicated or outside the pool."
            )
        occupied.add(address)
        if peer["status"] != "approved":
            continue
        try:
            expires = datetime.fromisoformat(peer["expires_at"])
        except (KeyError, ValueError) as error:
            raise WireGuardError("Approved peer expiry metadata is invalid.") from error
        if expires.tzinfo is None or expires <= now:
            continue
        result.append(peer)
    return result


def _interfaces(config: dict[str, Any]) -> tuple[str, ...]:
    """Resolve the exact configured Podman interfaces inside the Gateway."""
    configured = [
        ipaddress.IPv4Network(entry["subnet"], strict=True)
        for entry in config["networks"]
    ]
    if not configured:
        raise WireGuardError("WireGuard requires configured Podman networks.")
    result = _run(["ip", "-j", "-4", "address", "show"])
    try:
        records = json.loads(result)
    except json.JSONDecodeError as error:
        raise WireGuardError("Gateway interface inventory is invalid.") from error
    found: set[str] = set()
    for subnet in configured:
        matches = {
            item["ifname"]
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("ifname"), str)
            and any(
                isinstance(address, dict)
                and address.get("family") == "inet"
                and isinstance(address.get("local"), str)
                and ipaddress.IPv4Address(address["local"]) in subnet
                for address in item.get("addr_info", [])
            )
        }
        if len(matches) != 1:
            raise WireGuardError(
                "Could not resolve one Gateway interface for each configured network."
            )
        found.update(matches)
    return tuple(sorted(found))


def _configure_server(config: dict[str, Any], wireguard: dict[str, Any]) -> str:
    """Create the IPv4 WireGuard interface and reconcile approved peers."""
    _assert_no_fail_stop_marker()
    if not Path("/sys/module/wireguard").is_dir():
        raise WireGuardError(
            "Host kernel WireGuard support is unavailable; no module was loaded."
        )
    _validate_server_key_metadata(SERVER_KEY_PATH)
    if not Path("/var/lib/gateway/wireguard").is_dir():
        raise WireGuardError("Persistent WireGuard peer storage is not mounted.")
    state = _read_peers()
    podman_interfaces = _interfaces(config)
    _run(["ip", "link", "add", "dev", INTERFACE, "type", "wireguard"])
    previous_forwarding: str | None = None
    try:
        _run(
            [
                "wg",
                "set",
                INTERFACE,
                "listen-port",
                str(wireguard["listen_port"]),
                "private-key",
                str(SERVER_KEY_PATH),
            ]
        )
        _run(
            [
                "ip",
                "-4",
                "address",
                "add",
                f"{wireguard['server_address']}/32",
                "dev",
                INTERFACE,
            ]
        )
        previous_forwarding = acquire_forwarding(OWNER_ID, podman_interfaces)
        _run(["ip", "link", "set", "dev", INTERFACE, "up"])
        for peer in _valid_approved_peers(state, wireguard):
            _activate_peer(peer)
        return previous_forwarding
    except ForwardingRollbackError as error:
        message = _fail_stop_forwarding_rollback(wireguard)
        raise WireGuardError(message) from error
    except (OSError, WireGuardError, ForwardingError) as error:
        try:
            _run(["ip", "link", "del", "dev", INTERFACE])
        except WireGuardError as cleanup_error:
            raise WireGuardError(
                "CRITICAL: could not remove wg0 after WireGuard server activation failed."
            ) from cleanup_error
        if previous_forwarding is not None:
            release_forwarding(OWNER_ID, previous_forwarding)
        raise WireGuardError(
            "Could not safely activate the WireGuard server."
        ) from error


def run_server(config: dict[str, Any]) -> None:
    """Run the configured server until shutdown, then remove only its interface."""
    _assert_no_fail_stop_marker()
    wireguard = _enabled(config)
    previous_forwarding = _configure_server(config, wireguard)
    stopping = False

    def stop(_signal: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            _assert_interface_up()
            _expire_peers()
            time.sleep(1)
    finally:
        try:
            _run(["ip", "link", "del", "dev", INTERFACE])
        finally:
            release_forwarding(OWNER_ID, previous_forwarding)


def _expire_peers() -> None:
    """Remove expired peers and persist revocation before the next interval."""
    descriptor, state = _locked_state()
    expired = []
    try:
        now = datetime.now(UTC)
        for peer in state["peers"]:
            if peer["status"] != "approved":
                continue
            expires = datetime.fromisoformat(peer["expires_at"])
            if expires.tzinfo is not None and expires <= now:
                peer["status"] = "revoked"
                peer["revoked_at"] = now.isoformat()
                peer["revocation_reason"] = "approved expiry elapsed"
                _audit(state, "expire", peer, "peer expiry elapsed")
                expired.append(peer)
        if expired:
            _write_peers(state)
            for peer in expired:
                _deactivate_peer(peer)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    """Run WireGuard server or peer administration and report sanitized errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run the configured WireGuard server")
    run_parser.add_argument("config", nargs="?", default=str(CONFIG_PATH))
    fail_stop_parser = commands.add_parser(
        "fail-stop", help="install traffic drops while a critical marker exists"
    )
    fail_stop_parser.add_argument("config", nargs="?", default=str(CONFIG_PATH))
    peer_parser = commands.add_parser("peer", help="manage one-time WireGuard peers")
    operations = peer_parser.add_subparsers(dest="operation", required=True)
    generate = operations.add_parser(
        "generate", help="create a pending peer profile once"
    )
    generate.add_argument("--id", required=True)
    generate.add_argument("--owner", required=True)
    generate.add_argument("--purpose", required=True)
    generate.add_argument("--endpoint", required=True)
    server_key_parser = commands.add_parser(
        "server-key", help="provision the persistent server key"
    )
    server_key_operations = server_key_parser.add_subparsers(
        dest="operation", required=True
    )
    server_key_generate = server_key_operations.add_parser(
        "generate", help="generate the server key without replacing an existing key"
    )
    server_key_generate.add_argument("--filename", required=True)
    server_key_operations.add_parser(
        "validate", help="validate the mounted server key without displaying it"
    )
    approve = operations.add_parser("approve", help="activate a pending peer")
    approve.add_argument("peer_id")
    approve.add_argument("--approval-reference", required=True)
    approve.add_argument("--expires-at", required=True)
    revoke = operations.add_parser("revoke", help="revoke only the named peer")
    revoke.add_argument("peer_id")
    revoke.add_argument("--reason", required=True)
    operations.add_parser("list", help="list public peer metadata")
    args = parser.parse_args(argv)
    try:
        if args.command == "server-key":
            if os.geteuid() != 0:
                raise WireGuardError(
                    "WireGuard server-key provisioning requires container root."
                )
            if args.operation == "generate":
                _generate_server_key(args.filename)
                _validate_server_key_metadata(SERVER_KEY_PATH.parent / args.filename)
                print(
                    f"[wireguard] Created server key at "
                    f"{SERVER_KEY_PATH.parent / args.filename}.",
                    file=sys.stderr,
                )
                return 0
            _validate_server_key_file()
            print("[wireguard] Existing server key is valid.", file=sys.stderr)
            return 0
        if args.command == "run":
            run_server(load_host_config(args.config))
            return 0
        if args.command == "fail-stop":
            if os.geteuid() != 0:
                raise WireGuardError(
                    "WireGuard fail-stop firewall requires container root."
                )
            wireguard = _enabled(load_host_config(args.config))
            _install_fail_stop_drop(wireguard)
            print(
                "[wireguard] CRITICAL: fail-stop firewall drops installed; "
                "WireGuard remains disabled pending operator recovery.",
                file=sys.stderr,
            )
            return 0
        if os.geteuid() != 0:
            raise WireGuardError(
                "WireGuard peer administration requires container root."
            )
        config = load_host_config(CONFIG_PATH)
        if args.operation == "generate":
            profile, fingerprint, terminal = generate_peer(
                config, args.id, args.owner, args.purpose, args.endpoint
            )
            try:
                print(
                    f"[wireguard] Pending peer {args.id}; public fingerprint {fingerprint}. "
                    "One-time profile follows; approve separately before use.",
                    file=sys.stderr,
                )
            except OSError as error:
                os.close(terminal)
                raise WireGuardError(
                    f"Could not announce pending peer {args.id}, public fingerprint "
                    f"{fingerprint}; revoke it and do not retry."
                ) from error
            try:
                _write_profile_once(profile, terminal)
            except WireGuardError as error:
                print(
                    f"[wireguard] ERROR: {error} Peer {args.id}, public fingerprint {fingerprint}; do not retry or recover.",
                    file=sys.stderr,
                )
                return 1
            return 0
        if args.operation == "approve":
            _enabled(config)
            fingerprint = approve_peer(
                config, args.peer_id, args.approval_reference, args.expires_at
            )
            print(
                f"[wireguard] Approved peer {args.peer_id}; public fingerprint {fingerprint}.",
                file=sys.stderr,
            )
            return 0
        if args.operation == "revoke":
            fingerprint = revoke_peer(args.peer_id, args.reason)
            print(
                f"[wireguard] Revoked peer {args.peer_id}; public fingerprint {fingerprint}.",
                file=sys.stderr,
            )
            return 0
        state = _read_peers()
        public_peers = [
            {key: value for key, value in peer.items() if key != "public_key"}
            | {
                "public_fingerprint": hashlib.sha256(
                    peer["public_key"].encode("ascii")
                ).hexdigest()
            }
            for peer in state["peers"]
        ]
        print(
            json.dumps({"peers": public_peers, "audit": state["audit"]}, sort_keys=True)
        )
        return 0
    except (OSError, KeyError, TypeError, ValueError, WireGuardError) as error:
        print(f"[wireguard] ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
