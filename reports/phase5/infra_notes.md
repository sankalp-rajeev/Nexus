The prior critic logs show repeated psycopg2 startup failures: PostgreSQL reported "the database system is starting up"; later Kafka DNS failures followed the broker stopping.
Docker daemon restarts bypass Compose's initial dependency ordering, while the frozen critic connects once and exits on failure.
`services/critic/Dockerfile` now starts `infra/entrypoints/critic.py`, which waits for a successful PostgreSQL query and Kafka metadata before executing the unchanged critic.
`docker-compose.phase5.yml` pins internal addresses, disables Slack notifications, mounts `infra/phase5_health.py`, and isolates PostgreSQL on host port 55433; no existing stack or volume is changed.
Cold initialization/recovery required a longer database health window; the dashboard probe uses 127.0.0.1 because nginx listens on IPv4.
