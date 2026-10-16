"""Expose shared host-configuration checks to repository Python modules."""

from gateway.development.host_config_validation import (
    load_host_config,
    main,
    validate_host_config,
)

__all__ = ["load_host_config", "main", "validate_host_config"]


if __name__ == "__main__":
    raise SystemExit(main())
