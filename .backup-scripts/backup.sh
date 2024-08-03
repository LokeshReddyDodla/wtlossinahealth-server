#!/bin/bash

# Source environment variables if needed
if [ -f /home/deployer/aihealth-deployment/aihealth-server/.env ]; then
    source /home/deployer/aihealth-deployment/aihealth-server/.env
fi

# Define backup scripts directory
BACKUP_SCRIPTS_DIR="/home/deployer/aihealth-deployment/aihealth-server/.backup-scripts"


# Run all backup scripts
$BACKUP_SCRIPTS_DIR/backup-redis.sh
$BACKUP_SCRIPTS_DIR/backup-postgres.sh
$BACKUP_SCRIPTS_DIR/backup-mongo.sh
$BACKUP_SCRIPTS_DIR/backup-clickhouse.sh

echo "All backups completed."
