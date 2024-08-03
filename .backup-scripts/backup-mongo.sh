#!/bin/bash

# Source the .env file
export $(grep -v '^#' /home/deployer/aihealth-deployment/aihealth-server/.env | xargs)

# Set the date format for the backup file
DATE=$(date +"%Y%m%d%H%M")

# S3 bucket name and S3 folder
S3_BUCKET="backup.aihealth.clinic"
S3_FOLDER="mongodb"

# Temporary directory to store backup
TEMP_DIR="/tmp/mongo_backup_$DATE"
mkdir -p "$TEMP_DIR"

# Docker container name
CONTAINER_NAME="aihealth-mongo"

# Create backup
docker exec $CONTAINER_NAME mongodump --archive=$TEMP_DIR/mongo_backup_$DATE.gz --gzip

# Check if the backup was successful
if [ $? -ne 0 ]; then
  echo "MongoDB backup failed."
  exit 1
fi

# Upload the backup file to S3
aws s3 cp "$TEMP_DIR/mongo_backup_$DATE.gz" "s3://$S3_BUCKET/$S3_FOLDER/mongo_backup_$DATE.gz"

# Clean up temporary files and directory
rm -r "$TEMP_DIR"

# Make a POST request to the specified URL
# curl -X POST 

echo "MongoDB backup completed and heartbeat sent."
