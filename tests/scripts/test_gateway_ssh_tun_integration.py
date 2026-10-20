"""Exercise same-key SSH TUN sessions in explicitly isolated Podman resources."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

IMAGE = "localhost/gateway:1"
INTEGRATION_ENABLED = os.environ.get("RUN_GATEWAY_SSH_TUN_INTEGRATION") == "1"


def _run(
    arguments: Sequence[str],
    *,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run one test-owned host command without a shell."""
    result = subprocess.run(
        list(arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed ({result.returncode}): {arguments[0]} {arguments[1:]}\n"
            f"{result.stderr[-2000:]}"
        )
    return result


def _free_subnet(
    candidates: Sequence[str], occupied: Sequence[ipaddress.IPv4Network]
) -> str:
    """Select one synthetic test subnet without overlapping existing host routes."""
    for candidate in candidates:
        network = ipaddress.ip_network(candidate, strict=True)
        if not any(network.overlaps(route) for route in occupied):
            return str(network)
    pytest.skip("No isolated test subnet is available without changing host routes.")


def _host_routes() -> list[ipaddress.IPv4Network]:
    """Read non-default host routes before creating the disposable Podman network."""
    result = _run(["ip", "-j", "-4", "route", "show", "table", "all"])
    routes = json.loads(result.stdout)
    occupied = []
    for route in routes:
        destination = route.get("dst")
        if not isinstance(destination, str) or destination == "default":
            continue
        parsed = ipaddress.ip_network(destination, strict=False)
        if parsed.version == 4:
            occupied.append(parsed)
    return occupied


def _wait_for(
    description: str,
    predicate: Callable[[], bool],
    *,
    timeout: float = 30,
) -> None:
    """Poll a test-owned readiness condition until it succeeds or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {description}.")


def _link_names(container: str) -> set[str]:
    """Return interface names from one test-owned container namespace."""
    result = _run(
        ["podman", "exec", container, "ip", "-j", "link", "show"],
        check=False,
    )
    if result.returncode != 0:
        return set()
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    return {
        entry["ifname"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("ifname"), str)
    }


def _pam_uid_log(container: str, log_name: str) -> list[int]:
    """Read numeric UID records from one test-only PAM log."""
    result = _run(
        ["podman", "exec", container, "cat", f"/run/gateway/ssh_tun/{log_name}"]
    )
    return [int(line) for line in result.stdout.splitlines() if line.isdecimal()]


def _send_test_packet(
    client: str,
    *,
    source_address: str,
    receiver_address: str,
    payload: str,
) -> str:
    """Send a TCP packet through the TUN and return the receiver's observed source."""
    program = (
        "import socket,sys; "
        "s=socket.socket(); s.settimeout(8); "
        "s.bind((sys.argv[1],0)); "
        "s.connect((sys.argv[2],9000)); "
        "s.sendall(sys.argv[3].encode()); "
        "print(s.recv(256).decode())"
    )
    result = _run(
        [
            "podman",
            "exec",
            client,
            "python3",
            "-c",
            program,
            source_address,
            receiver_address,
            payload,
        ],
        timeout=15,
    )
    return result.stdout.strip()


def _disconnect_session(
    client: str,
    index: int,
    process: subprocess.Popen[bytes],
) -> None:
    """Stop only the SSH process whose PID the test wrapper recorded."""
    pid_path = f"/tmp/ssh-session-{index}.pid"
    result = _run(
        ["podman", "exec", client, "cat", pid_path],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip().isdecimal():
        raise AssertionError(f"SSH session {index} has no valid recorded PID.")
    pid = int(result.stdout.strip())
    if pid <= 1:
        raise AssertionError(f"SSH session {index} recorded an unsafe PID.")
    _run(["podman", "exec", client, "kill", "-TERM", str(pid)])
    process.wait(timeout=10)


@pytest.mark.integration
@pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="set RUN_GATEWAY_SSH_TUN_INTEGRATION=1 for isolated rootful Podman test",
)
def test_two_same_key_sessions_preserve_sources_and_teardown_independently(
    tmp_path: Path,
) -> None:
    """Verify real OpenSSH, PAM, TUN packets, source preservation, and cleanup."""
    if shutil.which("podman") is None:
        pytest.skip("Podman is unavailable.")
    info = _run(
        [
            "podman",
            "info",
            "--format",
            "rootless={{.Host.Security.Rootless}}",
        ]
    )
    if info.stdout.strip() != "rootless=false":
        pytest.skip("The isolated SSH TUN test requires rootful Podman.")
    if _run(["podman", "image", "exists", IMAGE], check=False).returncode != 0:
        pytest.skip(f"Build {IMAGE} before running the isolated SSH TUN test.")

    host_routes = _host_routes()
    subnet = _free_subnet(
        (
            "10.253.240.0/24",
            "10.254.240.0/24",
            "10.252.240.0/24",
            "192.0.2.0/24",
            "203.0.113.0/24",
        ),
        host_routes,
    )
    ssh_pool = _free_subnet(
        (
            "198.18.240.0/24",
            "198.19.240.0/24",
            "198.18.241.0/24",
        ),
        host_routes,
    )
    network = ipaddress.ip_network(subnet)
    gateway_address = str(network.network_address + 2)
    receiver_address = str(network.network_address + 3)
    suffix = uuid.uuid4().hex[:10]
    network_name = f"ssh-test-{suffix}"
    gateway_name = f"ssh-gateway-{suffix}"
    receiver_name = f"ssh-receiver-{suffix}"
    client_names = [f"ssh-client-a-{suffix}", f"ssh-client-b-{suffix}"]
    key_base = tmp_path / "tunnel-key"
    developer_key = tmp_path / "developer-key"
    host_key = tmp_path / "host-key"
    tunnel_keys = tmp_path / "tunnel_authorized_keys"
    developer_keys = tmp_path / "developer_authorized_keys"
    config_directory = tmp_path / "config"
    tls_directory = tmp_path / "tls"
    secrets_directory = tmp_path / "secrets"
    dns_directory = tmp_path / "dns"
    test_directory = tmp_path / "test"
    for directory in (
        config_directory,
        tls_directory,
        secrets_directory,
        dns_directory,
        test_directory,
    ):
        directory.mkdir(mode=0o700)

    _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_base)])
    _run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(developer_key),
        ]
    )
    _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)])
    tunnel_keys.write_text(key_base.with_suffix(".pub").read_text(), encoding="ascii")
    developer_keys.write_text(
        developer_key.with_suffix(".pub").read_text(), encoding="ascii"
    )
    tunnel_keys.chmod(0o644)
    developer_keys.chmod(0o644)
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ed25519",
            "-keyout",
            str(tls_directory / "gateway.key"),
            "-out",
            str(tls_directory / "gateway.cert"),
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ]
    )
    (tls_directory / "gateway.key").chmod(0o600)
    (tls_directory / "gateway.cert").chmod(0o644)
    password = secrets_directory / "cockpit-password"
    password.write_text("test-only-password\n", encoding="ascii")
    password.chmod(0o600)
    (dns_directory / "hosts").write_text(
        "# empty synthetic DNS data\n", encoding="ascii"
    )
    (dns_directory / "hosts").chmod(0o644)
    (test_directory / "tunnel-key").write_bytes(key_base.read_bytes())
    (test_directory / "tunnel-key").chmod(0o600)
    (test_directory / "developer-key").write_bytes(developer_key.read_bytes())
    (test_directory / "developer-key").chmod(0o600)
    (test_directory / "resolv.conf").write_text(
        "nameserver 127.0.0.1\noptions attempts:1 timeout:1\n",
        encoding="ascii",
    )
    (test_directory / "resolv.conf").chmod(0o644)

    config: dict[str, Any] = json.loads(
        (Path(__file__).resolve().parents[2] / "config/host_config.json").read_text(
            encoding="utf-8"
        )
    )
    config["gateway"]["remote_access"]["ssh_tun"] = {
        "enabled": True,
        "account": "gateway-tunnel",
        "address_pool": ssh_pool,
        "authorized_keys_path": "/run/test/tunnel_authorized_keys",
        "max_sessions": 2,
    }
    config["networks"] = [
        {
            "name": network_name,
            "subnet": subnet,
            "gateway_address": gateway_address,
        }
    ]
    config["containers"] = []
    config["dns_records"] = []
    config_path = config_directory / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    config_path.chmod(0o644)

    names = [gateway_name, receiver_name, *client_names]
    network_created = False
    processes: list[tuple[int, subprocess.Popen[bytes]]] = []
    try:
        _run(["podman", "network", "create", "--subnet", subnet, network_name])
        network_created = True
        _run(
            [
                "podman",
                "run",
                "--detach",
                "--name",
                gateway_name,
                "--network",
                network_name,
                "--ip",
                gateway_address,
                "--cap-drop=NET_RAW",
                "--cap-add=NET_ADMIN",
                "--device",
                "/dev/net/tun",
                "--volume",
                f"{config_directory}:/etc/gateway/generated:ro",
                "--volume",
                f"{developer_keys}:/run/gateway/authorized_keys:ro",
                "--volume",
                f"{tunnel_keys}:/run/gateway/ssh_tun/authorized_keys:ro",
                "--volume",
                f"{password}:/run/secrets/cockpit-password:ro",
                "--volume",
                f"{host_key}:/run/ssh-host-keys/ssh_host_ed25519_key:ro",
                "--volume",
                f"{host_key}.pub:/run/ssh-host-keys/ssh_host_ed25519_key.pub:ro",
                "--volume",
                f"{tls_directory / 'gateway.cert'}:/etc/cockpit/ws-certs.d/gateway.cert:ro",
                "--volume",
                f"{tls_directory / 'gateway.key'}:/etc/cockpit/ws-certs.d/gateway.key:ro",
                "--volume",
                f"{dns_directory}:/run/gateway/dns:ro",
                IMAGE,
            ]
        )
        receiver_program = (
            "import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, "
            " socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0',9000)); s.listen()\n"
            "while True:\n"
            " c,a=s.accept(); d=c.recv(1024); c.sendall(a[0].encode()+b':'+d); "
            "c.close()"
        )
        _run(
            [
                "podman",
                "run",
                "--detach",
                "--rm",
                "--name",
                receiver_name,
                "--network",
                network_name,
                "--ip",
                receiver_address,
                "--cap-add=NET_ADMIN",
                "--entrypoint",
                "python3",
                IMAGE,
                "-u",
                "-c",
                receiver_program,
            ]
        )
        for client_name in client_names:
            _run(
                [
                    "podman",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    client_name,
                    "--network",
                    network_name,
                    "--cap-add=NET_ADMIN",
                    "--device",
                    "/dev/net/tun",
                    "--volume",
                    f"{test_directory}:/run/test:ro",
                    "--entrypoint",
                    "/bin/sleep",
                    IMAGE,
                    "3600",
                ]
            )
        _wait_for(
            "Gateway SSH listener",
            lambda: bool(
                _run(
                    [
                        "podman",
                        "exec",
                        gateway_name,
                        "ss",
                        "-H",
                        "-ltn",
                        "sport",
                        "=",
                        ":22",
                    ],
                    check=False,
                ).stdout.strip()
            ),
        )
        assert _run(
            [
                "podman",
                "exec",
                gateway_name,
                "grep",
                "-F",
                "session required pam_exec.so /usr/local/lib/gateway/ssh_tun_runtime.py pam",
                "/etc/pam.d/sshd",
            ]
        ).stdout.strip()
        for uid_option, log_name in (
            ("-ru", "pam-real-uid.log"),
            ("-u", "pam-effective-uid.log"),
        ):
            _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "sed",
                    "-i",
                    (
                        "/^session required pam_exec.so /i session optional pam_exec.so type=open_session log=/run/gateway/ssh_tun/"
                        f"{log_name} /usr/bin/id {uid_option}"
                    ),
                    "/etc/pam.d/sshd",
                ]
            )
        _run(
            [
                "podman",
                "exec",
                gateway_name,
                "sed",
                "-i",
                "s#^session required pam_exec.so #session required pam_exec.so log=/run/gateway/ssh_tun/pam.log #",
                "/etc/pam.d/sshd",
            ]
        )
        _run(
            [
                "podman",
                "exec",
                client_names[0],
                "ssh",
                "-i",
                "/run/test/developer-key",
                "-p",
                "22",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "LogLevel=ERROR",
                f"developer@{gateway_address}",
                "true",
            ]
        )
        for log_name in ("pam-real-uid.log", "pam-effective-uid.log"):
            assert _pam_uid_log(gateway_name, log_name) == [0]
        _run(
            [
                "podman",
                "exec",
                receiver_name,
                "ip",
                "route",
                "add",
                ssh_pool,
                "via",
                gateway_address,
            ]
        )
        _run(
            [
                "podman",
                "exec",
                gateway_name,
                "ip",
                "link",
                "add",
                "dummy9",
                "type",
                "dummy",
            ]
        )
        previous_forwarding = _run(
            ["podman", "exec", gateway_name, "cat", "/proc/sys/net/ipv4/ip_forward"]
        ).stdout.strip()

        def start_session(index: int) -> subprocess.Popen[bytes]:
            """Start one real SSH client process with the shared key."""
            client_name = client_names[index]
            runner_program = (
                "import os,subprocess,sys; "
                "process=subprocess.Popen(sys.argv[2:]); "
                "open(sys.argv[1],'w').write(str(process.pid)); "
                "status=process.wait(); os.unlink(sys.argv[1]); "
                "raise SystemExit(status)"
            )
            command = [
                "podman",
                "exec",
                client_name,
                "python3",
                "-c",
                runner_program,
                f"/tmp/ssh-session-{index}.pid",
                "ssh",
                "-w",
                f"{index}:any",
                "-p",
                "22",
                "-i",
                "/run/test/tunnel-key",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "LogLevel=ERROR",
                f"gateway-tunnel@{gateway_address}",
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append((index, process))
            return process

        first = start_session(0)
        _wait_for(
            "first authenticated TUN",
            lambda: (
                first.poll() is None
                and "tun0" in _link_names(gateway_name)
                and "tun0" in _link_names(client_names[0])
            ),
        )
        for log_name in ("pam-real-uid.log", "pam-effective-uid.log"):
            assert _pam_uid_log(gateway_name, log_name) == [0, 0]
        second = start_session(1)
        _wait_for(
            "second authenticated TUN",
            lambda: (
                second.poll() is None
                and {"tun0", "tun1"}.issubset(_link_names(gateway_name))
                and "tun1" in _link_names(client_names[1])
            ),
        )
        for log_name in ("pam-real-uid.log", "pam-effective-uid.log"):
            assert _pam_uid_log(gateway_name, log_name) == [0, 0, 0]

        for index, payload in ((0, "first"), (1, "second")):
            pool = ipaddress.ip_network(ssh_pool)
            local_server = pool.network_address + index * 2
            peer_client = local_server + 1
            client_address = str(peer_client)
            server_address = str(local_server)
            client_name = client_names[index]
            interface = f"tun{index}"
            _run(
                [
                    "podman",
                    "exec",
                    client_name,
                    "ip",
                    "address",
                    "add",
                    "local",
                    client_address,
                    "peer",
                    server_address,
                    "dev",
                    interface,
                ]
            )
            _run(
                [
                    "podman",
                    "exec",
                    client_name,
                    "ip",
                    "link",
                    "set",
                    "dev",
                    interface,
                    "up",
                ]
            )
            _run(
                [
                    "podman",
                    "exec",
                    client_name,
                    "ip",
                    "route",
                    "add",
                    f"{receiver_address}/32",
                    "dev",
                    interface,
                ]
            )
            observed = _send_test_packet(
                client_name,
                source_address=client_address,
                receiver_address=receiver_address,
                payload=payload,
            )
            assert observed == f"{client_address}:{payload}"

        _disconnect_session(client_names[0], 0, first)
        _wait_for(
            "first-session cleanup without disturbing the second",
            lambda: (
                "tun0" not in _link_names(gateway_name)
                and "tun1" in _link_names(gateway_name)
            ),
            timeout=20,
        )
        assert "dummy9" in _link_names(gateway_name)
        assert _send_test_packet(
            client_names[1],
            source_address=str(ipaddress.ip_network(ssh_pool).network_address + 3),
            receiver_address=receiver_address,
            payload="after-first-disconnect",
        ) == (
            f"{ipaddress.ip_network(ssh_pool).network_address + 3}:"
            "after-first-disconnect"
        )

        _disconnect_session(client_names[1], 1, second)
        _wait_for(
            "last-session cleanup",
            lambda: "tun1" not in _link_names(gateway_name),
            timeout=20,
        )
        assert "dummy9" in _link_names(gateway_name)
        assert (
            _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "cat",
                    "/proc/sys/net/ipv4/ip_forward",
                ]
            ).stdout.strip()
            == previous_forwarding
        )
        assert (
            _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "test",
                    "!",
                    "-e",
                    "/run/gateway/remote_access/state.json",
                ],
                check=False,
            ).returncode
            == 0
        )
        state = json.loads(
            _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "cat",
                    "/run/gateway/ssh_tun/state/state.json",
                ]
            ).stdout
        )
        assert state["reservations"] == []
    except Exception as error:
        logs = _run(["podman", "logs", gateway_name], check=False)
        if logs.returncode == 0:
            reservations = _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "cat",
                    "/run/gateway/ssh_tun/state/state.json",
                ],
                check=False,
            )
            pam_log = _run(
                [
                    "podman",
                    "exec",
                    gateway_name,
                    "cat",
                    "/run/gateway/ssh_tun/pam.log",
                ],
                check=False,
            )
            raise AssertionError(
                f"{error}\n"
                f"Gateway interfaces: {sorted(_link_names(gateway_name))}\n"
                f"SSH TUN state: {reservations.stdout}\n"
                f"PAM helper output: {pam_log.stdout}\n"
                f"Gateway startup/runtime logs:\n{logs.stdout}\n{logs.stderr}"
            ) from error
        raise
    finally:
        for name in names:
            if (
                _run(["podman", "container", "exists", name], check=False).returncode
                == 0
            ):
                _run(["podman", "rm", "--force", name], check=False)
        for _index, process in processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        if network_created:
            _run(["podman", "network", "rm", network_name], check=False)
    assert str(network) not in {str(route) for route in _host_routes()}, (
        "Disposable Podman network route remained after cleanup."
    )
