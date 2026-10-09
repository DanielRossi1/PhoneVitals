#!/usr/bin/env python3
"""Backend entry point.

Starts the local server. The Electron window merely loads its page: all the
logic lives here.

The socket is bound before the server starts and its address is announced on
stdout as `PHONEVITALS_LISTENING <host>:<port>`, so the launcher can ask for
port 0 and never collide with another program, or with another instance.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOST = "127.0.0.1"


def main() -> int:
    from phonevitals import __version__

    parser = argparse.ArgumentParser(description="PhoneVitals backend")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--port", type=int, default=0,
                        help="port to listen on (default: any free port)")
    parser.add_argument("--demo", action="store_true",
                        help="load a sample snapshot, without a phone")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    token = os.environ.get("PHONEVITALS_TOKEN") or secrets.token_urlsafe(32)
    launched_by_ui = "PHONEVITALS_TOKEN" in os.environ

    import uvicorn
    from phonevitals.server import create_app

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, args.port))
    except OSError as exc:
        print(f"cannot listen on {HOST}:{args.port}: {exc.strerror}",
              file=sys.stderr)
        return 1
    sock.listen(64)
    port = sock.getsockname()[1]

    server: uvicorn.Server | None = None

    def stop() -> None:
        if server is not None:
            server.should_exit = True

    app = create_app(demo=args.demo, token=token, on_shutdown_request=stop)
    server = uvicorn.Server(uvicorn.Config(
        app, log_level="warning", ws="websockets-sansio", lifespan="on"))

    print(f"PHONEVITALS_LISTENING {HOST}:{port}", flush=True)
    if not launched_by_ui:
        print(f"Open http://{HOST}:{port}/?token={token}", flush=True)

    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
