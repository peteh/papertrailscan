"""Backward-compatible runner for the default three-page scan example."""

if __name__ == "__main__":
    from papertrailscan.cli import main

    raise SystemExit(main())
