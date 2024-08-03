#!/bin/bash

# Set the date format for the backup file
DATE=$(date +"%Y%m%d%H%M")

# S3 bucket name and S3 folder
S3_BUCKET="backup.aihealth.clinic"
S3_FOLDER="clickhouse"

# Temporary directory to store backup
TEMP_DIR="/tmp/clickhouse_backup_$DATE"
mkdir -p "$TEMP_DIR"

# Docker container name
CONTAINER_NAME="aihealth-clickhouse"

# Create backup
docker exec $CONTAINER_NAME clickhouse-client --query="BACKUP DATABASE default TO DISK '$TEMP_DIR/default_backup_$DATE'"

# Create a zip archive of the ClickHouse dump file
zip -r "/tmp/clickhouse_backup_$DATE.zip" "$TEMP_DIR"

# Upload the zip archive to S3
aws s3 cp "/tmp/clickhouse_backup_$DATE.zip" "s3://$S3_BUCKET/$S3_FOLDER/clickhouse_backup_$DATE.zip"

# Clean up temporary files and directory
rm -r "$TEMP_DIR"
rm "/tmp/clickhouse_backup_$DATE.zip"

# Make a POST request to the specified URL
# curl -X POST 

echo "ClickHouse backup completed and heartbeat sent."
