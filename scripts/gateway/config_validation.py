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


def validate_address_declarations(config: dict[str, Any]) -> None:
    """Validate an optional gateway IPv4 address and non-overlapping subnets.

    Args:
        config: Parsed host configuration. The ``gateway`` section is optional.

    Raises:
        KeyError: A required address or subnet field is missing.
        TypeError: A field has an unsupported type.
        ValueError: An address is not IPv4, a subnet is non-canonical, or two
            declared subnets overlap.
    """
    if "gateway" in config:
        bind_address = ipaddress.ip_address(config["gateway"]["bind_address"])
        if bind_address.version != 4:
            raise ValueError("gateway.bind_address must be an IPv4 address")

    networks = []
    for entry in config["networks"]:
        subnet = ipaddress.ip_network(entry["subnet"], strict=True)
        if subnet.version != 4:
            raise ValueError(f"network '{entry['name']}' subnet must be IPv4")
        for known_name, known_subnet in networks:
            if subnet.overlaps(known_subnet):
                raise ValueError(
                    f"network '{entry['name']}' subnet {subnet} overlaps "
                    f"network '{known_name}' subnet {known_subnet}"
                )
        networks.append((entry["name"], subnet))


def validate_config_file(config_path: str | Path) -> None:
    """Read JSON configuration and validate its IP address declarations.

    Args:
        config_path: Path to an already structurally validated JSON file.

    Raises:
        OSError: The file cannot be read.
        json.JSONDecodeError: The file does not contain valid JSON.
        KeyError, TypeError, ValueError: Address or subnet declarations fail.
    """
    with Path(config_path).open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    validate_address_declarations(config)


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