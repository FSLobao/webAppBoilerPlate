"""Load JSON documents while rejecting duplicate object keys.

The public loaders parse files and strings without side effects. The CLI
validates one JSON file for shell entrypoints before they pass it to jq.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class DuplicateKeyError(ValueError):
    """Report a repeated key in a JSON object."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object and reject a key that has already appeared."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def loads_json(contents: str) -> Any:
    """Parse JSON text and reject duplicate keys at every object level."""
    return json.loads(contents, object_pairs_hook=_unique_object)


def load_json(path: str | Path) -> Any:
    """Read and parse a JSON file while rejecting duplicate keys."""
    with Path(path).open(encoding="utf-8") as config_file:
        return loads_json(config_file.read())


def main(argv: list[str] | None = None) -> int:
    """Validate a JSON file and report parse failures to stderr."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON configuration path")
    args = parser.parse_args(argv)

    try:
        load_json(args.config)
    except (OSError, DuplicateKeyError, json.JSONDecodeError) as error:
        print(f"[config] ERROR: invalid JSON: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
