"""Experimental SLP/HTTP listener for Epson NetScanMonitor push-scan events.

This is not Epson's native ESC/I-2 wait-start client. The ES-60W was observed
querying this listener over SLP but did not send a TCP button event.
"""

import argparse
import ipaddress
import queue
import socket
import struct
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass

SLP_MULTICAST_GROUP = "239.255.255.253"
SLP_PORT = 2968
EVENT_PORT = 1865
MAX_HTTP_REQUEST = 65536


@dataclass(frozen=True)
class ScannerButtonEvent:
    """A scanner-originated push-scan event."""

    scanner_ip: str
    push_scan_id: str
    received_at: float


def build_slp_attribute_reply(
    transaction_id: bytes,
    client_name: str,
    host_ip: str,
    event_port: int = EVENT_PORT,
) -> bytes:
    """Build the Epson SLP attribute reply advertising this event listener."""
    if len(transaction_id) != 2:
        raise ValueError("SLP transaction ID must be two bytes")
    if not 1 <= event_port <= 65535:
        raise ValueError("event_port must be between 1 and 65535")
    ipaddress.IPv4Address(host_ip)
    if not client_name or any(char in client_name for char in "(),"):
        raise ValueError("client_name must be non-empty and cannot contain (),")

    attributes = f"(ClientName={client_name}),(IPAddress={host_ip}),(EventPort={event_port})".encode("ascii")
    payload = b"\x00\x00" + struct.pack(">H", len(attributes)) + attributes + b"\x00"
    length = 16 + len(payload)
    return (
        b"\x02\x07"
        + length.to_bytes(4, "big")[1:]
        + b"\x00" * 5
        + transaction_id
        + b"\x00\x02en"
        + payload
    )


def parse_push_scan_id(soap_body: bytes) -> str | None:
    """Extract PushScanIDIn from a SOAP event body."""
    try:
        root = ET.fromstring(soap_body)
    except ET.ParseError:
        return None

    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "PushScanIDIn" and element.text:
            push_scan_id = element.text.strip()
            if push_scan_id and len(push_scan_id) <= 64:
                return push_scan_id
    return None


def build_soap_response() -> bytes:
    """Build the success response Epson expects for a push-scan event."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        "<s:Body>"
        '<p:PushScanResponse xmlns:p="http://schema.epson.net/EpsonNet/Scan/2004/pushscan">'
        "<p:Response>0</p:Response>"
        "</p:PushScanResponse>"
        "</s:Body>"
        "</s:Envelope>"
    ).encode("utf-8")
    headers = (
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/soap+xml; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return headers + body


class EpsonButtonListener:
    """Advertise a host to an Epson scanner and queue its button events."""

    def __init__(
        self,
        scanner_ip: str,
        *,
        client_name: str = "PAPERTRAILSCAN",
        host_ip: str | None = None,
        slp_port: int = SLP_PORT,
        event_port: int = EVENT_PORT,
        multicast_group: str = SLP_MULTICAST_GROUP,
        verbose: bool = False,
    ):
        self.scanner_ip = str(ipaddress.IPv4Address(scanner_ip))
        self.client_name = client_name
        self.host_ip = host_ip
        self.slp_port = slp_port
        self.event_port = event_port
        self.multicast_group = multicast_group
        self.verbose = verbose
        self._events: queue.Queue[ScannerButtonEvent] = queue.Queue()
        self._running = False
        self._slp_socket: socket.socket | None = None
        self._event_socket: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    def _select_host_ip(self) -> str:
        if self.host_ip is not None:
            return str(ipaddress.IPv4Address(self.host_ip))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((self.scanner_ip, self.event_port))
            return probe.getsockname()[0]

    def start(self) -> None:
        """Start the SLP advertisement listener and TCP event listener."""
        if self._running:
            raise RuntimeError("button listener is already running")
        self.host_ip = self._select_host_ip()

        event_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        slp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            event_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            event_socket.bind((self.host_ip, self.event_port))
            event_socket.listen(5)
            event_socket.settimeout(0.5)

            slp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            slp_socket.bind(("", self.slp_port))
            membership = socket.inet_aton(self.multicast_group) + socket.inet_aton(self.host_ip)
            slp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            slp_socket.settimeout(0.5)
        except OSError:
            event_socket.close()
            slp_socket.close()
            raise

        self._event_socket = event_socket
        self._slp_socket = slp_socket
        self._running = True
        self._threads = [
            threading.Thread(target=self._serve_slp, name="epson-slp-listener", daemon=True),
            threading.Thread(target=self._serve_events, name="epson-event-listener", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._log(f"Listening for SLP on {self.multicast_group}:{self.slp_port}; TCP events on {self.host_ip}:{self.event_port}.")

    def wait_for_button(self, timeout: float | None = None) -> ScannerButtonEvent | None:
        """Wait for the next button event, returning None when timeout expires."""
        if not self._running:
            self.start()
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def _serve_slp(self) -> None:
        assert self._slp_socket is not None
        while self._running:
            try:
                packet, (source_ip, _source_port) = self._slp_socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            if source_ip != self.scanner_ip:
                self._log(f"Ignoring SLP packet from unexpected host {source_ip}.")
                continue
            function = packet[1] if len(packet) > 1 else None
            self._log(
                f"Received {len(packet)} SLP bytes from {source_ip}; function={function!r}; "
                f"request={packet.hex(' ')}."
            )
            if len(packet) < 12 or packet[:2] != b"\x02\x06":
                self._log("Ignoring packet: expected an SLPv2 attribute request (function 6).")
                continue
            if int.from_bytes(b"\x00" + packet[2:5], "big") != len(packet):
                self._log("Ignoring SLP packet with inconsistent message length.")
                continue

            reply = build_slp_attribute_reply(
                packet[10:12],
                self.client_name,
                self.host_ip or "",
                self.event_port,
            )
            try:
                self._slp_socket.sendto(reply, (self.scanner_ip, self.slp_port))
                self._log(f"Advertised {self.client_name} at {self.host_ip}:{self.event_port} to scanner.")
            except OSError:
                if not self._running:
                    break
                self._log("Could not send SLP reply to scanner.")

    def _serve_events(self) -> None:
        assert self._event_socket is not None
        while self._running:
            try:
                connection, (source_ip, _source_port) = self._event_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            self._log(f"TCP connection from {source_ip}.")
            if source_ip != self.scanner_ip:
                connection.close()
                self._log("Rejected TCP connection from unexpected host.")
                continue
            with connection:
                connection.settimeout(5.0)
                try:
                    body = self._read_http_body(connection)
                except (OSError, TimeoutError):
                    self._log("TCP event request ended before its body was received.")
                    continue
                if body is None:
                    self._log("TCP event did not contain a valid Content-Length body.")
                    continue
                push_scan_id = parse_push_scan_id(body)
                try:
                    connection.sendall(build_soap_response())
                except OSError:
                    self._log("Could not send SOAP acknowledgement.")
                    continue
                if push_scan_id is not None:
                    self._events.put(ScannerButtonEvent(source_ip, push_scan_id, time.time()))
                    self._log(f"Received Epson button event: PushScanID={push_scan_id}.")
                else:
                    self._log("SOAP body did not contain a PushScanIDIn value.")

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr)

    @staticmethod
    def _read_http_body(connection: socket.socket) -> bytes | None:
        request = bytearray()
        while b"\r\n\r\n" not in request and len(request) <= MAX_HTTP_REQUEST:
            chunk = connection.recv(4096)
            if not chunk:
                return None
            request.extend(chunk)

        if len(request) > MAX_HTTP_REQUEST:
            return None
        headers, _, body = request.partition(b"\r\n\r\n")
        content_length = None
        for line in headers.decode("latin-1").split("\r\n")[1:]:
            name, separator, value = line.partition(":")
            if separator and name.strip().lower() == "content-length":
                try:
                    content_length = int(value.strip())
                except ValueError:
                    return None
                break

        if content_length is None or content_length < 0 or content_length > MAX_HTTP_REQUEST:
            return None
        while len(body) < content_length:
            chunk = connection.recv(min(4096, content_length - len(body)))
            if not chunk:
                return None
            body += chunk
        return body[:content_length]

    def close(self) -> None:
        """Stop listeners and release their sockets."""
        self._running = False
        for listener_socket in (self._slp_socket, self._event_socket):
            if listener_socket is not None:
                listener_socket.close()
        self._slp_socket = None
        self._event_socket = None

    def __enter__(self) -> "EpsonButtonListener":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental Epson NetScanMonitor push-scan event listener.")
    parser.add_argument("--scanner-ip", required=True, help="IPv4 address of the scanner")
    parser.add_argument("--host-ip", help="local IPv4 address to advertise and bind")
    parser.add_argument("--client-name", default="PAPERTRAILSCAN")
    parser.add_argument("--verbose", action="store_true", help="log SLP and TCP event traffic")
    args = parser.parse_args(argv)

    try:
        with EpsonButtonListener(
            args.scanner_ip,
            host_ip=args.host_ip,
            client_name=args.client_name,
            verbose=args.verbose,
        ) as listener:
            print(f"Listening for button events from {args.scanner_ip} on {listener.host_ip}. Press the scanner button.")
            while True:
                event = listener.wait_for_button()
                if event is not None:
                    print(f"Button event: PushScanID={event.push_scan_id}")
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        parser.exit(1, f"error: cannot start button listener: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
