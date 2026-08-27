#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 1 ]] || { echo "Usage: $0 backups/file.sql.gz"; exit 2; }
gunzip -c "$1" | docker compose exec -T postgres psql -U "${POSTGRES_USER:-trading}" "${POSTGRES_DB:-trading}"
