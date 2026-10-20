"""Share scoped IPv4 forwarding across OpenVPN and SSH TUN sessions.

The module leases one Gateway-namespace nftables policy and forwarding setting
to root-owned runtime owners. It changes no host route and performs no NAT.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import subprocess
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

NFT_TABLE = "gateway_remote_access"
FORWARDING_PATH = Path("/proc/sys/net/ipv4/ip_forward")
STATE_DIRECTORY = Path("/run/gateway/remote_access")


class ForwardingError(RuntimeError):
    """Report a safe shared-forwarding failure."""


def _run(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one local networking tool without a shell."""
    try:
        return runner(
            list(arguments),
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ForwardingError(
            f"required networking command is unavailable: {arguments[0]}"
        ) from error


def _rules(interfaces: Sequence[str], owner_tag: str) -> str:
    """Build the shared, no-NAT forwarding table."""
    if not interfaces or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name) for name in interfaces
    ):
        raise ForwardingError("Gateway forwarding interfaces are invalid.")
    if not re.fullmatch(r"gateway-runtime:[0-9a-f]{64}", owner_tag):
        raise ForwardingError("Gateway forwarding ownership metadata is invalid.")
    podman_set = ", ".join(f'"{name}"' for name in sorted(set(interfaces)))
    return (
        f"create table inet {NFT_TABLE} {{\n"
        f'  comment "{owner_tag}"\n'
        "  chain forward {\n"
        "    type filter hook forward priority -5; policy drop;\n"
        f"    iifname {{ {podman_set} }} oifname {{ {podman_set} }} drop\n"
        "    ct state established,related accept\n"
        f'    iifname "tun*" oifname {{ {podman_set} }} accept\n'
        "  }\n"
        "}\n"
    )


def _ensure_directory(directory: Path) -> None:
    """Create and verify a private directory owned by the current user."""
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
    except OSError as error:
        raise ForwardingError("Gateway forwarding state is unavailable.") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or directory.is_symlink()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ForwardingError("Gateway forwarding state directory is unsafe.")


@contextmanager
def _locked(directory: Path):
    """Lock the private state file and yield its mutable state."""
    _ensure_directory(directory)
    lock_path = directory / "state.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        lock_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) & 0o077
        ):
            raise ForwardingError("Gateway forwarding lock is unsafe.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state_path = directory / "state.json"
        try:
            state_info = state_path.lstat()
        except FileNotFoundError:
            state: dict[str, Any] = {
                "schema_version": 1,
                "owners": [],
                "table_tag": None,
                "previous_forwarding": None,
            }
        else:
            if (
                not stat.S_ISREG(state_info.st_mode)
                or state_path.is_symlink()
                or state_info.st_uid != os.geteuid()
                or stat.S_IMODE(state_info.st_mode) & 0o077
            ):
                raise ForwardingError("Gateway forwarding state file is unsafe.")
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ForwardingError("Gateway forwarding state is invalid.") from error
            if (
                not isinstance(state, dict)
                or state.get("schema_version") != 1
                or not isinstance(state.get("owners"), list)
                or not all(
                    isinstance(owner, str) and re.fullmatch(r"[0-9a-f]{64}", owner)
                    for owner in state["owners"]
                )
                or len(set(state["owners"])) != len(state["owners"])
                or (
                    state["owners"]
                    and (
                        not isinstance(state.get("table_tag"), str)
                        or not re.fullmatch(
                            r"gateway-runtime:[0-9a-f]{64}", state["table_tag"]
                        )
                        or state.get("previous_forwarding") not in {"0", "1"}
                    )
                )
            ):
                raise ForwardingError("Gateway forwarding state is invalid.")
        try:
            yield state
        finally:
            if state["owners"]:
                temporary = directory / f"state.{secrets.token_hex(16)}.tmp"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0)
                output = os.open(temporary, flags, 0o600)
                with os.fdopen(output, "w", encoding="utf-8") as stream:
                    json.dump(state, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, state_path)
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            else:
                state_path.unlink(missing_ok=True)
        os.close(descriptor)
    except OSError as error:
        raise ForwardingError("Could not update Gateway forwarding state.") from error


def _table_handle(
    owner_tag: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int | None:
    """Return the exact tagged table handle, or None if absent."""
    listing = _run(["nft", "-j", "list", "tables"], runner=runner)
    if listing.returncode != 0:
        raise ForwardingError("Could not inspect Gateway firewall state.")
    try:
        entries = json.loads(listing.stdout)["nftables"]
        tables = [
            item["table"]
            for item in entries
            if isinstance(item, dict)
            and isinstance(item.get("table"), dict)
            and item["table"].get("family") == "inet"
            and item["table"].get("name") == NFT_TABLE
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ForwardingError("Gateway firewall listing is invalid.") from error
    if len(tables) > 1:
        raise ForwardingError("Gateway firewall listing is ambiguous.")
    if not tables:
        return None
    details = _run(
        ["nft", "-j", "-a", "list", "table", "inet", NFT_TABLE],
        runner=runner,
    )
    if details.returncode != 0:
        raise ForwardingError("Could not inspect Gateway firewall ownership.")
    try:
        records = json.loads(details.stdout)["nftables"]
        table_records = [
            item["table"]
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("table"), dict)
            and item["table"].get("family") == "inet"
            and item["table"].get("name") == NFT_TABLE
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ForwardingError("Gateway firewall ownership data is invalid.") from error
    if len(table_records) != 1:
        raise ForwardingError("Gateway firewall ownership data is invalid.")
    table = table_records[0]
    handle = table.get("handle")
    if (
        table.get("comment") != owner_tag
        or isinstance(handle, bool)
        or not isinstance(handle, int)
        or handle < 1
    ):
        raise ForwardingError(
            "Gateway firewall ownership changed; leaving it untouched."
        )
    return handle


def acquire_forwarding(
    owner_id: str,
    interfaces: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    forwarding_path: Path = FORWARDING_PATH,
    state_directory: Path = STATE_DIRECTORY,
) -> str:
    """Lease the shared firewall and return its original forwarding value."""
    if not re.fullmatch(r"[0-9a-f]{64}", owner_id):
        raise ForwardingError("Gateway forwarding owner is invalid.")
    installed_tag: str | None = None
    installed_previous: str | None = None
    try:
        with _locked(state_directory) as state:
            if owner_id in state["owners"]:
                if _table_handle(state["table_tag"], runner=runner) is None:
                    raise ForwardingError("Gateway forwarding table is missing.")
                return str(state["previous_forwarding"])
            if state["owners"]:
                if _table_handle(state["table_tag"], runner=runner) is None:
                    raise ForwardingError("Gateway forwarding table is missing.")
                current = forwarding_path.read_text(encoding="ascii").strip()
                if current != "1":
                    raise ForwardingError("Gateway IPv4 forwarding state changed.")
                state["owners"].append(owner_id)
                return str(state["previous_forwarding"])

            try:
                previous = forwarding_path.read_text(encoding="ascii").strip()
            except OSError as error:
                raise ForwardingError(
                    "Could not inspect Gateway IPv4 forwarding."
                ) from error
            if previous not in {"0", "1"}:
                raise ForwardingError("Gateway IPv4 forwarding state is invalid.")
            table_listing = _run(["nft", "-j", "list", "tables"], runner=runner)
            if table_listing.returncode != 0:
                raise ForwardingError("Could not inspect Gateway firewall state.")
            try:
                existing = json.loads(table_listing.stdout)["nftables"]
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ForwardingError("Gateway firewall listing is invalid.") from error
            if any(
                isinstance(item, dict)
                and isinstance(item.get("table"), dict)
                and item["table"].get("family") == "inet"
                and item["table"].get("name") == NFT_TABLE
                for item in existing
            ):
                raise ForwardingError(
                    "Gateway forwarding table exists without an ownership record."
                )
            owner_tag = f"gateway-runtime:{owner_id}"
            installed = _run(
                ["nft", "-f", "-"],
                runner=runner,
                input_text=_rules(interfaces, owner_tag),
            )
            if installed.returncode != 0:
                raise ForwardingError("Could not install Gateway forwarding rules.")
            installed_tag = owner_tag
            installed_previous = previous
            if previous == "0":
                forwarding_path.write_text("1", encoding="ascii")
            state.update(
                owners=[owner_id],
                table_tag=owner_tag,
                previous_forwarding=previous,
            )
            return previous
    except Exception as error:
        if installed_tag is not None:
            try:
                handle = _table_handle(installed_tag, runner=runner)
                if handle is not None:
                    deleted = _run(
                        ["nft", "delete", "table", "inet", "handle", str(handle)],
                        runner=runner,
                    )
                    if deleted.returncode != 0:
                        raise ForwardingError(
                            "Could not roll back Gateway forwarding rules."
                        )
                if installed_previous == "0":
                    current = forwarding_path.read_text(encoding="ascii").strip()
                    if current == "1":
                        forwarding_path.write_text("0", encoding="ascii")
            # Keep tuple parentheses for the Gateway's Python 3.13 runtime.
            except (OSError, ForwardingError) as error:  # fmt: skip
                raise ForwardingError(
                    "Gateway forwarding activation failed and owned-state rollback failed."
                ) from error
        if isinstance(error, ForwardingError):
            raise
        if isinstance(error, OSError):
            raise ForwardingError("Could not activate Gateway forwarding.") from error
        raise


def release_forwarding(
    owner_id: str,
    previous_forwarding: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    forwarding_path: Path = FORWARDING_PATH,
    state_directory: Path = STATE_DIRECTORY,
) -> None:
    """Release one owner without removing forwarding used by other tunnels."""
    if not re.fullmatch(r"[0-9a-f]{64}", owner_id) or previous_forwarding not in {
        "0",
        "1",
    }:
        raise ForwardingError("Gateway forwarding ownership metadata is invalid.")
    with _locked(state_directory) as state:
        if owner_id not in state["owners"]:
            return
        if state["previous_forwarding"] != previous_forwarding:
            raise ForwardingError("Gateway forwarding ownership metadata changed.")
        if len(state["owners"]) > 1:
            state["owners"].remove(owner_id)
            return
        owner_tag = state["table_tag"]
        handle = _table_handle(owner_tag, runner=runner)
        if handle is not None:
            deleted = _run(
                ["nft", "delete", "table", "inet", "handle", str(handle)],
                runner=runner,
            )
            if deleted.returncode != 0:
                raise ForwardingError("Could not remove Gateway forwarding rules.")
        if previous_forwarding == "0":
            try:
                current = forwarding_path.read_text(encoding="ascii").strip()
                if current == "1":
                    forwarding_path.write_text("0", encoding="ascii")
                elif current != "0":
                    raise ForwardingError("Gateway IPv4 forwarding state is invalid.")
            except OSError as error:
                raise ForwardingError(
                    "Could not restore Gateway IPv4 forwarding state."
                ) from error
        state["owners"].clear()
        state["table_tag"] = None
        state["previous_forwarding"] = None
