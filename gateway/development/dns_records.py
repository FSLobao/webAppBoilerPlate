"""Inspect readiness-confirmed Gateway DNS targets.

The public generator inspects only immutable container identities supplied by
an explicit handoff. It returns active ``IPv4 name`` records without writing
files; callers own atomic publication.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

try:
    from .host_config_validation import validate_host_config
except ImportError:
    from host_config_validation import validate_host_config

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


def _inspect_target_network(
    run_command: CommandRunner,
    container_id: str,
    network_name: str,
) -> tuple[str, str, str, str, str]:
    """Read only identity, readiness, and one configured network address."""
    format_string = (
        "{{.Id}}|{{.Name}}|{{.State.Running}}|{{.State.Health.Status}}|"
        "{{with index .NetworkSettings.Networks "
        + json.dumps(network_name)
        + "}}{{.IPAddress}}{{end}}"
    )
    result = run_command(
        [
            "podman",
            "inspect",
            "--type",
            "container",
            "--format",
            format_string,
            container_id,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or f"cannot inspect configured target on '{network_name}'"
        )
    fields = result.stdout.rstrip("\n").split("|")
    if len(fields) != 5:
        raise ValueError(
            f"invalid inspection result for configured network '{network_name}'"
        )
    return fields[0], fields[1], fields[2], fields[3], fields[4]


def _configured_targets(config: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Group configured DNS records by exact container identity name."""
    records_by_container: dict[str, list[dict[str, str]]] = {}
    for record in config.get("dns_records", []):
        records_by_container.setdefault(record["container"], []).append(record)
    return records_by_container


def generate_dns_records(
    config: dict[str, Any],
    ready_targets: Mapping[str, str],
    run_command: CommandRunner = subprocess.run,
) -> list[str]:
    """Return DNS records for currently healthy, readiness-confirmed targets.

    Args:
        config: Structurally validated Gateway host configuration.
        ready_targets: Mapping of configured container names to full Podman IDs.
        run_command: Subprocess-compatible runner, injectable for tests.

    Returns:
        Active ``IPv4 name`` records. Missing, stopped, or unhealthy identities
        are pending and produce no record.

    Raises:
        RuntimeError: Podman inspection fails for a reason other than absence.
        TypeError: A supplied target identity has an invalid type.
        ValueError: A supplied identity is invalid or inspected network data
            conflicts with the configured target.
    """
    validate_host_config(config)
    records_by_container = _configured_targets(config)
    unknown_targets = set(ready_targets) - set(records_by_container)
    if unknown_targets:
        raise ValueError("handoff includes a target not declared in dns_records")

    networks = {
        entry["name"]: ipaddress.ip_network(entry["subnet"], strict=True)
        for entry in config["networks"]
    }
    records: list[str] = []
    for container_name, container_id in ready_targets.items():
        if not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(
            container_id
        ):
            raise TypeError(
                f"invalid Podman identity for configured target '{container_name}'"
            )

        exists = run_command(
            ["podman", "container", "exists", container_id],
            check=False,
            capture_output=True,
            text=True,
        )
        if exists.returncode == 1:
            continue
        if exists.returncode:
            raise RuntimeError(
                exists.stderr.strip()
                or f"cannot inspect configured target '{container_name}'"
            )

        inspected_networks: dict[str, ipaddress.IPv4Address] = {}
        target_records: list[str] = []
        target_pending = False
        for record in records_by_container[container_name]:
            network_name = record["network"]
            if network_name not in inspected_networks:
                try:
                    (
                        inspected_id,
                        inspected_name,
                        running,
                        health,
                        address,
                    ) = _inspect_target_network(run_command, container_id, network_name)
                except RuntimeError as inspect_error:
                    recheck = run_command(
                        ["podman", "container", "exists", container_id],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if recheck.returncode == 1:
                        target_pending = True
                        break
                    if recheck.returncode:
                        raise RuntimeError(
                            recheck.stderr.strip()
                            or f"cannot recheck configured target '{container_name}' "
                            "after inspection failure"
                        ) from inspect_error
                    raise
                if inspected_id != container_id:
                    raise ValueError(
                        f"Podman identity changed for configured target "
                        f"'{container_name}'"
                    )
                if inspected_name.removeprefix("/") != container_name:
                    target_pending = True
                    break
                if running != "true" or health != "healthy":
                    target_pending = True
                    break
                if not address:
                    raise ValueError(
                        f"healthy configured target '{container_name}' is not "
                        f"attached to declared network '{network_name}'"
                    )
                parsed_address = ipaddress.ip_address(address)
                if (
                    parsed_address.version != 4
                    or parsed_address not in networks[network_name]
                ):
                    raise ValueError(
                        f"configured target '{container_name}' has an invalid address "
                        f"on '{network_name}': {address}"
                    )
                inspected_networks[network_name] = parsed_address
            if target_pending:
                break
            target_records.append(
                f"{inspected_networks[network_name]} {record['name']}"
            )
        if not target_pending:
            records.extend(target_records)
    return records
