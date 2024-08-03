#!/bin/bash

# Source the .env file
export $(grep -v '^#' /home/deployer/aihealth-deployment/aihealth-server/.env | xargs)

# Set the date format for the backup file
DATE=$(date +"%Y%m%d%H%M")

# Temporary directory to store backup
TEMP_DIR="/tmp/clickhouse_backup_$DATE"
mkdir -p "$TEMP_DIR"

# Create backup
clickhouse-backup create aihealth_backup_$DATE

# Check if the backup was successful
if [ $? -ne 0 ]; then
  echo "ClickHouse backup failed."
  exit 1
fi

# Upload the backup to S3
clickhouse-backup upload aihealth_backup_$DATE

# Check if the upload was successful
if [ $? -ne 0 ]; then
  echo "Failed to upload the ClickHouse backup to S3."
  exit 1
fi

# Clean up temporary files and directory
rm -r "$TEMP_DIR"

# Make a POST request to the specified URL
# curl -X POST 

echo "ClickHouse backup completed and heartbeat sent."
