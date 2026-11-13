"""Command-line interface for scanning documents."""

import argparse
from pathlib import Path
from collections.abc import Sequence

from .scanning import EpsonScanJob

DEFAULT_DEVICE = "epsonds:net:192.168.2.56"
DEFAULT_OUTPUT = Path("scans/document.pdf")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a document with an Epson network scanner.")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="SANE device name from scanimage -L")
    parser.add_argument("--pages", type=int, default=3, help="maximum number of pages to scan")
    parser.add_argument("--dpi", type=int, choices=(200, 300, 400, 600), default=300)
    parser.add_argument("--format", choices=("pdf", "jpeg"), default="pdf", dest="image_format")
    parser.add_argument("--mode", choices=("Lineart", "Gray", "Color"), default="Color")
    parser.add_argument("--paper-size", choices=("A4",), default="A4")
    parser.add_argument("--source", default="ADF Front")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.pages < 1:
        parser.error("--pages must be at least one")

    try:
        with EpsonScanJob(
            args.device,
            dpi=args.dpi,
            image_format=args.image_format,
            mode=args.mode,
            paper_size=args.paper_size,
            source=args.source,
        ) as job:
            job.start_scan()
            pages_scanned = 0
            for _ in range(args.pages):
                if job.add_scan() is None:
                    break
                pages_scanned += 1

            if pages_scanned == 0:
                print("No pages were scanned; no document to save.")
                return 1

            job.finish_scan()
            for document in job.download_document(args.output):
                print(f"Saved {document}")
    except RuntimeError as error:
        parser.exit(1, f"error: {error}\n")

    return 0
