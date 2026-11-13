import unittest
from pathlib import Path
from unittest.mock import patch

from papertrailscan.button_scan import ButtonTriggeredScanApplication
from papertrailscan.button_waiter import ScannerButtonEvent


class FakeWaiter:
    def __init__(self, probes, waits):
        self.probes = iter(probes)
        self.waits = iter(waits)
        self.wait_timeouts = []

    def probe(self):
        return next(self.probes)

    def wait_for_button(self, timeout=None):
        self.wait_timeouts.append(timeout)
        result = next(self.waits)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeScanJob:
    def __init__(self, device_name, **settings):
        self.device_name = device_name
        self.settings = settings
        self.pages = 0
        self.finished = False
        self.closed = False

    def start_scan(self):
        pass

    def add_scan(self):
        self.pages += 1
        return Path(f"page-{self.pages}.pdf")

    def finish_scan(self):
        self.finished = True

    def download_document(self, destination):
        return [destination]

    def close(self):
        self.closed = True


class ButtonTriggeredScanTests(unittest.TestCase):
    def make_app(self, waiter, jobs, clock, messages):
        def make_job(device_name, **settings):
            job = FakeScanJob(device_name, **settings)
            jobs.append(job)
            return job

        return ButtonTriggeredScanApplication(
            "192.168.2.56",
            output_dir="test-scans",
            idle_timeout=10,
            reconnect_interval=3,
            waiter=waiter,
            scan_job_factory=make_job,
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            monotonic=lambda: clock[0],
            output=messages.append,
        )

    def test_multiple_presses_finish_one_document_after_idle(self):
        event1 = ScannerButtonEvent("192.168.2.56", 1)
        event2 = ScannerButtonEvent("192.168.2.56", 2)
        waiter = FakeWaiter([True, True, True, True], [event1, event2, None, KeyboardInterrupt()])
        jobs = []
        clock = [0.0]
        messages = []
        app = self.make_app(waiter, jobs, clock, messages)

        with patch("papertrailscan.button_scan.time.strftime", return_value="2026-11-13_12-00-00"):
            with self.assertRaises(KeyboardInterrupt):
                app.run()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].pages, 2)
        self.assertTrue(jobs[0].finished)
        self.assertTrue(jobs[0].closed)
        self.assertTrue(any("test-scans/scan-2026-11-13_12-00-00.pdf" in message for message in messages))

    def test_recovers_after_disconnect_and_keeps_document_open(self):
        event1 = ScannerButtonEvent("192.168.2.56", 1)
        event2 = ScannerButtonEvent("192.168.2.56", 2)
        waiter = FakeWaiter(
            [True, False, True, True, True],
            [event1, event2, None, KeyboardInterrupt()],
        )
        jobs = []
        clock = [0.0]
        messages = []
        app = self.make_app(waiter, jobs, clock, messages)

        with patch("papertrailscan.button_scan.time.strftime", return_value="2026-11-13_12-00-01"):
            with self.assertRaises(KeyboardInterrupt):
                app.run()

        self.assertEqual(clock[0], 3)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].pages, 2)
        self.assertTrue(jobs[0].finished)
        self.assertTrue(any("is offline" in message for message in messages))
        self.assertTrue(any("back online" in message for message in messages))

    def test_logs_each_page_scan(self):
        event1 = ScannerButtonEvent("192.168.2.56", 1)
        event2 = ScannerButtonEvent("192.168.2.56", 2)
        waiter = FakeWaiter([True, True, True], [event1, event2, KeyboardInterrupt()])
        jobs = []
        clock = [0.0]
        messages = []
        app = self.make_app(waiter, jobs, clock, messages)

        with self.assertRaises(KeyboardInterrupt):
            app.run()

        self.assertTrue(any("Scanned page 1" in message for message in messages))
        self.assertTrue(any("Scanned page 2" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
