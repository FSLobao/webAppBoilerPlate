"""Validate IP address and subnet declarations in host configuration.

The public function reads no host state and changes no files. The module CLI
accepts one JSON configuration path and reports validation failures to stderr.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any

from scripts.gateway.host_config_validation import (
    load_host_config,
    validate_host_config,
)


def validate_address_declarations(config: dict[str, Any]) -> None:
    """Validate Gateway bind addresses, optional interface IPs, and subnets.

    Args:
        config: Parsed host configuration. The ``gateway`` section is optional.

    Raises:
        KeyError: A required address or subnet field is missing.
        TypeError: A field has an unsupported type.
        ValueError: An address is invalid or outside its subnet, a subnet is
            non-canonical, or two declared subnets overlap.
    """
    validate_host_config(config)
    validate_host_config(config)
    if "gateway" in config:
        for field in (
            "bind_address",
            "ssh_bind_address",
            "cockpit_bind_address",
        ):
            if field in config["gateway"]:
                bind_address = ipaddress.ip_address(config["gateway"][field])
                if bind_address.version != 4:
                    raise ValueError(
                        f"gateway.{field} must be an IPv4 address"
                    )
    if "application_gateway" in config:
        bind_address = ipaddress.ip_address(
            config["application_gateway"]["listen_address"]
        )
        if bind_address.version != 4:
            raise ValueError("application_gateway.listen_address must be an IPv4 address")

    networks = []
    gateway_addresses: set[ipaddress.IPv4Address] = set()
    for entry in config["networks"]:
        subnet = ipaddress.ip_network(entry["subnet"], strict=True)
        if subnet.version != 4:
            raise ValueError(f"network '{entry['name']}' subnet must be IPv4")
        if "gateway_address" in entry:
            raw_address = entry["gateway_address"]
            if not isinstance(raw_address, str):
                raise ValueError(
                    f"network '{entry['name']}' gateway_address must be an IPv4 address"
                )
            address = ipaddress.ip_address(raw_address)
            if address.version != 4:
                raise ValueError(
                    f"network '{entry['name']}' gateway_address must be IPv4"
                )
            if address not in subnet:
                raise ValueError(
                    f"network '{entry['name']}' gateway_address {address} "
                    f"is outside subnet {subnet}"
                )
            if address in (subnet.network_address, subnet.broadcast_address):
                raise ValueError(
                    f"network '{entry['name']}' gateway_address {address} "
                    f"is not a usable host address in subnet {subnet}"
                )
            if address in gateway_addresses:
                raise ValueError(f"duplicate Gateway address {address}")
            gateway_addresses.add(address)
        for known_name, known_subnet in networks:
            if subnet.overlaps(known_subnet):
                raise ValueError(
                    f"network '{entry['name']}' subnet {subnet} overlaps "
                    f"network '{known_name}' subnet {known_subnet}"
                )
        networks.append((entry["name"], subnet))


def validate_application_gateway_networks(config: dict[str, Any]) -> None:
    """Require NGINX and each enabled upstream to share a declared network."""
    validate_host_config(config)
    validate_host_config(config)
    application_gateway = config.get("application_gateway")
    if not application_gateway or not application_gateway["enabled"]:
        return

    containers = {
        entry["name"]: set(entry["networks"])
        for entry in config.get("containers", [])
    }
    nginx_networks = containers.get("nginx")
    if nginx_networks is None:
        raise ValueError(
            "application_gateway requires an 'nginx' container declaration"
        )

    for route in application_gateway["routes"]:
        for upstream in (route["frontend"], route["backend"]):
            upstream_networks = containers.get(upstream)
            if upstream_networks is None:
                raise ValueError(
                    f"application_gateway upstream '{upstream}' is not declared"
                )
            if not nginx_networks.intersection(upstream_networks):
                raise ValueError(
                    f"application_gateway upstream '{upstream}' shares no network "
                    "with 'nginx'"
                )


def validate_config_file(config_path: str | Path) -> None:
    """Read JSON configuration and validate its IP address declarations.

    Args:
        config_path: Path to an already structurally validated JSON file.

    Raises:
        OSError: The file cannot be read.
        json.JSONDecodeError: The file does not contain valid JSON.
        KeyError, TypeError, ValueError: Address or subnet declarations fail.
    """
    config = load_host_config(config_path)
    validate_address_declarations(config)
    validate_application_gateway_networks(config)


def main(argv: list[str] | None = None) -> int:
    """Run the address validation CLI; return 0 on success and 1 on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON configuration path")
    args = parser.parse_args(argv)

    try:
        validate_config_file(args.config)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(
            f"[host-preflight] ERROR: invalid address/network declaration: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())