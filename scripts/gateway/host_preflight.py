"""Run Python-only, read-only host and Podman preflight checks.

The CLI checks Podman versions, Cockpit password-file content, and configured
Podman networks and containers. State checks are read-only and report stopped
containers as pending.
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

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def podman_version_supported(version: str) -> bool:
    """Return whether a Podman version is at least 4.4.

    Args:
        version: Podman's client version, optionally prefixed with ``v``.

    Returns:
        True when the first two numeric version components are at least 4.4.
        Malformed versions return False.
    """
    try:
        parts = tuple(int(part) for part in version.lstrip("v").split(".")[:2])
    except ValueError:
        return False
    return parts >= (4, 4)


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


def validate_podman_state(
    config: dict[str, Any],
    run_command: CommandRunner = subprocess.run,
    announce: Callable[[str], None] = print,
    allow_missing_gateway_networks: bool = False,
) -> None:
    """Check declared host networks and container attachments against Podman.

    Args:
        config: Structurally validated host configuration. ``gateway`` is
            optional; its selected networks may be created during deployment.
        run_command: Subprocess-compatible runner, injectable for tests.
        announce: Receives pending-target messages; defaults to standard output.
        allow_missing_gateway_networks: Permit selected gateway networks to be
            absent before gateway deployment creates them.

    Raises:
        RuntimeError: A Podman command fails.
        KeyError, TypeError, ValueError: Inspected state conflicts with config.
        subprocess.CalledProcessError: Listing Podman networks fails.

    External commands: ``podman network ls``, ``podman network inspect``,
    ``podman container exists``, and ``podman inspect``. The function is
    read-only and does not start containers or create networks.
    """
    names_output = run_command(
        ["podman", "network", "ls", "--format", "{{.Name}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    existing_networks = {}
    for name in names_output.splitlines():
        details = _run_json(run_command, "podman", "network", "inspect", name)[0]
        existing_networks[name] = _network_subnets(details)

    declared_networks = {
        entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
        for entry in config["networks"]
    }
    gateway = config.get("gateway")
    gateway_networks = set(
        gateway.get("networks", declared_networks) if gateway else ()
    )
    for name, subnet in declared_networks.items():
        for existing_name, subnets in existing_networks.items():
            if existing_name == name:
                continue
            for existing_subnet in subnets:
                if subnet.overlaps(existing_subnet):
                    raise ValueError(
                        f"declared network '{name}' subnet {subnet} overlaps existing "
                        f"Podman network '{existing_name}' subnet {existing_subnet}"
                    )

        if name not in existing_networks:
            if allow_missing_gateway_networks and name in gateway_networks:
                continue
            raise ValueError(f"declared host network '{name}' is absent")
        ipv4_subnets = [
            current for current in existing_networks[name] if current.version == 4
        ]
        if ipv4_subnets != [subnet]:
            raise ValueError(
                f"existing Podman network '{name}' does not match declared subnet {subnet}"
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
        result = run_command(
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
            run_command,
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
    version_parser = commands.add_parser(
        "podman-version", help="check Podman client version is at least 4.4"
    )
    version_parser.add_argument("version", help="Podman client version")
    password_parser = commands.add_parser(
        "password-file", help="check that a Cockpit password file has one non-empty line"
    )
    password_parser.add_argument("path", help="Cockpit password file")
    state_parser = commands.add_parser(
        "podman-state", help="check declared host networks and containers against Podman"
    )
    state_parser.add_argument("config", help="JSON host configuration")
    state_parser.add_argument(
        "--allow-missing-gateway-networks",
        action="store_true",
        help="allow selected gateway networks to be created during deployment",
    )
    args = parser.parse_args(argv)

    if args.check == "podman-version":
        return 0 if podman_version_supported(args.version) else 1
    if args.check == "password-file":
        return 0 if cockpit_password_is_valid(args.path) else 1

    try:
        with pathlib.Path(args.config).open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        validate_podman_state(
            config,
            allow_missing_gateway_networks=args.allow_missing_gateway_networks,
        )
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