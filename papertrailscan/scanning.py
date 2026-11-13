"""SANE-backed scan jobs for Epson network scanners."""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class EpsonScanJob:
    MODES = {"Lineart", "Gray", "Color"}
    FORMATS = {"pdf", "jpeg"}
    A4_SIZE_MM = (210, 297)
    FEEDER_EMPTY_ERROR = "Document feeder out of documents"
    RETRY_DELAY_SECONDS = 3
    FEEDER_RETRY_WINDOW_SECONDS = 10

    def __init__(
        self,
        device_name: str,
        *,
        dpi: int = 300,
        image_format: str = "pdf",
        mode: str = "Color",
        paper_size: str = "A4",
        source: str = "ADF Front",
        scan_timeout: float = 120.0,
    ):
        self.device_name = device_name
        self.source = source
        self.scan_timeout = scan_timeout
        self.dpi = 300
        self.image_format = "pdf"
        self.mode = "Color"
        self.paper_size = "A4"
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._page_files: list[Path] = []
        self._finished = False
        self.set_document_settings(dpi=dpi, image_format=image_format, mode=mode, paper_size=paper_size)

    def set_document_settings(
        self,
        *,
        dpi: int | None = None,
        image_format: str | None = None,
        mode: str | None = None,
        paper_size: str | None = None,
        source: str | None = None,
    ) -> None:
        """Set scan resolution, output format, color mode, and input source."""
        if self._temporary_directory is not None:
            raise RuntimeError("document settings cannot be changed after scanning starts")
        if dpi is not None:
            if dpi not in {200, 300, 400, 600}:
                raise ValueError("dpi must be one of 200, 300, 400, or 600")
            self.dpi = dpi
        if image_format is not None:
            image_format = image_format.lower()
            if image_format not in self.FORMATS:
                raise ValueError("image_format must be 'pdf' or 'jpeg'")
            self.image_format = image_format
        if mode is not None:
            if mode not in self.MODES:
                raise ValueError("mode must be 'Lineart', 'Gray', or 'Color'")
            self.mode = mode
        if paper_size is not None:
            paper_size = paper_size.upper()
            if paper_size != "A4":
                raise ValueError("paper_size must be 'A4'")
            self.paper_size = paper_size
        if source is not None:
            self.source = source

    def start_scan(self) -> None:
        """Start a scan job and prepare temporary storage for its pages."""
        if self._temporary_directory is not None:
            raise RuntimeError("scan job has already started")
        if shutil.which("scanimage") is None:
            raise RuntimeError("scanimage is required; install a SANE package with the epsonds backend")
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="epson-scan-")
        self._finished = False

    def add_scan(self) -> Path | None:
        """Scan one page, or return None if the feeder stays empty for 10 seconds."""
        if self._temporary_directory is None:
            raise RuntimeError("call start_scan() before add_scan()")
        if self._finished:
            raise RuntimeError("cannot add pages after finish_scan()")

        extension = "pdf" if self.image_format == "pdf" else "jpg"
        page_file = Path(self._temporary_directory.name) / f"page-{len(self._page_files) + 1:04d}.{extension}"
        width_mm, height_mm = self.A4_SIZE_MM
        command = [
            "scanimage",
            "--device-name",
            self.device_name,
            "--source",
            self.source,
            "--resolution",
            str(self.dpi),
            "--mode",
            self.mode,
            "--format",
            self.image_format,
            "-x",
            str(width_mm),
            "-y",
            str(height_mm),
            "--output-file",
            str(page_file),
        ]
        retry_deadline = None
        while True:
            if retry_deadline is not None and time.monotonic() >= retry_deadline:
                print("Document feeder remained empty for 10 seconds; finishing with scanned pages.", file=sys.stderr)
                return None
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=self.scan_timeout)
                break
            except subprocess.CalledProcessError as error:
                detail = error.stderr.strip() or str(error)
                if self.FEEDER_EMPTY_ERROR in detail:
                    if retry_deadline is None:
                        retry_deadline = time.monotonic() + self.FEEDER_RETRY_WINDOW_SECONDS
                    remaining = retry_deadline - time.monotonic()
                    if remaining <= 0:
                        print("Document feeder remained empty for 10 seconds; finishing with scanned pages.", file=sys.stderr)
                        return None
                    wait = min(self.RETRY_DELAY_SECONDS, remaining)
                    print(f"Document feeder is empty; retrying in {wait:g} seconds.", file=sys.stderr)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"scanner failed: {detail}") from error
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"scan exceeded {self.scan_timeout:g} seconds") from error

        self._page_files.append(page_file)
        return page_file

    def finish_scan(self) -> None:
        """Finish the job and combine its pages when the output is PDF."""
        if self._temporary_directory is None:
            raise RuntimeError("call start_scan() before finish_scan()")
        if self._finished:
            raise RuntimeError("scan job is already finished")
        if not self._page_files:
            raise RuntimeError("cannot finish a scan job with no pages")

        if self.image_format == "pdf" and len(self._page_files) > 1:
            pdfunite = shutil.which("pdfunite")
            if pdfunite is None:
                raise RuntimeError("pdfunite is required to combine multiple scanned PDF pages")
            combined_pdf = Path(self._temporary_directory.name) / "document.pdf"
            try:
                subprocess.run(
                    [pdfunite, *(str(page) for page in self._page_files), str(combined_pdf)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self.scan_timeout,
                )
            except subprocess.CalledProcessError as error:
                detail = error.stderr.strip() or str(error)
                raise RuntimeError(f"could not combine scanned pages: {detail}") from error
            self._page_files = [combined_pdf]

        self._finished = True

    def download_document(self, destination: str | Path) -> list[Path]:
        """Save the finished document locally and return the resulting file paths."""
        if not self._finished:
            raise RuntimeError("call finish_scan() before download_document()")

        target = Path(destination)
        if self.image_format == "pdf":
            if target.suffix.lower() != ".pdf":
                target = target.with_suffix(".pdf")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._page_files[0], target)
            return [target]

        if len(self._page_files) == 1:
            if target.suffix.lower() not in {".jpg", ".jpeg"}:
                target = target.with_suffix(".jpg")
            targets = [target]
        elif target.suffix:
            targets = [target.with_name(f"{target.stem}-{index:04d}.jpg") for index in range(1, len(self._page_files) + 1)]
        else:
            target.mkdir(parents=True, exist_ok=True)
            targets = [target / f"page-{index:04d}.jpg" for index in range(1, len(self._page_files) + 1)]

        for page_file, output_file in zip(self._page_files, targets):
            output_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(page_file, output_file)
        return targets

    def close(self) -> None:
        """Remove temporary page files used by this job."""
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def __enter__(self) -> "EpsonScanJob":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
