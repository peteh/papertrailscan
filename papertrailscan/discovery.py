"""Epson ENPC network scanner discovery."""

import argparse
import socket
import struct
import time

ENPC_PORT = 3289
ENPC_PREFIX = b"EPSON"
QUERY = b"Q"
RESPONSE = b"q"
QUERY_FUNCTIONS = (bytes.fromhex("00000000"), bytes.fromhex("00000010"))
SCANNER_MODELS = (
    "DS-40",
    "DS-560",
    "DS-570W",
    "DS-575W",
    "DS-1660W",
    "DS-360W",
    "ES-300W",
    "ES-300WR",
    "ES-500W",
    "ES-500WR",
    "ES-60W",
    "ES-60WA",
    "ES-65WR",
    "DS-80W",
    "DS-80WA",
    "FF-680W",
    "RR-60",
    "RR-70W",
)


class EpsonScannerDiscovery:
    """Discover Epson scanners on the local network using ENPC."""

    def __init__(self, broadcast: str = "255.255.255.255", timeout: float = 3.0):
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.broadcast = broadcast
        self.timeout = timeout

    @staticmethod
    def _make_query(function: bytes) -> bytes:
        if len(function) != 4:
            raise ValueError("ENPC function must be exactly four bytes")
        return ENPC_PREFIX + QUERY + function + struct.pack(">I", 0)

    @staticmethod
    def _parse_response(packet: bytes) -> tuple[bytes, bytes] | None:
        if len(packet) < 14 or packet[:6] != ENPC_PREFIX + RESPONSE:
            return None

        function = packet[6:10]
        body_length = int.from_bytes(packet[11:14], "big")
        body = packet[14:]
        if body_length != len(body):
            return None
        return function, body

    @staticmethod
    def _scanner_name(body: bytes) -> str | None:
        for model in SCANNER_MODELS:
            encoded_model = model.encode("ascii")
            offset = body.find(encoded_model)
            if offset >= 0 and (
                offset + len(encoded_model) == len(body)
                or body[offset + len(encoded_model)] == 0
            ):
                return model

        identifier = body.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
        return identifier or None

    def discover(self) -> list[tuple[str, str]]:
        """Return discovered (IP address, model or device ID) pairs."""
        found: dict[str, str] = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 0))
            for function in QUERY_FUNCTIONS:
                sock.sendto(self._make_query(function), (self.broadcast, ENPC_PORT))

            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    packet, (address, _port) = sock.recvfrom(2048)
                except TimeoutError:
                    break
                parsed = self._parse_response(packet)
                if parsed and parsed[0] == bytes.fromhex("00000000"):
                    name = self._scanner_name(parsed[1])
                    if name:
                        found[address] = name

        return sorted(found.items())


def main() -> None:
    parser = argparse.ArgumentParser(description="List Epson scanners discovered via ENPC.")
    parser.add_argument("--broadcast", default="255.255.255.255", help="IPv4 broadcast address for the LAN")
    parser.add_argument("--timeout", type=float, default=3.0, help="seconds to wait for replies")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    scanners = EpsonScannerDiscovery(args.broadcast, args.timeout).discover()
    if not scanners:
        print("No supported scanners found.")
        return

    print(f"{'IP address':<16} Model / device ID")
    for address, name in scanners:
        print(f"{address:<16} {name}")


if __name__ == "__main__":
    main()
