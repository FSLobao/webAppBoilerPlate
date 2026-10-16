"""Validate host configuration rules shared by Gateway entrypoints.

The public functions reject the removed ``gateway.networks`` field and load
JSON with duplicate-key protection. The CLI validates one host configuration
for container startup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__:
    from .strict_json import load_json
else:
    from strict_json import load_json


def validate_host_config(config: Any) -> None:
    """Reject removed Gateway-level network configuration.

    Raises:
        ValueError: The configuration declares ``gateway.networks``.
    """
    if not isinstance(config, dict):
        return
    gateway = config.get("gateway")
    if isinstance(gateway, dict) and "networks" in gateway:
        raise ValueError(
            "'gateway.networks' is not supported; declare Podman networks "
            "in top-level 'networks'"
        )


def load_host_config(path: str | Path) -> Any:
    """Load strict JSON and reject removed host-configuration fields.

    Raises:
        OSError: The configuration file cannot be read.
        ValueError: The JSON is invalid or uses ``gateway.networks``.
    """
    config = load_json(path)
    validate_host_config(config)
    return config


def main(argv: list[str] | None = None) -> int:
    """Validate one host configuration and report failures to stderr."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON host configuration path")
    args = parser.parse_args(argv)

    try:
        load_host_config(args.config)
    except (OSError, ValueError) as error:
        print(
            f"[host-config] ERROR: invalid host configuration: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
