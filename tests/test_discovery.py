import unittest
from unittest.mock import patch

from papertrailscan.discovery import EpsonScannerDiscovery


class FakeSocket:
    def __init__(self, packets):
        self.packets = iter(packets)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def setsockopt(self, *args):
        pass

    def bind(self, *args):
        pass

    def sendto(self, packet, address):
        self.sent.append((packet, address))

    def settimeout(self, timeout):
        pass

    def recvfrom(self, _size):
        try:
            return next(self.packets), ("192.168.2.56", 3289)
        except StopIteration as error:
            raise TimeoutError from error


class EpsonScannerDiscoveryTests(unittest.TestCase):
    def test_discovers_scanner_from_valid_reply(self):
        body = b"device\x00DS-560\x00"
        packet = b"EPSONq" + bytes.fromhex("00000000") + b"\x00" + len(body).to_bytes(3, "big") + body
        fake_socket = FakeSocket([packet])

        with patch("papertrailscan.discovery.socket.socket", return_value=fake_socket):
            with patch("papertrailscan.discovery.time.monotonic", side_effect=[0.0, 0.0, 2.0]):
                scanners = EpsonScannerDiscovery(timeout=1.0).discover()

        self.assertEqual(scanners, [("192.168.2.56", "DS-560")])
        self.assertEqual(len(fake_socket.sent), 2)

    def test_ignores_truncated_reply(self):
        body = b"device-id"
        packet = b"EPSONq" + bytes.fromhex("00000000") + b"\x00" + len(body).to_bytes(3, "big") + body[:-1]
        fake_socket = FakeSocket([packet])

        with patch("papertrailscan.discovery.socket.socket", return_value=fake_socket):
            with patch("papertrailscan.discovery.time.monotonic", side_effect=[0.0, 0.0, 2.0]):
                scanners = EpsonScannerDiscovery(timeout=1.0).discover()

        self.assertEqual(scanners, [])


if __name__ == "__main__":
    unittest.main()
