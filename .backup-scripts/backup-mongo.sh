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

# MongoDB credentials
MONGO_USERNAME=$MONGO_INITDB_ROOT_USERNAME
MONGO_PASSWORD=$MONGO_INITDB_ROOT_PASSWORD
MONGO_AUTH_DB=$MONGOEXPRESS_LOGIN

# Create backup inside the container
docker exec $CONTAINER_NAME mongodump --archive="/data/db/mongo_backup_$DATE.gz" --gzip --username=$MONGO_USERNAME --password=$MONGO_PASSWORD --authenticationDatabase=$MONGO_AUTH_DB

# Check if the backup was successful
if [ $? -ne 0 ]; then
  echo "MongoDB backup failed."
  exit 1
fi

# Copy the backup file from the container to the host
docker cp $CONTAINER_NAME:/data/db/mongo_backup_$DATE.gz "$TEMP_DIR/mongo_backup_$DATE.gz"

# Check if the copy was successful
if [ $? -ne 0 ]; then
  echo "Failed to copy the MongoDB backup file from the container."
  exit 1
fi

# Upload the backup file to S3
aws s3 cp "$TEMP_DIR/mongo_backup_$DATE.gz" "s3://$S3_BUCKET/$S3_FOLDER/mongo_backup_$DATE.gz"

# Clean up temporary files and directory
rm -r "$TEMP_DIR"

# Make a POST request to the specified URL
curl -X POST https://uptime.betterstack.com/api/v1/heartbeat/UaStBus5EsqcjKtbJ9zhPmGm

echo "MongoDB backup completed and heartbeat sent."
