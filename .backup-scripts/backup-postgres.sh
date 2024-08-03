#!/bin/bash

# Source the .env file
export $(grep -v '^#' /home/deployer/aihealth-deployment/aihealth-server/.env | xargs)

# Set the date format for the backup file
DATE=$(date +"%Y%m%d%H%M")

# S3 bucket name and S3 folder
S3_BUCKET="backup.aihealth.clinic"
S3_FOLDER="postgres"

# Temporary directory to store backup
TEMP_DIR="/tmp/postgres_backup_$DATE"
mkdir -p "$TEMP_DIR"

# Docker container name
CONTAINER_NAME="aihealth-postgres"

# Create backup
docker exec $CONTAINER_NAME pg_dump -U $POSTGRES_USER $POSTGRES_DB > $TEMP_DIR/postgres_backup_$DATE.sql

# Create a zip archive of the PostgreSQL dump file
zip -r "/tmp/postgres_backup_$DATE.zip" "$TEMP_DIR"

# Upload the zip archive to S3
aws s3 cp "/tmp/postgres_backup_$DATE.zip" "s3://$S3_BUCKET/$S3_FOLDER/postgres_backup_$DATE.zip"

# Clean up temporary files and directory
rm -r "$TEMP_DIR"
rm "/tmp/postgres_backup_$DATE.zip"

# Make a POST request to the specified URL
# curl -X POST 

echo "PostgreSQL backup completed and heartbeat sent."
