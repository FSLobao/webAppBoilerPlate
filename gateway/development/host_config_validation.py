"""Validate host configuration rules shared by Gateway entrypoints.

The public functions reject removed configuration fields, validate optional
startup-readiness settings, and load JSON with duplicate-key protection. The
CLI validates one host configuration for container startup.
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
    """Validate removed fields and optional Gateway startup-readiness settings.

    Raises:
        ValueError: The configuration uses a removed field or invalid readiness settings.
    """
    if not isinstance(config, dict):
        return
    gateway = config.get("gateway")
    if isinstance(gateway, dict) and "networks" in gateway:
        raise ValueError(
            "'gateway.networks' is not supported; declare Podman networks "
            "in top-level 'networks'"
        )
    if isinstance(gateway, dict) and "startup_readiness" in gateway:
        readiness = gateway["startup_readiness"]
        expected_fields = {"timeout_seconds", "interval_seconds"}
        if not isinstance(readiness, dict) or set(readiness) != expected_fields:
            raise ValueError(
                "gateway.startup_readiness must contain exactly "
                "'timeout_seconds' and 'interval_seconds'"
            )
        timeout_seconds = readiness["timeout_seconds"]
        interval_seconds = readiness["interval_seconds"]
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 300
        ):
            raise ValueError(
                "gateway.startup_readiness.timeout_seconds must be an integer "
                "between 1 and 300"
            )
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, int)
            or not 1 <= interval_seconds <= 10
        ):
            raise ValueError(
                "gateway.startup_readiness.interval_seconds must be an integer "
                "between 1 and 10"
            )
        if interval_seconds > timeout_seconds:
            raise ValueError(
                "gateway.startup_readiness.interval_seconds must not exceed "
                "timeout_seconds"
            )
    if "application_gateway" in config:
        raise ValueError(
            "'application_gateway' is not supported; use 'http_proxy' for "
            "optional HTTP reverse-proxy configuration"
        )


def load_host_config(path: str | Path) -> Any:
    """Load strict JSON and reject removed host-configuration fields.

    Raises:
        OSError: The configuration file cannot be read.
        ValueError: The JSON is invalid or uses a removed configuration field.
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
