"""Validate and render explicit readiness-scoped Gateway DNS handoffs.

The CLI hashes effective configuration, validates a scoped target-identity
request, inspects those identities through Podman's local socket, and returns
an atomic-replacement candidate on stdout. It never writes the hosts file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try:
    from .dns_records import generate_dns_records
    from .host_config_validation import load_host_config, validate_host_config
    from .strict_json import loads_json
except ImportError:
    from dns_records import generate_dns_records
    from host_config_validation import load_host_config, validate_host_config
    from strict_json import loads_json

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
_REVISION = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


def effective_config_revision(config: Mapping[str, Any]) -> str:
    """Return SHA-256 of canonical validated effective host configuration."""
    validate_host_config(dict(config))
    canonical = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def request_revision(request: Any) -> str:
    """Validate the handoff envelope and return its configuration revision."""
    if not isinstance(request, dict) or set(request) != {
        "config_revision",
        "target_scope",
        "ready_targets",
    }:
        raise ValueError(
            "handoff must contain config_revision, target_scope, and ready_targets"
        )
    revision = request["config_revision"]
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise ValueError("config_revision must be a sha256 revision")
    return revision


def validate_handoff_request(
    config: Mapping[str, Any], request: Any
) -> tuple[list[str], dict[str, str]]:
    """Validate exact configured target scope and immutable ready identities."""
    validate_host_config(dict(config))
    request_revision(request)
    records = config.get("dns_records", [])
    configured = {record["container"] for record in records}
    scope = request["target_scope"]
    if (
        not isinstance(scope, list)
        or not scope
        or not all(isinstance(name, str) for name in scope)
        or len(scope) != len(set(scope))
        or not set(scope) <= configured
    ):
        raise ValueError("target_scope must list unique configured DNS container names")

    ready_targets = request["ready_targets"]
    if not isinstance(ready_targets, list):
        raise TypeError("ready_targets must be a list of container identities")
    identities: dict[str, str] = {}
    for target in ready_targets:
        if (
            not isinstance(target, dict)
            or set(target) != {"container", "id"}
            or not isinstance(target["container"], str)
            or not isinstance(target["id"], str)
            or not _CONTAINER_ID.fullmatch(target["id"])
        ):
            raise ValueError(
                "each ready target must contain configured container and full ID"
            )
        name = target["container"]
        if name not in scope:
            raise ValueError("ready target is outside target_scope")
        if name in identities:
            raise ValueError("ready_targets contains a duplicate configured container")
        identities[name] = target["id"]
    return scope, identities


def merge_scoped_hosts(
    config: Mapping[str, Any],
    current_hosts: str,
    target_scope: list[str],
    refreshed_records: list[str],
) -> str:
    """Replace only scoped target records and retain other configured records."""
    configured_records = config.get("dns_records", [])
    names_by_container: dict[str, set[str]] = {}
    all_names: set[str] = set()
    for record in configured_records:
        names_by_container.setdefault(record["container"], set()).add(record["name"])
        all_names.add(record["name"])
    replaced_names = set().union(
        *(names_by_container.get(container, set()) for container in target_scope)
    )

    retained: dict[str, str] = {}
    for line in current_hosts.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) < 2:
            raise ValueError(
                "existing generated DNS hosts file contains an invalid line"
            )
        address, *names = fields
        for name in names:
            if name in all_names and name not in replaced_names:
                retained[name] = address

    refreshed: dict[str, str] = {}
    for line in refreshed_records:
        address, name = line.split(maxsplit=1)
        if name not in replaced_names:
            raise ValueError("refreshed DNS record is outside target_scope")
        refreshed[name] = address
    retained.update(refreshed)

    output = ["# Managed by readiness-scoped Gateway DNS refresh"]
    for record in configured_records:
        address = retained.get(record["name"])
        if address:
            output.append(f"{address} {record['name']}")
        elif record["container"] in target_scope:
            output.append(
                f"# PENDING DNS target: {record['name']} "
                f"({record['container']} readiness/unverified)"
            )
    return "\n".join(output) + "\n"


def render_handoff(
    config: dict[str, Any],
    request: Any,
    current_hosts: str,
    run_command: CommandRunner,
) -> str:
    """Return generated hosts content for one valid, scoped readiness handoff."""
    validate_host_config(config)
    expected_revision = request_revision(request)
    if expected_revision != effective_config_revision(config):
        raise ValueError("handoff config_revision is stale")
    scope, ready_targets = validate_handoff_request(config, request)
    scoped_config = dict(config)
    scoped_config["dns_records"] = [
        record
        for record in config.get("dns_records", [])
        if record["container"] in scope
    ]
    records = generate_dns_records(scoped_config, ready_targets, run_command)
    return merge_scoped_hosts(config, current_hosts, scope, records)


def main(argv: list[str] | None = None) -> int:
    """Run revision or handoff CLI; print only revision or generated hosts."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    revision_parser = commands.add_parser("revision")
    revision_parser.add_argument("config", help="JSON Gateway host configuration")
    request_revision_parser = commands.add_parser("request-revision")
    request_revision_parser.add_argument("request", help="JSON readiness handoff")
    handoff_parser = commands.add_parser("handoff")
    handoff_parser.add_argument("--config", required=True)
    handoff_parser.add_argument("--hosts", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "revision":
            config = load_host_config(args.config)
            print(effective_config_revision(config))
            return 0
        if args.command == "request-revision":
            request = loads_json(Path(args.request).read_text(encoding="utf-8"))
            print(request_revision(request))
            return 0

        config = load_host_config(args.config)
        request = loads_json(sys.stdin.read())
        current_hosts = Path(args.hosts).read_text(encoding="utf-8")
        refreshed_hosts = render_handoff(
            config,
            request,
            current_hosts,
            subprocess.run,
        )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"[gateway] ERROR: DNS readiness handoff rejected: {error}", file=sys.stderr
        )
        return 1

    print(refreshed_hosts, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
