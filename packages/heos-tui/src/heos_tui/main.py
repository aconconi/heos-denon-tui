"""``heos-tui`` entry point."""

import argparse
import os

from .app import HeosTui


def main() -> None:
    parser = argparse.ArgumentParser(prog="heos-tui", description="Terminal UI for Denon HEOS.")
    parser.add_argument(
        "-H",
        "--host",
        default=os.environ.get("HEOS_HOST"),
        help="device IP/hostname (default: discover)",
    )
    parser.add_argument(
        "--avr-host",
        default=os.environ.get("HEOS_AVR_HOST"),
        help="Denon AVR address for the Amp tab (default: try the HEOS device's own address)",
    )
    args = parser.parse_args()
    HeosTui(args.host, args.avr_host).run()


if __name__ == "__main__":
    main()
