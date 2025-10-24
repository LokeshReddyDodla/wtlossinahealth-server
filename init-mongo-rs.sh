#!/bin/bash
# MongoDB Replica Set Initialization Script

echo "Waiting for MongoDB to start..."
sleep 5

echo "Initializing replica set..."
mongosh --host aihealth-mongo:27017 <<EOF
rs.initiate({
  _id: 'rs0',
  members: [
    { _id: 0, host: 'aihealth-mongo:27017' }
  ]
})
EOF

echo "Replica set initialized!"
