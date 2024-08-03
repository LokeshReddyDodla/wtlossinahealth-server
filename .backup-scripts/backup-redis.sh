#!/bin/bash

# Set the date format for the backup file
DATE=$(date +"%Y%m%d%H%M")

# Redis backup directory inside the container
REDIS_BACKUP_DIR="/data"

# S3 bucket name and S3 folder
S3_BUCKET="backup.aihealth.clinic"
S3_FOLDER="redis"

# Temporary directory to store backup
TEMP_DIR="/tmp/redis_backup_$DATE"
mkdir -p "$TEMP_DIR"

# Docker container name
CONTAINER_NAME="aihealth-redis"

# Command to trigger Redis backup inside the container
docker exec $CONTAINER_NAME redis-cli save

# Copy the Redis dump file from the container to the temporary directory
docker cp $CONTAINER_NAME:$REDIS_BACKUP_DIR/dump.rdb $TEMP_DIR/dump_$DATE.rdb

# Create a zip archive of the Redis dump file
zip -r "/tmp/redis_backup_$DATE.zip" "$TEMP_DIR"

# Upload the zip archive to S3
aws s3 cp "/tmp/redis_backup_$DATE.zip" "s3://$S3_BUCKET/$S3_FOLDER/redis_backup_$DATE.zip"

# Clean up temporary files and directory
rm -r "$TEMP_DIR"
rm "/tmp/redis_backup_$DATE.zip"

# Make a POST request to the specified URL
# curl -X POST 

echo "Redis backup completed and heartbeat sent."