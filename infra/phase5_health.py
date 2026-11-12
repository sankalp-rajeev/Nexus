"""Read-only dependency health probe for Python worker containers."""
import os
from pathlib import Path
import socket
import sys


def probe(role):
    command = Path("/proc/1/cmdline").read_bytes().replace(b"\x00", b" ")
    if f"services.{role}.main".encode() not in command:
        raise RuntimeError("worker main process is not running")
    with socket.create_connection((os.getenv("POSTGRES_HOST", "postgres"), int(os.getenv("POSTGRES_PORT", "5432"))), timeout=3):
        pass
    if role in ("critic", "assembler", "classifier"):
        from confluent_kafka.admin import AdminClient
        AdminClient({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")}).list_topics(timeout=3)
    if role == "healer":
        import urllib.request
        with socket.create_connection((os.getenv("REDIS_HOST", "redis"), int(os.getenv("REDIS_PORT", "6379"))), timeout=3):
            pass
        urllib.request.urlopen("http://mlflow:5000/health", timeout=3).close()


if __name__ == "__main__":
    probe(sys.argv[1])
