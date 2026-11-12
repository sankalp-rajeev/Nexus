"""Infrastructure-only readiness wait, including Docker daemon restarts."""
import os
import sys
import time

import psycopg2
from confluent_kafka.admin import AdminClient


def wait_ready():
    for attempt in range(120):
        try:
            with psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                dbname=os.getenv("POSTGRES_DB", "nexus"),
                user=os.getenv("POSTGRES_USER", "nexus"),
                password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"),
                connect_timeout=3,
            ) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            AdminClient({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")}).list_topics(timeout=3)
            return
        except Exception as exc:
            # Never emit DSNs, credentials or response bodies.
            print(f"critic entrypoint: waiting for dependencies ({type(exc).__name__}, attempt {attempt + 1})", flush=True)
            time.sleep(3)
    raise RuntimeError("critic dependencies unavailable after readiness deadline")


if __name__ == "__main__":
    wait_ready()
    os.execv(sys.executable, [sys.executable, "-m", "services.critic.main"])
