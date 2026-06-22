from __future__ import annotations

import argparse
import select
import socket
import socketserver
import sys
import threading
import time

import paramiko


class _ForwardHandler(socketserver.BaseRequestHandler):
    chain_host = "127.0.0.1"
    chain_port = 0
    transport = None

    def handle(self) -> None:
        assert self.transport is not None
        try:
            channel = self.transport.open_channel(
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception as exc:  # pragma: no cover
            print(
                f"forward open failed {self.chain_host}:{self.chain_port}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return

        if channel is None:
            print(
                f"forward rejected {self.chain_host}:{self.chain_port}",
                file=sys.stderr,
                flush=True,
            )
            return

        sockets = [self.request, channel]
        try:
            while True:
                ready, _, _ = select.select(sockets, [], [])
                if self.request in ready:
                    data = self.request.recv(32768)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in ready:
                    data = channel.recv(32768)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()
            self.request.close()


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_mapping(value: str) -> tuple[int, str, int]:
    try:
        local_port, remote_host, remote_port = value.split(":", 2)
        return int(local_port), remote_host, int(remote_port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid mapping '{value}', expected local_port:remote_host:remote_port"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Open local TCP forwards over SSH.")
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--ssh-user", required=True)
    parser.add_argument("--ssh-password", required=True)
    parser.add_argument(
        "--mapping",
        action="append",
        required=True,
        help="Forward mapping in local_port:remote_host:remote_port form.",
    )
    args = parser.parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=args.ssh_host,
        port=args.ssh_port,
        username=args.ssh_user,
        password=args.ssh_password,
        timeout=20,
    )
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        raise RuntimeError("ssh transport is not active")
    transport.set_keepalive(30)

    servers: list[_ThreadingTCPServer] = []
    threads: list[threading.Thread] = []
    try:
        for mapping in args.mapping:
            local_port, remote_host, remote_port = parse_mapping(mapping)
            handler = type(
                f"ForwardHandler_{local_port}",
                (_ForwardHandler,),
                {
                    "chain_host": remote_host,
                    "chain_port": remote_port,
                    "transport": transport,
                },
            )
            server = _ThreadingTCPServer(("127.0.0.1", local_port), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            servers.append(server)
            threads.append(thread)
            print(
                f"forwarding 127.0.0.1:{local_port} -> {remote_host}:{remote_port}",
                flush=True,
            )

        print("tunnels ready", flush=True)
        while transport.is_active():
            time.sleep(1)
        print("ssh transport is no longer active; stopping tunnels", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == "__main__":
    main()
