"""Generate Gateway DNS host records from live Podman containers.

The public function returns records without writing files. The CLI reads a
configuration path, inspects Podman, and writes ``IPv4 name`` lines to stdout.
Errors go to stderr and return status 1. The shell caller owns staging and file
permissions.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from scripts.gateway.host_config_validation import (
    load_host_config,
    validate_host_config,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _run_json(run_command: CommandRunner, *args: str) -> Any:
    """Run a Podman command and parse its JSON output."""
    result = run_command(*args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(args)}")
    return json.loads(result.stdout)


def generate_dns_records(
    config: dict[str, Any], run_command: CommandRunner = subprocess.run
) -> list[str]:
    """Return validated DNS records for running containers.

    Args:
        config: Structurally validated gateway configuration.
        run_command: Subprocess-compatible runner, injectable for tests.

    Returns:
        One ``IPv4 name`` string for each configured DNS record.

    Raises:
        RuntimeError: A Podman command fails.
        KeyError, TypeError, ValueError: Target state or address is invalid.

    External commands: ``podman container exists`` and ``podman inspect``.
    This function is read-only and writes no files.
    """
    validate_host_config(config)
    networks = {
        entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
        for entry in config["networks"]
    }
    records = []
    for record in config["dns_records"]:
        exists = run_command(
            ["podman", "container", "exists", record["container"]],
            check=False,
            capture_output=True,
            text=True,
        )
        if exists.returncode == 1:
            raise ValueError(
                f"configured DNS target container '{record['container']}' is absent"
            )
        if exists.returncode:
            raise RuntimeError(
                exists.stderr.strip()
                or f"cannot inspect container '{record['container']}'"
            )

        container = _run_json(
            run_command,
            "podman",
            "inspect",
            "--type",
            "container",
            record["container"],
        )[0]
        attached = container.get("NetworkSettings", {}).get("Networks", {})
        if not container.get("State", {}).get("Running", False):
            raise ValueError(
                f"configured DNS target container '{record['container']}' stopped "
                "before DNS generation"
            )
        if record["network"] not in attached:
            raise ValueError(
                f"container '{record['container']}' is not attached to declared network "
                f"'{record['network']}'"
            )

        address = attached[record["network"]].get("IPAddress", "")
        parsed_address = ipaddress.ip_address(address)
        if (
            parsed_address.version != 4
            or parsed_address not in networks[record["network"]]
        ):
            raise ValueError(
                f"container '{record['container']}' has an invalid address on "
                f"'{record['network']}': {address}"
            )
        records.append(f"{parsed_address} {record['name']}")
    return records


def main(argv: list[str] | None = None) -> int:
    """Run DNS record generation CLI; write records to stdout on success."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON gateway configuration")
    args = parser.parse_args(argv)

    try:
        config = load_host_config(args.config)
        records = generate_dns_records(config)
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
            f"[gateway] ERROR: DNS generation failed: {error}",
            file=sys.stderr,
        )
        return 1

    for record in records:
        print(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())