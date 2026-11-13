"""Coordinate Epson button events with one-page scan jobs."""

import time
from collections.abc import Callable
from pathlib import Path

from .button_waiter import EpsonButtonWaiter
from .scanning import EpsonScanJob


class ButtonTriggeredScanApplication:
    """Probe a scanner, scan once per button press, and group pages by idle time."""

    def __init__(
        self,
        scanner_ip: str,
        *,
        device_name: str | None = None,
        output_dir: str | Path = "scans",
        dpi: int = 300,
        image_format: str = "pdf",
        mode: str = "Color",
        paper_size: str = "A4",
        source: str = "ADF Front",
        idle_timeout: float = 10.0,
        reconnect_interval: float = 3.0,
        scan_timeout: float = 120.0,
        verbose: bool = False,
        waiter: EpsonButtonWaiter | None = None,
        scan_job_factory: Callable[..., EpsonScanJob] = EpsonScanJob,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        output: Callable[[str], None] = print,
    ):
        if idle_timeout <= 0:
            raise ValueError("idle_timeout must be greater than zero")
        if reconnect_interval <= 0:
            raise ValueError("reconnect_interval must be greater than zero")
        self.scanner_ip = scanner_ip
        self.device_name = device_name or f"epsonds:net:{scanner_ip}"
        self.output_dir = Path(output_dir)
        self.settings = {
            "dpi": dpi,
            "image_format": image_format,
            "mode": mode,
            "paper_size": paper_size,
            "source": source,
            "scan_timeout": scan_timeout,
        }
        self.idle_timeout = idle_timeout
        self.reconnect_interval = reconnect_interval
        self.verbose = verbose
        self.waiter = waiter or EpsonButtonWaiter(scanner_ip, verbose=verbose)
        self.scan_job_factory = scan_job_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.output = output
        self._job: EpsonScanJob | None = None
        self._page_count = 0
        self._last_page_at: float | None = None

    def _log(self, message: str) -> None:
        if self.verbose:
            self.output(message)

    def _start_document(self) -> None:
        job = self.scan_job_factory(self.device_name, **self.settings)
        job.start_scan()
        self._job = job
        self._page_count = 0
        self._log("Started a new scan document.")

    def _finish_document(self) -> None:
        job = self._job
        if job is None:
            return
        try:
            if self._page_count == 0:
                self.output("No pages scanned; discarding empty document.")
                return
            job.finish_scan()
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            suffix = "pdf" if self.settings["image_format"] == "pdf" else "jpg"
            destination = self.output_dir / f"scan-{timestamp}.{suffix}"
            for document in job.download_document(destination):
                self.output(f"Saved {document}")
        except RuntimeError as error:
            self.output(f"Could not finish document: {error}")
        finally:
            job.close()
            self._job = None
            self._page_count = 0
            self._last_page_at = None

    def _idle_remaining(self) -> float | None:
        if self._last_page_at is None:
            return None
        return self.idle_timeout - (self.monotonic() - self._last_page_at)

    def run(self) -> None:
        """Run until interrupted, recovering after scanner disconnects."""
        was_online: bool | None = None
        try:
            while True:
                online = self.waiter.probe()
                if not online:
                    if was_online is not False:
                        self.output(f"Scanner {self.scanner_ip} is offline; retrying.")
                    was_online = False
                    remaining = self._idle_remaining()
                    if remaining is not None and remaining <= 0:
                        self._finish_document()
                        continue
                    wait = self.reconnect_interval if remaining is None else min(self.reconnect_interval, remaining)
                    self.sleep(wait)
                    continue

                if was_online is False:
                    self.output(f"Scanner {self.scanner_ip} is back online.")
                was_online = True

                remaining = self._idle_remaining()
                wait_timeout = None if remaining is None else max(0.0, remaining)
                try:
                    event = self.waiter.wait_for_button(timeout=wait_timeout)
                except (OSError, RuntimeError, ValueError) as error:
                    self.output(f"Scanner connection lost or wait failed: {error}")
                    was_online = False
                    self.sleep(self.reconnect_interval)
                    continue

                if event is None:
                    self._finish_document()
                    continue

                self._log(f"Button event received from {event.scanner_ip}.")
                if self._job is None:
                    self._start_document()
                job = self._job
                if job is None:
                    raise RuntimeError("could not start a scan document")
                try:
                    page = job.add_scan()
                except RuntimeError as error:
                    self.output(f"Page scan failed: {error}")
                    self._finish_document()
                    was_online = None
                    continue

                if page is None:
                    self._finish_document()
                    continue
                self._page_count += 1
                self._last_page_at = self.monotonic()
                self._log(f"Added page {self._page_count}; waiting for the next press.")
        finally:
            self._finish_document()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Scan one page per Epson button press; finish after idle timeout.")
    parser.add_argument("--scanner-ip", required=True, help="IPv4 address of the scanner")
    parser.add_argument("--device", help="SANE device name; defaults to epsonds:net:<scanner-ip>")
    parser.add_argument("--output-dir", type=Path, default=Path("scans"))
    parser.add_argument("--dpi", type=int, choices=(200, 300, 400, 600), default=300)
    parser.add_argument("--format", choices=("pdf", "jpeg"), default="pdf", dest="image_format")
    parser.add_argument("--mode", choices=("Lineart", "Gray", "Color"), default="Color")
    parser.add_argument("--paper-size", choices=("A4",), default="A4")
    parser.add_argument("--source", default="ADF Front")
    parser.add_argument("--idle-timeout", type=float, default=10.0)
    parser.add_argument("--reconnect-interval", type=float, default=3.0)
    parser.add_argument("--scan-timeout", type=float, default=120.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        app = ButtonTriggeredScanApplication(
            args.scanner_ip,
            device_name=args.device,
            output_dir=args.output_dir,
            dpi=args.dpi,
            image_format=args.image_format,
            mode=args.mode,
            paper_size=args.paper_size,
            source=args.source,
            idle_timeout=args.idle_timeout,
            reconnect_interval=args.reconnect_interval,
            scan_timeout=args.scan_timeout,
            verbose=args.verbose,
        )
        app.run()
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
