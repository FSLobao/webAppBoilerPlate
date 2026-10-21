"""Check and load host WireGuard kernel support for Gateway deployment."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
from collections.abc import Callable, Sequence

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class WireGuardKernelError(RuntimeError):
    """Report a sanitized WireGuard kernel-module operation failure."""


def _run_modprobe(
    arguments: Sequence[str],
    *,
    modprobe_path: pathlib.Path,
    run_command: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    """Run modprobe without a shell and capture its diagnostic output."""
    try:
        return run_command(
            [str(modprobe_path), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise WireGuardKernelError(
            f"Cannot run host modprobe at {modprobe_path}."
        ) from error


def _require_modprobe_success(
    result: subprocess.CompletedProcess[str], operation: str
) -> None:
    """Raise a useful error when modprobe returns a failure status."""
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip()
    message = f"{operation} failed with status {result.returncode}"
    if detail:
        message = f"{message}: {detail}"
    raise WireGuardKernelError(message)


def check_wireguard_kernel_support(
    *,
    run_command: CommandRunner = subprocess.run,
    module_path: pathlib.Path = pathlib.Path("/sys/module/wireguard"),
    modprobe_path: pathlib.Path = pathlib.Path("/usr/sbin/modprobe"),
) -> bool:
    """Check module loadability without changing host state.

    Args:
        run_command: Subprocess-compatible command runner, injectable for tests.
        module_path: Sysfs directory that proves the module is loaded.
        modprobe_path: Host modprobe executable used by deployment and systemd.

    Returns:
        True when WireGuard is already loaded; False when it can be loaded.

    Raises:
        WireGuardKernelError: If modprobe cannot resolve WireGuard under host
            policy or the module is unavailable.
    """
    result = _run_modprobe(
        ["--use-blacklist", "--dry-run", "--verbose", "wireguard"],
        modprobe_path=modprobe_path,
        run_command=run_command,
    )
    _require_modprobe_success(result, "WireGuard module availability check")
    if module_path.is_dir():
        return True
    if not (result.stdout.strip() or result.stderr.strip()):
        raise WireGuardKernelError(
            "WireGuard is not loaded and modprobe found no load plan; "
            "check kernel support and host module policy."
        )
    return False


def load_wireguard_kernel_support(
    *,
    run_command: CommandRunner = subprocess.run,
    module_path: pathlib.Path = pathlib.Path("/sys/module/wireguard"),
    modprobe_path: pathlib.Path = pathlib.Path("/usr/sbin/modprobe"),
) -> bool:
    """Load WireGuard when needed and verify its sysfs presence.

    Args:
        run_command: Subprocess-compatible command runner, injectable for tests.
        module_path: Sysfs directory that proves the module is loaded.
        modprobe_path: Host modprobe executable used by deployment and systemd.

    Returns:
        True when this call loaded the module; False when it was already loaded.

    Raises:
        WireGuardKernelError: If modprobe fails or the module remains unloaded.
    """
    if module_path.is_dir():
        return False
    result = _run_modprobe(
        ["--use-blacklist", "wireguard"],
        modprobe_path=modprobe_path,
        run_command=run_command,
    )
    _require_modprobe_success(result, "Loading the WireGuard kernel module")
    if not module_path.is_dir():
        raise WireGuardKernelError(
            "modprobe succeeded but /sys/module/wireguard is absent; "
            "check kernel support and host module policy."
        )
    return True


def main(argv: list[str] | None = None) -> int:
    """Load WireGuard kernel support for an enabled Gateway deployment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        loaded = load_wireguard_kernel_support()
    except WireGuardKernelError as error:
        print(f"[wireguard-kernel] ERROR: {error}", file=sys.stderr)
        return 1
    message = "Loaded" if loaded else "WireGuard kernel support is already loaded."
    if loaded:
        message = "Loaded WireGuard kernel support."
    print(f"[wireguard-kernel] {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
