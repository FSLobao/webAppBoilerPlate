"""Run Python-only, read-only host and Podman preflight checks.

Gateway network checks report planned creation and DNS readiness without
inspecting application containers. Generic host checks also inspect declared
container state and report stopped containers as pending.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from scripts.gateway.host_config_validation import (
    load_host_config,
    validate_host_config,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

TARGET_HOST_OS_ID = "rhel"
TARGET_HOST_OS_VERSION = "9.8"
TARGET_PODMAN_VERSION = "5.8.2"


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
    return bool(password) and b"\n" not in password and b"\r" not in password and b"\0" not in password


def _run_json(run_command: CommandRunner, *args: str) -> Any:
    """Run a Podman command and parse its JSON output."""
    result = run_command(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(args)}")
    return json.loads(result.stdout)


def _network_subnets(network: dict[str, Any]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Return parsed subnets from one Podman network inspection result."""
    raw_subnets = network.get("subnets", [])
    if isinstance(raw_subnets, dict):
        raw_subnets = [raw_subnets]
    return [
        ipaddress.ip_network(item["subnet"], strict=True)
        for item in raw_subnets
        if item.get("subnet")
    ]


def _inspect_podman_networks(
    run_command: CommandRunner,
) -> dict[str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]]:
    """Read all existing Podman network names and subnets."""
    names_output = run_command(
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    networks = {}
    for name in names_output.splitlines():
        details = _run_json(run_command, "podman", "network", "inspect", name)[0]
        networks[name] = _network_subnets(details)
    return networks


def _validate_declared_networks(
    config: dict[str, Any],
    existing_networks: dict[
        str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]
    ],
    *,
    allow_missing: bool,
    announce: Callable[[str], None] = print,
) -> dict[str, ipaddress.IPv4Network]:
    """Validate configured IPv4 networks against inspected Podman state.

    Args:
        config: Structurally validated host configuration.
        existing_networks: Inspected Podman network subnets.
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
            for existing_subnet in subnets:
                if (
                    subnet.version == existing_subnet.version
                    and subnet.overlaps(existing_subnet)
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
            current for current in existing_networks[name] if current.version == 4
        ]
        if ipv4_subnets != [subnet]:
            raise ValueError(
                f"existing Podman network '{name}' does not match "
                f"declared subnet {subnet}"
            )
    return declared_networks


def validate_gateway_networks(
    config: dict[str, Any],
    run_command: CommandRunner | None = None,
    announce: Callable[[str], None] = print,
) -> None:
    """Check Gateway networks and report DNS readiness from config alone.

    Args:
        config: Structurally validated host configuration.
        run_command: Subprocess-compatible runner, injectable for tests.
        announce: Receives planned network and pending DNS messages.

    Raises:
        RuntimeError: A Podman command fails.
        KeyError, TypeError, ValueError: Inspected network state conflicts with config.
        subprocess.CalledProcessError: Listing Podman networks fails.

    External commands: ``podman network ls`` and ``podman network inspect``.
    The function never inspects application containers or mutates host state.
    """
    validate_host_config(config)
    command_runner = run_command or subprocess.run
    existing_networks = _inspect_podman_networks(command_runner)
    _validate_declared_networks(
        config,
        existing_networks,
        allow_missing=True,
        announce=announce,
    )
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
        RuntimeError: A Podman command fails.
        KeyError, TypeError, ValueError: Inspected state conflicts with config.
        subprocess.CalledProcessError: Listing Podman networks fails.

    External commands: ``podman network ls``, ``podman network inspect``,
    ``podman container exists``, and ``podman inspect``. This generic check is
    read-only and retains its container-inspection behavior.
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
                result.stderr.strip()
                or f"cannot inspect container '{container_name}'"
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
                announce(f"[host-preflight] PENDING container: {container_name} is stopped")
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
        "password-file", help="check that a Cockpit password file has one non-empty line"
    )
    password_parser.add_argument("path", help="Cockpit password file")
    state_parser = commands.add_parser(
        "podman-state", help="check declared host networks and containers against Podman"
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
            f"[host-preflight] ERROR: Podman state check failed: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())