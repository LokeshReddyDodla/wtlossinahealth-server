#!/bin/bash

# Source environment variables if needed
if [ -f /home/deployer/aihealth-deployment/aihealth-server/.env ]; then
    source /home/deployer/aihealth-deployment/aihealth-server/.env
fi

# Run all backup scripts
./backup-redis.sh
./backup-postgres.sh
./backup-mongo.sh
./backup-clickhouse.sh

echo "All backups completed."
