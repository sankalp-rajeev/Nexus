"""nexus-assembler entry point."""

from __future__ import annotations

import logging

from services.assembler.consumer import AssemblerService

logging.basicConfig(level=logging.INFO)


def main() -> None:
    AssemblerService().run()


if __name__ == "__main__":
    main()
