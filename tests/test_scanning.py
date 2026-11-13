import subprocess
import unittest
from unittest.mock import call, patch

from papertrailscan.scanning import EpsonScanJob


class EpsonScanJobTests(unittest.TestCase):
    def test_scan_command_uses_a4_geometry(self):
        with EpsonScanJob("test:device") as job:
            with patch("papertrailscan.scanning.shutil.which", return_value="/usr/bin/scanimage"):
                job.start_scan()
            with patch(
                "papertrailscan.scanning.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as scan:
                job.add_scan()

        command = scan.call_args.args[0]
        self.assertEqual(command[command.index("-x") + 1], "210")
        self.assertEqual(command[command.index("-y") + 1], "297")

    def test_empty_feeder_retries_for_ten_seconds(self):
        clock = [0.0]
        empty_feeder = subprocess.CalledProcessError(
            1,
            ["scanimage"],
            stderr="scanimage: sane_start: Document feeder out of documents",
        )

        def advance_clock(seconds):
            clock[0] += seconds

        with EpsonScanJob("test:device") as job:
            with patch("papertrailscan.scanning.shutil.which", return_value="/usr/bin/scanimage"):
                job.start_scan()
            with (
                patch("papertrailscan.scanning.subprocess.run", side_effect=empty_feeder) as scan,
                patch("papertrailscan.scanning.time.monotonic", side_effect=lambda: clock[0]),
                patch("papertrailscan.scanning.time.sleep", side_effect=advance_clock) as wait,
            ):
                self.assertIsNone(job.add_scan())

        self.assertEqual(clock[0], 10)
        self.assertEqual(scan.call_count, 4)
        self.assertEqual(wait.call_args_list, [call(3), call(3), call(3), call(1)])


if __name__ == "__main__":
    unittest.main()
