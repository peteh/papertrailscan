# papertrailscan

A small scan server for EPSON ES-60W that does the following:

1. Wait for scanner to connect to the network
2. When scan button is pressed, a page is scanned
3. When no pages are scanned within the next 10 seconds, a new document is created with all pages

The server can be used to output into the `consume` directory of paperless-ngx.

Tested hardware:

* Epson ES-60W

## Requirements

* Python 3.10 or later
* SANE with the Epson `epsonds` backend and the `scanimage` command
* `pdfunite` for combining multi-page PDF scans

Confirm SANE can see the scanner with `scanimage -L` before running the application.

## Install

```sh
git clone https://github.com/peteh/papertrailscan.git
cd papertrailscan
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Usage

Run the automatic button-to-document workflow:

```sh
papertrailscan-button-scan --scanner-ip 192.168.2.56 --idle-timeout 10 --output-dir scans --verbose
```

Each button press scans one page. Another press within 10 seconds adds a page to the same document; after 10 idle seconds, the document is saved and the app waits for the next press. The app probes the scanner and retries after disconnects. Settings such as `--dpi`, `--format`, `--mode`, `--paper-size`, and `--source` can be passed as well.

The waiter opens a TCP connection to scanner port `1865`, sends the native wait-start request, and returns when the scanner reports a button press. Use `--timeout 30` to limit each wait or omit `--once` to wait again after each press.

## Docker

A containerized version of the button-triggered scanner workflow is included. The scanner IP is required, and the container always writes scanned documents to the same path inside the container: `/data/scans`. The host-side mount location is configured with `HOST_SCAN_DIR`.

Use a `.env` file next to `docker-compose.yml` or export the values in the shell:

```bash
SCANNER_IP=192.168.2.56 \
HOST_SCAN_DIR=/srv/paperless/consume \
docker compose up --build
```

Example `.env`:

```basic
SCANNER_IP=192.168.2.56
HOST_SCAN_DIR=/srv/paperless/consume
DPI=300
FORMAT=pdf
MODE=Color
PAPER_SIZE=A4
SOURCE='ADF Front'
IDLE_TIMEOUT=20
RECONNECT_INTERVAL=3
SCAN_TIMEOUT=120
VERBOSE=true
```

The Compose file mounts the host directory at `/data/scans` inside the container, so the app always writes to a fixed internal path while still allowing the host storage location to be chosen separately.

The Compose setup runs the same native CLI command as the host install, so the command-line arguments still work when running natively and the container simply passes the same options via environment variables.

## Additional tools in the repo

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

## Tests

Run the unit tests with:

```sh
python -m unittest discover -s tests -v
```
