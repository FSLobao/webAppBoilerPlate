"""Test shared, session-owned nftables and IPv4 forwarding state."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from gateway.development import remote_forwarding as forwarding


class FakeFirewall:
    """Model one nftables table with a stable inspected kernel handle."""

    def __init__(self) -> None:
        self.comment: str | None = None
        self.handle = 41
        self.commands: list[list[str]] = []
        self.lock = threading.Lock()
        self.fail_delete = False

    def run(
        self, arguments: list[str], *, input: str | None = None, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Return synthetic nft JSON and apply only explicit test commands."""
        with self.lock:
            self.commands.append(arguments)
            if arguments == ["nft", "-j", "list", "tables"]:
                tables = (
                    [
                        {
                            "table": {
                                "family": "inet",
                                "name": forwarding.NFT_TABLE,
                            }
                        }
                    ]
                    if self.comment is not None
                    else []
                )
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps({"nftables": tables}), ""
                )
            if arguments == [
                "nft",
                "-j",
                "-a",
                "list",
                "table",
                "inet",
                forwarding.NFT_TABLE,
            ]:
                if self.comment is None:
                    return subprocess.CompletedProcess(arguments, 1, "", "missing")
                table = {
                    "family": "inet",
                    "name": forwarding.NFT_TABLE,
                    "comment": self.comment,
                    "handle": self.handle,
                }
                output = {"nftables": [{"table": table}]}
                return subprocess.CompletedProcess(arguments, 0, json.dumps(output), "")
            if arguments == ["nft", "-f", "-"]:
                if self.comment is not None:
                    return subprocess.CompletedProcess(arguments, 1, "", "exists")
                assert input is not None
                self.comment = input.split('comment "')[1].split('"')[0]
                return subprocess.CompletedProcess(arguments, 0, "", "")
            if arguments == [
                "nft",
                "delete",
                "table",
                "inet",
                "handle",
                str(self.handle),
            ]:
                if self.fail_delete:
                    return subprocess.CompletedProcess(
                        arguments, 1, "", "table handle changed"
                    )
                self.comment = None
                return subprocess.CompletedProcess(arguments, 0, "", "")
            raise AssertionError(f"unexpected command: {arguments}")


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create one isolated forwarding sysctl and manager state directory."""
    forwarding_path = tmp_path / "ip_forward"
    forwarding_path.write_text("0", encoding="ascii")
    return forwarding_path, tmp_path / "state", tmp_path


def test_rules_allow_tun_to_podman_without_nat_or_podman_peering() -> None:
    """Allow routed TUN traffic, replies, and no other inter-network traffic."""
    rules = forwarding._rules(("eth1", "eth0"), f"gateway-runtime:{'a' * 64}")

    assert 'iifname "tun*" oifname { "eth0", "eth1" } accept' in rules
    assert 'iifname { "eth0", "eth1" } oifname { "eth0", "eth1" } drop' in rules
    assert "ct state established,related accept" in rules
    assert "snat" not in rules.lower()
    assert "masquerade" not in rules.lower()


def test_last_owner_restores_only_the_original_forwarding_value(
    tmp_path: Path,
) -> None:
    """Create one owned table and remove it after its only owner leaves."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "a" * 64

    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0", "eth1"),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    forwarding.release_forwarding(
        owner,
        previous,
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )

    assert previous == "0"
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert firewall.comment is None
    assert not (state_directory / "state.json").exists()
    assert [
        call for call in firewall.commands if call[:3] == ["nft", "delete", "table"]
    ] == [["nft", "delete", "table", "inet", "handle", "41"]]


def test_releasing_one_of_two_tunnels_preserves_shared_forwarding(
    tmp_path: Path,
) -> None:
    """Keep the shared table active until every session releases its lease."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    first, second = "b" * 64, "c" * 64
    first_previous = forwarding.acquire_forwarding(
        first,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    second_previous = forwarding.acquire_forwarding(
        second,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )

    forwarding.release_forwarding(
        first,
        first_previous,
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    assert firewall.comment == f"gateway-runtime:{first}"
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert json.loads((state_directory / "state.json").read_text())["owners"] == [
        second
    ]

    forwarding.release_forwarding(
        second,
        second_previous,
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    assert firewall.comment is None
    assert forwarding_path.read_text(encoding="ascii") == "0"


def test_preexisting_foreign_table_fails_without_sysctl_mutation(
    tmp_path: Path,
) -> None:
    """Leave an existing table and forwarding value untouched."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    firewall.comment = "foreign"

    with pytest.raises(forwarding.ForwardingError, match="without an ownership record"):
        forwarding.acquire_forwarding(
            "d" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert firewall.comment == "foreign"
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert not (state_directory / "state.json").exists()


def test_changed_table_owner_is_never_deleted(tmp_path: Path) -> None:
    """Refuse cleanup after nft ownership metadata changes."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "e" * 64
    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    firewall.comment = "foreign replacement"

    with pytest.raises(forwarding.ForwardingError, match="ownership changed"):
        forwarding.release_forwarding(
            owner,
            previous,
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert firewall.comment == "foreign replacement"
    assert forwarding_path.read_text(encoding="ascii") == "1"


def test_concurrent_owners_share_one_policy_and_do_not_overwrite_each_other(
    tmp_path: Path,
) -> None:
    """Serialize concurrent leases and retain both independent owners."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owners = ("f" * 64, "1" * 64)
    errors: list[Exception] = []

    def acquire(owner: str) -> None:
        try:
            forwarding.acquire_forwarding(
                owner,
                ("eth0",),
                runner=firewall.run,
                forwarding_path=forwarding_path,
                state_directory=state_directory,
            )
        except Exception as error:  # noqa: BLE001 -- report thread assertion failures.
            errors.append(error)

    threads = [threading.Thread(target=acquire, args=(owner,)) for owner in owners]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert set(state["owners"]) == set(owners)
    assert firewall.comment is not None
