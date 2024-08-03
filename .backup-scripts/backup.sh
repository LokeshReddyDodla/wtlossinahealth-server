#!/bin/bash

# Source environment variables if needed
if [ -f ../.env ]; then
    source ../.env
fi

# Run all backup scripts
./backup-redis.sh
# ./backup-postgres.sh
# ./backup-mongo.sh
# ./backup-clickhouse.sh

echo "All backups completed."
