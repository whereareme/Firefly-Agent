"""Run the local Firefly relationship gateway."""

from __future__ import annotations

import argparse
import ctypes
import os
import threading

from .config import ConfigError, load_config
from .gateway import RelationshipGatewayServer


def process_is_alive(pid: int) -> bool:
    """Inspect a process without signaling or mutating it."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def parent_watchdog(server: RelationshipGatewayServer, parent_pid: int, stop: threading.Event) -> None:
    """Stop a managed headless Sidecar after its Firefly parent disappears."""
    while not stop.wait(1.0):
        if not process_is_alive(parent_pid):
            server.shutdown()
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Firefly relationship gateway.")
    parser.add_argument("--config", required=True, help="Path to the secret-free gateway JSON config.")
    parser.add_argument("--headless", action="store_true", help="Run the gateway without the local panel.")
    parser.add_argument("--parent-pid", type=int, help="Exit after this managing Firefly process exits.")
    arguments = parser.parse_args(argv)
    if arguments.parent_pid is not None and (
        arguments.parent_pid <= 0 or arguments.parent_pid == os.getpid()
    ):
        parser.error("--parent-pid must identify a different live process")
    try:
        config = load_config(arguments.config)
    except ConfigError as error:
        parser.error(str(error))

    try:
        server = RelationshipGatewayServer(config)
    except OSError as error:
        parser.error(f"could not listen on {config.host}:{config.port}: {error}")
    server.proposals_enabled = not arguments.headless
    print(f"Firefly relationship gateway listening on http://{config.host}:{server.server_port}/v1")
    server_thread: threading.Thread | None = None
    watchdog_stop = threading.Event()
    watchdog_thread: threading.Thread | None = None
    if arguments.parent_pid is not None:
        watchdog_thread = threading.Thread(
            target=parent_watchdog,
            args=(server, arguments.parent_pid, watchdog_stop),
            name="relationship-parent-watchdog",
            daemon=True,
        )
        watchdog_thread.start()
    try:
        if arguments.headless:
            server.serve_forever()
        else:
            from .panel import run_panel

            server_thread = threading.Thread(target=server.serve_forever, name="relationship-gateway", daemon=True)
            server_thread.start()
            run_panel(server)
    except KeyboardInterrupt:
        return 0
    finally:
        watchdog_stop.set()
        if server_thread is not None:
            server.shutdown()
            server_thread.join()
        server.server_close()
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
