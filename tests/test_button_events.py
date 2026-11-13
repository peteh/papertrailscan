import unittest

from papertrailscan.button_events import (
    build_slp_attribute_reply,
    build_soap_response,
    parse_push_scan_id,
)


class EpsonButtonEventTests(unittest.TestCase):
    def test_builds_slp_attribute_reply(self):
        transaction_id = b"\x12\x34"
        reply = build_slp_attribute_reply(transaction_id, "PAPERTRAILSCAN", "192.168.2.240")

        self.assertEqual(reply[:2], b"\x02\x07")
        self.assertEqual(reply[10:12], transaction_id)
        self.assertEqual(int.from_bytes(b"\x00" + reply[2:5], "big"), len(reply))
        self.assertIn(b"(EventPort=1865)", reply)

    def test_parses_push_scan_id(self):
        body = b"<Envelope><Body><PushScanIDIn>02</PushScanIDIn></Body></Envelope>"
        self.assertEqual(parse_push_scan_id(body), "02")

    def test_ignores_invalid_event_body(self):
        self.assertIsNone(parse_push_scan_id(b"not xml"))

    def test_builds_soap_acknowledgement(self):
        response = build_soap_response()
        self.assertTrue(response.startswith(b"HTTP/1.0 200 OK\r\n"))
        self.assertIn(b"<p:Response>0</p:Response>", response)


if __name__ == "__main__":
    unittest.main()
