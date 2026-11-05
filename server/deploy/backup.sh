#!/bin/sh
# Runs inside the "backup" container (docker-compose.yml): a compressed dump of the database once a day,
# keeping the newest 14. Restore one with:
#   gunzip -c hellotas-YYYYMMDD-HHMM.sql.gz | docker compose exec -T db psql -U hellotas hellotas
set -eu
KEEP=14
while true; do
  file="/backups/hellotas-$(date +%Y%m%d-%H%M).sql.gz"
  if pg_dump -h db -U hellotas hellotas | gzip > "$file"; then
    echo "backup written: $file"
    count=0
    for old in $(ls -1t /backups/hellotas-*.sql.gz); do
      count=$((count + 1))
      if [ "$count" -gt "$KEEP" ]; then
        echo "dropping old backup: $old"
        rm -f "$old"
      fi
    done
  else
    echo "backup FAILED" >&2
  fi
  sleep 86400
done
