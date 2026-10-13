"""Tests for Gateway configuration address validation."""

import json

import pytest

from scripts.gateway.config_validation import (
    validate_address_declarations,
    validate_config_file,
)


def test_accepts_ipv4_address_and_disjoint_networks() -> None:
    """Accept canonical, non-overlapping IPv4 declarations."""
    validate_address_declarations(
        {
            "gateway": {"bind_address": "127.0.0.1"},
            "networks": [
                {"name": "project-a", "subnet": "10.89.1.0/24"},
                {"name": "project-b", "subnet": "10.89.2.0/24"},
            ],
        }
    )


def test_accepts_host_networks_without_gateway() -> None:
    """Validate host network declarations without gateway-specific fields."""
    validate_address_declarations(
        {"networks": [{"name": "database", "subnet": "10.90.0.0/24"}]}
    )


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            {"gateway": {"bind_address": "::1"}, "networks": []},
            "gateway.bind_address must be an IPv4 address",
        ),
        (
            {
                "gateway": {"bind_address": "127.0.0.1"},
                "networks": [{"name": "project-a", "subnet": "10.89.1.7/24"}],
            },
            "has host bits set",
        ),
        (
            {
                "gateway": {"bind_address": "127.0.0.1"},
                "networks": [{"name": "project-a", "subnet": "2001:db8::/64"}],
            },
            "subnet must be IPv4",
        ),
        (
            {
                "gateway": {"bind_address": "127.0.0.1"},
                "networks": [
                    {"name": "project-a", "subnet": "10.89.1.0/24"},
                    {"name": "project-b", "subnet": "10.89.1.128/25"},
                ],
            },
            "overlaps",
        ),
    ],
)
def test_rejects_invalid_address_declarations(
    config: dict[str, object], message: str
) -> None:
    """Reject malformed, non-IPv4, or overlapping address declarations."""
    with pytest.raises(ValueError, match=message):
        validate_address_declarations(config)


def test_validate_config_file_reads_json(tmp_path) -> None:
    """Read and validate a JSON file through the public file interface."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "gateway": {"bind_address": "127.0.0.1"},
                "networks": [{"name": "project-a", "subnet": "10.89.1.0/24"}],
            }
        ),
        encoding="utf-8",
    )

    validate_config_file(config_path)