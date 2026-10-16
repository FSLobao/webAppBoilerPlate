"""Expose the shared strict JSON loader to repository Python modules."""

from gateway.development.strict_json import (
    DuplicateKeyError,
    load_json,
    loads_json,
    main,
)

__all__ = ["DuplicateKeyError", "load_json", "loads_json", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
