"""Run Python-only, read-only host and Podman preflight checks.

Gateway network checks report planned creation and DNS readiness without
inspecting application containers. Both checks reject unrelated overlapping
IPv4 host routes while permitting exact routes tied to inspected Podman
bridges. Gateway checks also validate configured remote pools and literal
endpoints against that route snapshot. Generic host checks inspect declared
container state and report stopped containers as pending.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import pathlib
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scripts.gateway.host_config_validation import (
    load_host_config,
    validate_host_config,
)
from scripts.gateway.remote_access import (
    OwnedRoute,
    RouteOwner,
    RouteSpec,
    validate_remote_access_config,
    validate_remote_access_host_routes,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

TARGET_HOST_OS_ID = "rhel"
TARGET_HOST_OS_VERSION = "9.8"
TARGET_PODMAN_VERSION = "5.8.2"


@dataclass(frozen=True)
class PodmanNetwork:
    """Hold inspected network details needed to validate declared routes."""

    subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
    interface: str | None
    gateways: frozenset[ipaddress.IPv4Address]


def host_platform_matches_target(os_id: str, os_version: str) -> bool:
    """Return whether the host matches the RHEL 9.8 deployment target."""
    return os_id == TARGET_HOST_OS_ID and os_version == TARGET_HOST_OS_VERSION


def podman_version_matches_target(version: str) -> bool:
    """Return whether a Podman version matches the 5.8.2 deployment target.

    Args:
        version: Podman's client version, optionally prefixed with ``v``.

    Returns:
        True only for version 5.8.2. Other or malformed versions return False.
    """
    return version.removeprefix("v") == TARGET_PODMAN_VERSION


def selinux_mode_matches_target(mode: str) -> bool:
    """Return whether SELinux is already disabled on the deployment host."""
    return mode == "Disabled"


def cockpit_password_is_valid(password_path: str | pathlib.Path) -> bool:
    """Return whether a Cockpit secret contains one non-empty line.

    Trailing LF bytes are allowed. Embedded LF, CR, and NUL bytes are rejected.
    File read errors return False. This function does not change the file.
    """
    try:
        password = pathlib.Path(password_path).read_bytes().rstrip(b"\n")
    except OSError:
        return False
    return (
        bool(password)
        and b"\n" not in password
        and b"\r" not in password
        and b"\0" not in password
    )


def _run_json(run_command: CommandRunner, *args: str) -> Any:
    """Run a Podman command and parse its JSON output."""
    result = run_command(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(args)}")
    return json.loads(result.stdout)


def _network_subnets(
    network: dict[str, Any],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Return parsed subnets from one Podman network inspection result."""
    raw_subnets = network.get("subnets", [])
    if isinstance(raw_subnets, dict):
        raw_subnets = [raw_subnets]
    return [
        ipaddress.ip_network(item["subnet"], strict=True)
        for item in raw_subnets
        if item.get("subnet")
    ]


def _network_gateways(network: dict[str, Any]) -> frozenset[ipaddress.IPv4Address]:
    """Return IPv4 bridge addresses from one Podman network inspection result."""
    raw_subnets = network.get("subnets", [])
    if isinstance(raw_subnets, dict):
        raw_subnets = [raw_subnets]
    return frozenset(
        address
        for item in raw_subnets
        if item.get("gateway")
        for address in [ipaddress.ip_address(item["gateway"])]
        if address.version == 4
    )


def _inspect_podman_networks(
    run_command: CommandRunner,
) -> dict[str, PodmanNetwork]:
    """Read existing Podman networks and exact bridge metadata."""
    names_output = run_command(
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    networks = {}
    for name in names_output.splitlines():
        inspected = _run_json(run_command, "podman", "network", "inspect", name)
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise TypeError(f"invalid Podman network inspection for '{name}'")
        details = inspected[0]
        if not isinstance(details, dict):
            raise TypeError(f"invalid Podman network inspection for '{name}'")
        interface = details.get("network_interface")
        if interface is not None and (not isinstance(interface, str) or not interface):
            raise ValueError(f"invalid Podman network interface for '{name}'")
        networks[name] = PodmanNetwork(
            subnets=_network_subnets(details),
            interface=interface,
            gateways=_network_gateways(details),
        )
    return networks


def _validate_declared_networks(
    config: dict[str, Any],
    existing_networks: dict[str, PodmanNetwork],
    *,
    allow_missing: bool,
    announce: Callable[[str], None] = print,
) -> dict[str, ipaddress.IPv4Network]:
    """Validate configured IPv4 networks against inspected Podman state.

    Args:
        config: Structurally validated host configuration.
        existing_networks: Inspected Podman network details.
        allow_missing: Permit absent declared networks and report planned creation.
        announce: Receives planned network messages.

    Raises:
        KeyError, TypeError, ValueError: Inspected state conflicts with config.
    """
    declared_networks = {
        entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
        for entry in config["networks"]
    }
    for name, subnet in declared_networks.items():
        for existing_name, subnets in existing_networks.items():
            if existing_name == name:
                continue
            for existing_subnet in subnets.subnets:
                if subnet.version == existing_subnet.version and subnet.overlaps(
                    existing_subnet
                ):
                    raise ValueError(
                        f"declared network '{name}' subnet {subnet} overlaps existing "
                        f"Podman network '{existing_name}' subnet {existing_subnet}"
                    )

        if name not in existing_networks:
            if allow_missing:
                announce(
                    f"[host-preflight] PENDING network creation: {name} ({subnet})"
                )
                continue
            raise ValueError(f"declared host network '{name}' is absent")
        ipv4_subnets = [
            current
            for current in existing_networks[name].subnets
            if current.version == 4
        ]
        if ipv4_subnets != [subnet]:
            raise ValueError(
                f"existing Podman network '{name}' does not match "
                f"declared subnet {subnet}"
            )
    return declared_networks


def _route_matches_managed_network(
    route: dict[str, Any],
    destination: ipaddress.IPv4Network,
    network: PodmanNetwork | None,
) -> bool:
    """Return whether a route exactly belongs to the inspected Podman bridge."""
    if network is None or network.interface is None:
        return False
    if route.get("dev") != network.interface:
        return False
    if route.get("protocol") != "kernel" or route.get("gateway") or route.get("via"):
        return False
    if route.get("multipath") or route.get("nexthops"):
        return False

    route_type = route.get("type")
    table = route.get("table")
    if (
        route_type in (None, "unicast")
        and route.get("scope") == "link"
        and table in (None, "main", 254)
    ):
        return any(
            subnet.version == 4 and subnet == destination for subnet in network.subnets
        )

    return (
        route_type == "local"
        and route.get("scope") == "host"
        and table in ("local", 255)
        and destination.prefixlen == 32
        and destination.network_address in network.gateways
        and any(
            subnet.version == 4 and destination.subnet_of(subnet)
            for subnet in network.subnets
        )
    )


def _read_host_routes(run_command: CommandRunner) -> list[dict[str, Any]]:
    """Read and validate one IPv4 route-table snapshot."""
    command = ["ip", "-j", "-4", "route", "show", "table", "all"]
    result = run_command(command, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or f"command failed: {' '.join(command)}"
        )
    routes = json.loads(result.stdout)
    if not isinstance(routes, list):
        raise TypeError("IPv4 route output must be a JSON array")
    if any(not isinstance(route, dict) for route in routes):
        raise TypeError("IPv4 route entries must be JSON objects")
    return routes


def _validate_host_routes(
    declared_networks: dict[str, ipaddress.IPv4Network],
    existing_networks: dict[str, PodmanNetwork],
    run_command: CommandRunner,
    routes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Reject declared CIDRs that overlap unrelated IPv4 routes."""
    if not declared_networks:
        return routes
    routes = routes if routes is not None else _read_host_routes(run_command)

    for route in routes:
        raw_destination = route.get("dst")
        if raw_destination == "default":
            continue
        if not isinstance(raw_destination, str):
            raise TypeError("IPv4 route entry has no valid destination")
        destination = ipaddress.ip_network(raw_destination, strict=False)
        if destination.version != 4 or destination.prefixlen == 0:
            continue

        for name, subnet in declared_networks.items():
            if not subnet.overlaps(destination):
                continue
            network = existing_networks.get(name)
            if _route_matches_managed_network(route, destination, network):
                continue
            raise ValueError(
                f"declared network '{name}' subnet {subnet} overlaps host IPv4 "
                f"route {destination} (table={route.get('table', 'unspecified')}, "
                f"dev={route.get('dev', 'unspecified')})"
            )
    return routes


def _validate_remote_access_routes(
    config: dict[str, Any], routes: list[dict[str, Any]]
) -> None:
    """Check configured pools and endpoints, allowing only tagged Gateway return routes."""
    gateway = config.get("gateway")
    remote_access = gateway.get("remote_access") if isinstance(gateway, dict) else None
    if remote_access is None:
        return
    transports = {
        "openvpn": remote_access.get("openvpn"),
        "ssh_tun": remote_access.get("ssh_tun"),
        "wireguard": remote_access.get("wireguard"),
    }
    active_routes: list[OwnedRoute] = []
    active_owners: dict[str, list[RouteOwner]] = {
        "openvpn": [],
        "ssh_tun": [],
        "wireguard": [],
    }
    networks = config.get("networks", [])
    addresses = [
        (
            ipaddress.ip_network(network["subnet"], strict=True),
            ipaddress.ip_address(network["gateway_address"]),
            network["name"],
        )
        for network in networks
        if isinstance(network, dict) and "gateway_address" in network
    ]
    addresses.sort(
        key=lambda entry: (int(entry[0].network_address), entry[0].prefixlen, entry[2])
    )
    if addresses:
        for transport, metadata in transports.items():
            if not isinstance(metadata, dict):
                continue
            pool_field = "client_pool" if transport == "openvpn" else "address_pool"
            if pool_field not in metadata:
                continue
            expected_pool = ipaddress.ip_network(metadata[pool_field], strict=True)
            expected_gateway = addresses[0][1]
            owner = RouteOwner(transport, f"{transport}-managed-return-route")
            for route in routes:
                raw_destination = route.get("dst")
                if not isinstance(raw_destination, str) or raw_destination == "default":
                    continue
                destination = ipaddress.ip_network(raw_destination, strict=False)
                if (
                    destination == expected_pool
                    and route.get("gateway") == str(expected_gateway)
                    and route.get("protocol") in (186, "186")
                    and route.get("type") in (None, "unicast")
                    and route.get("table") in (None, "main", 254)
                    and not route.get("multipath")
                    and not route.get("nexthops")
                ):
                    active_routes.append(
                        OwnedRoute(
                            RouteSpec(
                                destination,
                                "host",
                                interface=route.get("dev"),
                                gateway=expected_gateway,
                                table=route.get("table", "main"),
                            ),
                            owner,
                        )
                    )
                    active_owners[transport].append(owner)
    validate_remote_access_host_routes(
        config,
        routes,
        active_routes=active_routes,
        active_owners=active_owners,
    )


def _validate_openvpn_profile_file(config: dict[str, Any]) -> None:
    """Check enabled profile metadata without opening its contents."""
    gateway = config.get("gateway")
    remote_access = gateway.get("remote_access") if isinstance(gateway, dict) else None
    openvpn = remote_access.get("openvpn") if isinstance(remote_access, dict) else None
    if not isinstance(openvpn, dict) or openvpn.get("enabled") is not True:
        return
    profile_path = pathlib.Path(openvpn["profile_path"])
    try:
        profile_stat = profile_path.lstat()
    except OSError as error:
        raise ValueError("configured OpenVPN profile is unavailable") from error
    if (
        not stat.S_ISREG(profile_stat.st_mode)
        or profile_path.is_symlink()
        or profile_stat.st_uid != 0
        or not (stat.S_IMODE(profile_stat.st_mode) & 0o400)
        or stat.S_IMODE(profile_stat.st_mode) & 0o177
    ):
        raise ValueError(
            "configured OpenVPN profile must be a root-owned private regular file"
        )


def _validate_ssh_tun_keys_file(config: dict[str, Any]) -> None:
    """Check enabled SSH TUN public-key mount metadata without parsing keys."""
    gateway = config.get("gateway")
    remote_access = gateway.get("remote_access") if isinstance(gateway, dict) else None
    ssh_tun = remote_access.get("ssh_tun") if isinstance(remote_access, dict) else None
    if not isinstance(ssh_tun, dict) or ssh_tun.get("enabled") is not True:
        return
    keys_path = pathlib.Path(ssh_tun["authorized_keys_path"])
    try:
        keys_stat = keys_path.lstat()
    except OSError as error:
        raise ValueError("configured SSH TUN public-key file is unavailable") from error
    if (
        not stat.S_ISREG(keys_stat.st_mode)
        or keys_path.is_symlink()
        or keys_stat.st_uid != 0
        or stat.S_IMODE(keys_stat.st_mode) & 0o022
        or keys_stat.st_size == 0
    ):
        raise ValueError(
            "configured SSH TUN public-key file must be a non-empty, "
            "root-owned regular file that is not group/world writable"
        )


def _require_external_key_path(
    key_path: pathlib.Path, repository_root: pathlib.Path
) -> None:
    """Reject a WireGuard server key resolved inside the checked-out repository."""
    try:
        resolved_key_path = key_path.resolve(strict=True)
        resolved_repository_root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("configured WireGuard server key is unavailable") from error
    if resolved_key_path.is_relative_to(resolved_repository_root):
        raise ValueError(
            "configured WireGuard server key must be outside the Git repository"
        )


def _validate_wireguard_inputs(config: dict[str, Any]) -> None:
    """Check kernel support and server-key metadata without opening the key."""
    gateway = config.get("gateway")
    remote_access = gateway.get("remote_access") if isinstance(gateway, dict) else None
    wireguard = (
        remote_access.get("wireguard") if isinstance(remote_access, dict) else None
    )
    if not isinstance(wireguard, dict) or wireguard.get("enabled") is not True:
        return
    if not pathlib.Path("/sys/module/wireguard").is_dir():
        raise ValueError(
            "WireGuard kernel support is not loaded; load it through host policy, "
            "not Gateway deployment"
        )
    key_path = pathlib.Path(wireguard["server_private_key_path"])
    repository_root = pathlib.Path(__file__).resolve().parents[2]
    _require_external_key_path(key_path, repository_root)
    try:
        key_stat = key_path.lstat()
    except OSError as error:
        raise ValueError("configured WireGuard server key is unavailable") from error
    mode = stat.S_IMODE(key_stat.st_mode)
    if (
        not stat.S_ISREG(key_stat.st_mode)
        or key_path.is_symlink()
        or key_stat.st_uid != 0
        or mode & 0o077
        or not mode & 0o400
    ):
        raise ValueError(
            "WireGuard server key must be a readable, root-owned private regular file"
        )


def validate_gateway_networks(
    config: dict[str, Any],
    run_command: CommandRunner | None = None,
    announce: Callable[[str], None] = print,
) -> None:
    """Check Gateway networks, remote pools, and DNS readiness from config alone.

    Args:
        config: Structurally validated host configuration.
        run_command: Subprocess-compatible runner, injectable for tests.
        announce: Receives planned network and pending DNS messages.

    Raises:
        RuntimeError: A Podman or route command fails.
        KeyError, TypeError, ValueError: Inspected network state, remote-access
            metadata, or host routes conflict with config.
        subprocess.CalledProcessError: Listing Podman networks fails.

    External commands: ``podman network ls``, ``podman network inspect``, and
    ``ip -j -4 route show table all``.
    The function never inspects application containers or mutates host state.
    """
    validate_host_config(config)
    validate_remote_access_config(config)
    _validate_openvpn_profile_file(config)
    _validate_ssh_tun_keys_file(config)
    _validate_wireguard_inputs(config)
    command_runner = run_command or subprocess.run
    existing_networks = _inspect_podman_networks(command_runner)
    declared_networks = _validate_declared_networks(
        config,
        existing_networks,
        allow_missing=True,
        announce=announce,
    )
    routes = _validate_host_routes(declared_networks, existing_networks, command_runner)
    gateway = config.get("gateway")
    if isinstance(gateway, dict) and gateway.get("remote_access") is not None:
        routes = routes if routes is not None else _read_host_routes(command_runner)
        _validate_remote_access_routes(config, routes)
    for record in config.get("dns_records", []):
        announce(
            f"[host-preflight] PENDING DNS target: {record['name']} "
            f"({record['container']} readiness/unverified)"
        )


def validate_podman_state(
    config: dict[str, Any],
    run_command: CommandRunner | None = None,
    announce: Callable[[str], None] = print,
) -> None:
    """Check existing declared networks and generic container attachments.

    Args:
        config: Structurally validated host configuration. ``gateway`` is optional.
        run_command: Subprocess-compatible runner, injectable for tests.
        announce: Receives stopped-container messages; defaults to standard output.

    Raises:
        RuntimeError: A Podman or route command fails.
        KeyError, TypeError, ValueError: Inspected state or host routes conflict with config.
        subprocess.CalledProcessError: Listing Podman networks fails.

    External commands: ``podman network ls``, ``podman network inspect``,
    ``ip -j -4 route show table all``, ``podman container exists``, and
    ``podman inspect``. This generic check is read-only and retains its
    container-inspection behavior.
    """
    validate_host_config(config)
    command_runner = run_command or subprocess.run
    existing_networks = _inspect_podman_networks(command_runner)
    declared_networks = _validate_declared_networks(
        config,
        existing_networks,
        allow_missing=False,
        announce=announce,
    )
    _validate_host_routes(declared_networks, existing_networks, command_runner)
    container_networks: dict[str, set[str]] = {}
    for declaration in config.get("containers", []):
        container_networks.setdefault(declaration["name"], set()).update(
            declaration["networks"]
        )
    dns_records_by_container: dict[str, list[dict[str, str]]] = {}
    for record in config.get("dns_records", []):
        container_networks.setdefault(record["container"], set()).add(record["network"])
        dns_records_by_container.setdefault(record["container"], []).append(record)

    for container_name, network_names in container_networks.items():
        result = command_runner(
            ["podman", "container", "exists", container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 1:
            raise ValueError(f"configured container '{container_name}' is absent")
        if result.returncode:
            raise RuntimeError(
                result.stderr.strip() or f"cannot inspect container '{container_name}'"
            )

        container = _run_json(
            command_runner,
            "podman",
            "inspect",
            "--type",
            "container",
            container_name,
        )[0]
        attached = container.get("NetworkSettings", {}).get("Networks", {})
        if not container.get("State", {}).get("Running", False):
            dns_records = dns_records_by_container.get(container_name, [])
            if dns_records:
                for record in dns_records:
                    announce(
                        f"[host-preflight] PENDING DNS target: {record['name']} "
                        f"({container_name} is stopped)"
                    )
            else:
                announce(
                    f"[host-preflight] PENDING container: {container_name} is stopped"
                )
            continue

        for network_name in sorted(network_names):
            if network_name not in attached:
                raise ValueError(
                    f"container '{container_name}' is not attached to declared network "
                    f"'{network_name}'"
                )
            address = attached[network_name].get("IPAddress", "")
            parsed_address = ipaddress.ip_address(address) if address else None
            if (
                parsed_address is None
                or parsed_address.version != 4
                or parsed_address not in declared_networks[network_name]
            ):
                raise ValueError(
                    f"running container '{container_name}' has no valid IPv4 address "
                    f"in declared network '{network_name}': {address}"
                )


def main(argv: list[str] | None = None) -> int:
    """Run a host-preflight check and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="check", required=True)
    host_parser = commands.add_parser(
        "host-platform", help="check host matches RHEL 9.8"
    )
    host_parser.add_argument("os_id", help="host operating-system ID")
    host_parser.add_argument("os_version", help="host operating-system version")
    version_parser = commands.add_parser(
        "podman-version", help="check Podman client version is 5.8.2"
    )
    version_parser.add_argument("version", help="Podman client version")
    selinux_parser = commands.add_parser(
        "selinux-mode", help="check SELinux is Disabled"
    )
    selinux_parser.add_argument("mode", help="current SELinux mode")
    password_parser = commands.add_parser(
        "password-file",
        help="check that a Cockpit password file has one non-empty line",
    )
    password_parser.add_argument("path", help="Cockpit password file")
    state_parser = commands.add_parser(
        "podman-state",
        help="check declared host networks and containers against Podman",
    )
    state_parser.add_argument("config", help="JSON host configuration")
    gateway_parser = commands.add_parser(
        "gateway-networks",
        help="check Gateway networks and report planned network/DNS readiness",
    )
    gateway_parser.add_argument("config", help="JSON host configuration")
    args = parser.parse_args(argv)

    if args.check == "host-platform":
        return 0 if host_platform_matches_target(args.os_id, args.os_version) else 1
    if args.check == "podman-version":
        return 0 if podman_version_matches_target(args.version) else 1
    if args.check == "selinux-mode":
        return 0 if selinux_mode_matches_target(args.mode) else 1
    if args.check == "password-file":
        return 0 if cockpit_password_is_valid(args.path) else 1

    try:
        config = load_host_config(args.config)
        if args.check == "gateway-networks":
            validate_gateway_networks(config, run_command=subprocess.run)
        else:
            validate_podman_state(config, run_command=subprocess.run)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"[host-preflight] ERROR: host preflight check failed: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
