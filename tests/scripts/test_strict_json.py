"""Tests for duplicate-key-safe JSON parsing."""

import pytest

from gateway.development.host_config_validation import (
    load_host_config,
    main as validate_host_config_main,
)
from scripts.gateway.strict_json import DuplicateKeyError, loads_json


@pytest.mark.parametrize(
    "contents",
    [
        '{"networks": [], "networks": []}',
        '{"gateway": {"name": "first", "name": "second"}}',
    ],
)
def test_rejects_duplicate_keys_at_every_object_level(contents: str) -> None:
    """Reject repeated keys in top-level and nested JSON objects."""
    with pytest.raises(DuplicateKeyError, match="duplicate JSON object key"):
        loads_json(contents)


def test_generic_strict_json_loader_accepts_host_schema_specific_key() -> None:
    """Keep duplicate-key parsing generic rather than embedding host schema."""
    assert loads_json('{"gateway": {"networks": ["app-net"]}}') == {
        "gateway": {"networks": ["app-net"]}
    }


def test_startup_host_config_validator_rejects_gateway_networks(
    tmp_path, capsys
) -> None:
    """Reject the removed field through the validator used by container startup."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"gateway": {"networks": ["app-net"]}, "networks": []}',
        encoding="utf-8",
    )

    assert validate_host_config_main([str(config_path)]) == 1
    assert "gateway.networks" in capsys.readouterr().err
