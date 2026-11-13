"""Wait for the Epson ESC/I-2 network button-start event."""

import argparse
import ipaddress
import socket
import struct
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

SCANNER_PORT = 1865
FRAME_HEADER_SIZE = 12
MAX_FRAME_BODY = 1024 * 1024
WAIT_START_PAYLOAD = bytes.fromhex("01 a0 04 00 00 01 2c")


@dataclass(frozen=True)
class ScannerButtonEvent:
    scanner_ip: str
    received_at: float


class EpsonButtonWaiter:
    """Use Epson's native job-start handshake and wait for a button event."""

    def __init__(
        self,
        scanner_ip: str,
        *,
        port: int = SCANNER_PORT,
        connect_timeout: float = 3.0,
        verbose: bool = False,
    ):
        self.scanner_ip = str(ipaddress.IPv4Address(scanner_ip))
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be greater than zero")
        self.port = port
        self.connect_timeout = connect_timeout
        self.verbose = verbose

    @staticmethod
    def _read_exact(connection: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise ConnectionError("scanner closed the ESC/I-2 connection")
            data.extend(chunk)
        return bytes(data)

    @classmethod
    def _read_frame(cls, connection: socket.socket) -> tuple[bytes, bytes]:
        header = cls._read_exact(connection, FRAME_HEADER_SIZE)
        if header[:2] != b"IS":
            raise ValueError(f"invalid Epson frame signature: {header[:2]!r}")
        if header[5] != FRAME_HEADER_SIZE:
            raise ValueError(f"unsupported Epson frame header size: {header[5]}")
        body_length = int.from_bytes(header[6:10], "big")
        if body_length > MAX_FRAME_BODY:
            raise ValueError(f"Epson frame body is too large: {body_length}")
        return header[2:5], cls._read_exact(connection, body_length)

    @staticmethod
    def _build_wait_start_frame() -> bytes:
        header = b"IS" + bytes.fromhex("21 00 00 0c")
        return header + struct.pack(">I", len(WAIT_START_PAYLOAD)) + b"\x00\x00" + WAIT_START_PAYLOAD

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr)

    def probe(self) -> bool:
        """Check whether the scanner accepts its ESC/I-2 connection greeting."""
        try:
            with socket.create_connection((self.scanner_ip, self.port), self.connect_timeout) as connection:
                connection.settimeout(self.connect_timeout)
                greeting_type, greeting = self._read_frame(connection)
                return greeting_type == bytes.fromhex("800010") and greeting == bytes.fromhex("0104000000")
        except (OSError, ValueError):
            return False

    def wait_for_button(self, timeout: float | None = None) -> ScannerButtonEvent | None:
        """Wait for one scanner button event, or return None on timeout."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")

        with socket.create_connection((self.scanner_ip, self.port), self.connect_timeout) as connection:
            connection.settimeout(self.connect_timeout)
            greeting_type, greeting = self._read_frame(connection)
            if greeting_type != bytes.fromhex("800010"):
                raise RuntimeError(f"unexpected connection greeting {greeting_type.hex()}: {greeting.hex()}")
            self._log(f"Scanner greeting: {greeting_type.hex(' ')} {greeting.hex(' ')}")

            connection.sendall(self._build_wait_start_frame())
            reply_type, reply = self._read_frame(connection)
            if reply_type[:2] != bytes.fromhex("a100") or not reply or reply[0] != 6:
                raise RuntimeError(f"scanner rejected wait-start request: {reply_type.hex()} {reply.hex()}")
            self._log(f"Wait-start accepted: {reply_type.hex(' ')} {reply.hex(' ')}")

            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                if deadline is None:
                    connection.settimeout(None)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    connection.settimeout(remaining)
                try:
                    message_type, body = self._read_frame(connection)
                except TimeoutError:
                    return None

                self._log(f"Scanner message: {message_type.hex(' ')} {body.hex(' ')}")
                if body and body[0] == 1:
                    return ScannerButtonEvent(self.scanner_ip, time.time())
                if not body or body[0] != 6:
                    raise RuntimeError(f"unexpected scanner wait response: {message_type.hex()} {body.hex()}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for a physical Epson scanner button press.")
    parser.add_argument("--scanner-ip", required=True, help="IPv4 address of the scanner")
    parser.add_argument("--port", type=int, default=SCANNER_PORT)
    parser.add_argument("--timeout", type=float, help="seconds to wait for each button press")
    parser.add_argument("--once", action="store_true", help="exit after the first button press")
    parser.add_argument("--verbose", action="store_true", help="log Epson protocol frames")
    args = parser.parse_args(argv)

    try:
        waiter = EpsonButtonWaiter(args.scanner_ip, port=args.port, verbose=args.verbose)
        while True:
            print(f"Waiting for scanner button at {waiter.scanner_ip}:{waiter.port}...", flush=True)
            event = waiter.wait_for_button(args.timeout)
            if event is None:
                print("No button press received before timeout.", file=sys.stderr)
                return 1
            print(f"Scanner button pressed at {event.received_at:.3f}.", flush=True)
            if args.once:
                return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
