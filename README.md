# papertrailscan

Small Python tools for discovering and scanning Epson network scanners. Scanning uses the system SANE `epsonds` backend; this project does not reimplement Epson's scan transport.

## Requirements

- Python 3.10 or later
- SANE with the Epson `epsonds` backend and the `scanimage` command
- `pdfunite` for combining multi-page PDF scans

Confirm SANE can see the scanner with `scanimage -L` before running the application.

## Install

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Use

Scan up to three A4 color pages into `scans/document.pdf`:

```sh
papertrailscan
```

The settings can be changed on the command line:

```sh
papertrailscan --device 'epsonds:net:192.168.2.56' --pages 3 --dpi 300 --format pdf --mode Color --paper-size A4 --output scans/document.pdf
```

Discover Epson scanners on the local network:

```sh
papertrailscan-discover
```

Wait for the ES-60W's physical button using the native ESC/I-2 job-start exchange:

```sh
papertrailscan-button --scanner-ip 192.168.2.56 --once --verbose
```

Run the automatic button-to-document workflow:

```sh
papertrailscan-button-scan --scanner-ip 192.168.2.56 --idle-timeout 10 --output-dir scans --verbose
```

Each button press scans one page. Another press within 10 seconds adds a page to the same document; after 10 idle seconds, the document is saved and the app waits for the next press. The app probes the scanner and retries after disconnects. Settings such as `--dpi`, `--format`, `--mode`, `--paper-size`, and `--source` can be passed as well.

The waiter opens a TCP connection to scanner port `1865`, sends the native wait-start request, and returns when the scanner reports a button press. Use `--timeout 30` to limit each wait or omit `--once` to wait again after each press.

Or run the modules directly from the repository:

```sh
python -m papertrailscan
python -m papertrailscan.discovery --broadcast 192.168.2.255
```

The reusable APIs are `papertrailscan.EpsonScanJob`, `papertrailscan.discovery.EpsonScannerDiscovery`, and `papertrailscan.button_waiter.EpsonButtonWaiter`.

## Docker

A containerized version of the button-triggered scanner workflow is included. The scanner IP is required; all other settings are optional overrides.

```sh
SCANNER_IP=192.168.2.56 docker compose up --build
```

Optional overrides for the other settings:

```sh
SCANNER_IP=192.168.2.56 \
OUTPUT_DIR=/data/scans \
DPI=300 \
FORMAT=pdf \
MODE=Color \
PAPER_SIZE=A4 \
SOURCE='ADF Front' \
IDLE_TIMEOUT=10 \
RECONNECT_INTERVAL=3 \
SCAN_TIMEOUT=120 \
VERBOSE=true \
docker compose up --build
```

The Compose setup runs the same native CLI command as the host install, so the command-line arguments still work when running natively and the container only supplies environment values for the same options.

## Tests

Run the unit tests with:

```sh
python -m unittest discover -s tests -v
```
