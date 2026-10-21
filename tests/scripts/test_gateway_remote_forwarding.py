"""Test shared, session-owned nftables and IPv4 forwarding state."""

from __future__ import annotations

import ast
import importlib
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


def test_module_compiles_and_imports() -> None:
    """Compile the source and confirm its importable module is available."""
    source_path = Path(forwarding.__file__)
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(source_path), feature_version=(3, 13))
    compile(source, str(source_path), "exec")

    assert (
        importlib.import_module("gateway.development.remote_forwarding") is forwarding
    )


def test_rules_allow_tun_to_podman_without_nat_or_podman_peering() -> None:
    """Allow routed TUN traffic, replies, and no other inter-network traffic."""
    rules = forwarding._rules(("eth1", "eth0"), f"gateway-runtime:{'a' * 64}")

    assert 'iifname "tun*" oifname { "eth0", "eth1" } accept' in rules
    assert 'iifname "wg0" oifname { "eth0", "eth1" } accept' in rules
    assert 'iifname { "eth0", "eth1" } oifname { "eth0", "eth1" } drop' in rules
    assert "ct state established,related accept" in rules
    assert "snat" not in rules.lower()
    assert "masquerade" not in rules.lower()


def test_last_owner_restores_only_the_original_forwarding_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create one owned table and remove it after its only owner leaves."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "a" * 64
    events: list[str] = []
    original_write_text = Path.write_text

    def record_write(path: Path, data: str, *args: object, **kwargs: object) -> int:
        result = original_write_text(path, data, *args, **kwargs)
        if path == forwarding_path and data == "0":
            events.append("forwarding-disabled")
        return result

    def record_commands(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:3] == ["nft", "delete", "table"]:
            events.append("table-deleted")
        return firewall.run(arguments, **kwargs)

    monkeypatch.setattr(Path, "write_text", record_write)

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
        runner=record_commands,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )

    assert previous == "0"
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert events == ["forwarding-disabled", "table-deleted"]
    assert firewall.comment is None
    assert not (state_directory / "state.json").exists()
    assert [
        call for call in firewall.commands if call[:3] == ["nft", "delete", "table"]
    ] == [["nft", "delete", "table", "inet", "handle", "41"]]


def test_last_owner_preserves_preexisting_forwarding_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete the policy without changing forwarding that was already enabled."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    forwarding_path.write_text("1", encoding="ascii")
    firewall = FakeFirewall()
    writes: list[str] = []
    original_write_text = Path.write_text

    def record_write(path: Path, data: str, *args: object, **kwargs: object) -> int:
        if path == forwarding_path:
            writes.append(data)
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", record_write)
    owner = "b" * 64
    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0",),
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

    assert previous == "1"
    assert writes == []
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert firewall.comment is None
    assert not (state_directory / "state.json").exists()


@pytest.mark.parametrize("failure", ["read", "write"])
def test_failed_release_sysctl_restore_retains_owner_and_blocks_new_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Keep the owned policy and critical state when sysctl restore fails."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "9" * 64
    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    original_read_text = Path.read_text
    original_write_text = Path.write_text

    def fail_read(path: Path, *args: object, **kwargs: object) -> str:
        if failure == "read" and path == forwarding_path:
            raise PermissionError("synthetic private error text")
        return original_read_text(path, *args, **kwargs)

    def fail_write(path: Path, data: str, *args: object, **kwargs: object) -> int:
        if failure == "write" and path == forwarding_path and data == "0":
            raise PermissionError("synthetic private error text")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read)
    monkeypatch.setattr(Path, "write_text", fail_write)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.release_forwarding(
            owner,
            previous,
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.critical is True
    assert error.value.owner_id == owner
    assert error.value.operation == "release"
    assert error.value.failed_steps == ("forwarding",)
    assert "synthetic private error text" not in str(error.value)
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]

    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "8" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_ineffective_release_sysctl_restore_retains_owner_and_blocks_new_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the owned policy when restore writes but readback stays enabled."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "5" * 64
    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    original_write_text = Path.write_text

    def ineffective_restore(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path == forwarding_path and data == "0":
            return len(data)
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", ineffective_restore)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.release_forwarding(
            owner,
            previous,
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.critical is True
    assert error.value.owner_id == owner
    assert error.value.operation == "release"
    assert error.value.failed_steps == ("forwarding",)
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]

    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "4" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_failed_table_delete_retains_owner_and_allows_release_retry(
    tmp_path: Path,
) -> None:
    """Keep the lease after table deletion fails so the owner can retry."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "6" * 64
    previous = forwarding.acquire_forwarding(
        owner,
        ("eth0",),
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )
    firewall.fail_delete = True

    with pytest.raises(forwarding.ForwardingError, match="Could not remove"):
        forwarding.release_forwarding(
            owner,
            previous,
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert firewall.comment == f"gateway-runtime:{owner}"
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["critical_owner"] is None
    assert state["critical_failed_steps"] == []

    firewall.fail_delete = False
    forwarding.release_forwarding(
        owner,
        previous,
        runner=firewall.run,
        forwarding_path=forwarding_path,
        state_directory=state_directory,
    )

    assert firewall.comment is None
    assert not (state_directory / "state.json").exists()


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


def test_failed_acquire_rollback_persists_critical_owner_and_blocks_new_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Track residual firewall state when sysctl activation and table cleanup fail."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    firewall.fail_delete = True
    owner = "d" * 64
    original_write_text = Path.write_text

    def fail_forwarding_enable(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            raise PermissionError("synthetic private error text")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_forwarding_enable)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.critical is True
    assert error.value.owner_id == owner
    assert error.value.operation == "acquire_rollback"
    assert error.value.failed_steps == ("table",)
    assert "synthetic private error text" not in str(error.value)
    assert firewall.comment == f"gateway-runtime:{owner}"
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["table_tag"] == f"gateway-runtime:{owner}"
    assert state["previous_forwarding"] == "0"
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["table"]
    assert forwarding_path.read_text(encoding="ascii") == "0"

    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "e" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )
    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.release_forwarding(
            owner,
            "0",
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_failed_sysctl_restore_retains_table_and_blocks_new_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep restrictive rules when restoring the original sysctl fails."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "9" * 64
    original_write_text = Path.write_text

    def fail_restore(path: Path, data: str, *args: object, **kwargs: object) -> int:
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            raise PermissionError("synthetic activation failure")
        if path == forwarding_path and data == "0":
            raise PermissionError("synthetic restore failure")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_restore)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.failed_steps == ("forwarding",)
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]
    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "8" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_ineffective_sysctl_restore_retains_table_and_blocks_new_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep restrictive rules when a successful write does not restore forwarding."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "5" * 64
    original_write_text = Path.write_text

    def ineffective_restore(
        path: Path, data: str, *args: object, **kwargs: object
    ) -> int:
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            raise PermissionError("synthetic activation failure")
        if path == forwarding_path and data == "0":
            return len(data)
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", ineffective_restore)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.failed_steps == ("forwarding",)
    assert forwarding_path.read_text(encoding="ascii") == "1"
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]
    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "4" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_unavailable_sysctl_preserves_owned_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain restrictive rules when sysctl state cannot be read."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "7" * 64
    original_read_text = Path.read_text
    original_write_text = Path.write_text
    activated = False

    def fail_rollback_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == forwarding_path and activated:
            raise PermissionError("synthetic sysctl unavailable")
        return original_read_text(path, *args, **kwargs)

    def fail_activation(path: Path, data: str, *args: object, **kwargs: object) -> int:
        nonlocal activated
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            activated = True
            raise PermissionError("synthetic activation failure")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_rollback_read)
    monkeypatch.setattr(Path, "write_text", fail_activation)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert error.value.failed_steps == ("forwarding",)
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]


def test_unicode_sysctl_read_failure_preserves_owned_table_and_blocks_new_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep restrictive rules when rollback cannot decode forwarding state."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "8" * 64
    original_read_text = Path.read_text
    original_write_text = Path.write_text
    activation_attempted = False
    read_calls = 0

    def fail_rollback_read(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal read_calls
        if path == forwarding_path:
            read_calls += 1
            if activation_attempted:
                raise UnicodeDecodeError("ascii", b"\xff", 0, 1, "ordinal not in range")
        return original_read_text(path, *args, **kwargs)

    def fail_activation(path: Path, data: str, *args: object, **kwargs: object) -> int:
        nonlocal activation_attempted
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            activation_attempted = True
            raise PermissionError("synthetic activation failure")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_rollback_read)
    monkeypatch.setattr(Path, "write_text", fail_activation)

    with pytest.raises(forwarding.ForwardingRollbackError) as error:
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert read_calls == 2
    assert error.value.failed_steps == ("forwarding",)
    assert original_read_text(forwarding_path, encoding="ascii") == "1"
    assert firewall.comment == f"gateway-runtime:{owner}"
    assert not any(call[:3] == ["nft", "delete", "table"] for call in firewall.commands)
    state = json.loads((state_directory / "state.json").read_text(encoding="utf-8"))
    assert state["owners"] == [owner]
    assert state["table_tag"] == f"gateway-runtime:{owner}"
    assert state["previous_forwarding"] == "0"
    assert state["critical_owner"] == owner
    assert state["critical_failed_steps"] == ["forwarding"]

    with pytest.raises(forwarding.ForwardingError, match="requires operator recovery"):
        forwarding.acquire_forwarding(
            "7" * 64,
            ("eth0",),
            runner=firewall.run,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )


def test_rollback_restores_sysctl_before_deleting_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore IPv4 forwarding before deleting the owned table."""
    forwarding_path, state_directory, _ = _paths(tmp_path)
    firewall = FakeFirewall()
    owner = "6" * 64
    events: list[str] = []
    original_write_text = Path.write_text

    def record_write(path: Path, data: str, *args: object, **kwargs: object) -> int:
        if path == forwarding_path and data == "0":
            events.append("forwarding-disabled")
        if path == forwarding_path and data == "1":
            original_write_text(path, data, *args, **kwargs)
            raise PermissionError("synthetic activation failure")
        return original_write_text(path, data, *args, **kwargs)

    def record_commands(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:3] == ["nft", "delete", "table"]:
            events.append("table-deleted")
        return firewall.run(arguments, **kwargs)

    monkeypatch.setattr(Path, "write_text", record_write)

    with pytest.raises(forwarding.ForwardingError, match="Could not activate"):
        forwarding.acquire_forwarding(
            owner,
            ("eth0",),
            runner=record_commands,
            forwarding_path=forwarding_path,
            state_directory=state_directory,
        )

    assert events == ["forwarding-disabled", "table-deleted"]
    assert forwarding_path.read_text(encoding="ascii") == "0"
    assert firewall.comment is None


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
