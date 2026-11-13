import socket
import struct
import unittest
from unittest.mock import patch

from papertrailscan.button_waiter import EpsonButtonWaiter, WAIT_START_PAYLOAD


def frame(message_type, body):
    header = b"IS" + message_type + b"\x0c" + struct.pack(">I", len(body)) + b"\x00\x00"
    return header + body


class FakeConnection:
    def __init__(self, data):
        self.data = bytearray(data)
        self.sent = []
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if not self.data:
            raise socket.timeout
        result = bytes(self.data[:size])
        del self.data[:size]
        return result


class EpsonButtonWaiterTests(unittest.TestCase):
    def test_sends_native_request_and_returns_button_event(self):
        greeting = frame(bytes.fromhex("800010"), bytes.fromhex("0104000000"))
        start_ack = frame(bytes.fromhex("a10010"), b"\x06")
        button_event = frame(bytes.fromhex("900010"), b"\x01")
        connection = FakeConnection(greeting + start_ack + button_event)

        with patch("papertrailscan.button_waiter.socket.create_connection", return_value=connection):
            event = EpsonButtonWaiter("192.168.2.56").wait_for_button(timeout=1)

        expected_request = (
            b"IS"
            + bytes.fromhex("2100000c")
            + struct.pack(">I", len(WAIT_START_PAYLOAD))
            + b"\x00\x00"
            + WAIT_START_PAYLOAD
        )
        self.assertEqual(connection.sent, [expected_request])
        self.assertIsNotNone(event)
        self.assertEqual(event.scanner_ip, "192.168.2.56")

    def test_returns_none_when_no_button_arrives(self):
        greeting = frame(bytes.fromhex("800010"), bytes.fromhex("0104000000"))
        start_ack = frame(bytes.fromhex("a10010"), b"\x06")
        connection = FakeConnection(greeting + start_ack)

        with patch("papertrailscan.button_waiter.socket.create_connection", return_value=connection):
            event = EpsonButtonWaiter("192.168.2.56").wait_for_button(timeout=1)

        self.assertIsNone(event)

    def test_rejects_unexpected_wait_start_acknowledgement(self):
        greeting = frame(bytes.fromhex("800010"), bytes.fromhex("0104000000"))
        bad_ack = frame(bytes.fromhex("a10010"), b"\x02")
        connection = FakeConnection(greeting + bad_ack)

        with patch("papertrailscan.button_waiter.socket.create_connection", return_value=connection):
            with self.assertRaises(RuntimeError):
                EpsonButtonWaiter("192.168.2.56").wait_for_button(timeout=1)


if __name__ == "__main__":
    unittest.main()
