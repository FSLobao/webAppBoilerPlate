"""Tests for Gateway configuration address validation."""

import json

import pytest

from scripts.gateway.config_validation import (
    validate_address_declarations,
    validate_http_proxy_networks,
    validate_config_file,
)


def test_accepts_ipv4_address_and_disjoint_networks() -> None:
    """Accept canonical, non-overlapping IPv4 declarations."""
    validate_address_declarations(
        {
            "gateway": {
                "bind_address": "127.0.0.1",
                "ssh_bind_address": "0.0.0.0",
                "cockpit_bind_address": "127.0.0.1",
            },
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


def test_accepts_static_gateway_addresses_inside_networks() -> None:
    """Accept usable, in-subnet addresses for Gateway interfaces."""
    validate_address_declarations(
        {
            "networks": [
                {
                    "name": "shared",
                    "subnet": "192.168.9.0/24",
                    "gateway_address": "192.168.9.2",
                },
                {
                    "name": "webApp",
                    "subnet": "192.168.8.0/29",
                    "gateway_address": "192.168.8.2",
                },
            ]
        }
    )


def test_accepts_http_proxy_upstreams_on_shared_network() -> None:
    """Accept HTTP proxy routes when both upstreams share a declared network."""
    validate_http_proxy_networks(
        {
            "containers": [
                {"name": "nginx", "networks": ["shared"]},
                {"name": "webApp", "networks": ["webApp", "shared"]},
            ],
            "http_proxy": {
                "enabled": True,
                "routes": [{"frontend": "webApp", "backend": "webApp"}],
            },
        }
    )


def test_rejects_http_proxy_upstream_without_shared_network() -> None:
    """Reject HTTP proxy routes that cannot reach their configured upstream."""
    with pytest.raises(ValueError, match="shares no network"):
        validate_http_proxy_networks(
            {
                "containers": [
                    {"name": "nginx", "networks": ["shared"]},
                    {"name": "webApp", "networks": ["webApp"]},
                ],
                "http_proxy": {
                    "enabled": True,
                    "routes": [{"frontend": "webApp", "backend": "webApp"}],
                },
            }
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
                "gateway": {
                    "bind_address": "127.0.0.1",
                    "ssh_bind_address": "::1",
                },
                "networks": [],
            },
            "gateway.ssh_bind_address must be an IPv4 address",
        ),
        (
            {
                "http_proxy": {"listen_address": "::1"},
                "networks": [],
            },
            "http_proxy.listen_address must be an IPv4 address",
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
                "networks": [
                    {
                        "name": "project-a",
                        "subnet": "10.89.1.0/24",
                        "gateway_address": "10.89.2.2",
                    }
                ]
            },
            "is outside subnet",
        ),
        (
            {
                "networks": [
                    {
                        "name": "project-a",
                        "subnet": "10.89.1.0/24",
                        "gateway_address": "10.89.1.0",
                    }
                ]
            },
            "not a usable host address",
        ),
        (
            {
                "networks": [
                    {
                        "name": "project-a",
                        "subnet": "10.89.1.0/24",
                        "gateway_address": "10.89.1.255",
                    }
                ]
            },
            "not a usable host address",
        ),
        (
            {
                "networks": [
                    {
                        "name": "project-a",
                        "subnet": "10.89.1.0/24",
                        "gateway_address": "2001:db8::2",
                    }
                ]
            },
            "gateway_address must be IPv4",
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


def test_validate_config_file_rejects_duplicate_keys(tmp_path) -> None:
    """Reject duplicate configuration keys before JSON object parsing loses them."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"schema_version": 2, "schema_version": 1, "networks": []}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        validate_config_file(config_path)


def test_validate_config_file_rejects_gateway_networks(tmp_path) -> None:
    """Reject the removed Gateway network selector in a parsed configuration."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"gateway": {"networks": ["app-net"]}, "networks": []}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gateway.networks.*not supported"):
        validate_config_file(config_path)


def test_address_validation_rejects_gateway_networks_directly() -> None:
    """Reject the removed selector through the public dictionary validator."""
    with pytest.raises(ValueError, match="gateway.networks.*not supported"):
        validate_address_declarations(
            {
                "gateway": {"networks": ["app-net"]},
                "networks": [],
            }
        )


def test_validate_config_file_rejects_application_gateway_section(tmp_path) -> None:
    """Reject the removed proxy section instead of accepting a legacy alias."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"application_gateway": {}, "networks": []}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="application_gateway.*not supported"):
        validate_config_file(config_path)
