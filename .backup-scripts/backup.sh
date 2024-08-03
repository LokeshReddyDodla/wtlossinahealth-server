#!/bin/bash

# Run all backup scripts
/home/deployer/backup-scripts/backup-redis.sh
/home/deployer/backup-scripts/backup-postgres.sh
/home/deployer/backup-scripts/backup-mongo.sh
/home/deployer/backup-scripts/backup-clickhouse.sh

echo "All backups completed."
