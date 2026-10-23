#!/usr/bin/env sh
# Команда контейнера миграций: применить Alembic и, если CC_SEED_DEMO=true, засеять демо.
set -eu

echo "waiting for postgres..."
python - <<'PY'
import os, time
import psycopg
url = os.environ["CC_DATABASE_URL"].replace("+psycopg", "")
for attempt in range(60):
    try:
        with psycopg.connect(url, connect_timeout=2):
            break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("postgres not reachable")
print("postgres is up")
PY

alembic upgrade head

if [ "${CC_SEED_DEMO:-false}" = "true" ]; then
  echo "seeding demo data..."
  python -m app.scripts.seed
fi

echo "migrate_and_seed done"
