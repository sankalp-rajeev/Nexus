"""nexus-critic entry point."""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO)

from services.critic.consumer import CriticConsumer
from services.critic.db import CriticDB


def main() -> None:
    db = CriticDB()
    db.connect()
    CriticConsumer(db).run()


if __name__ == "__main__":
    main()
