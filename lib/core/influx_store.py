import os
from influxdb_client import InfluxDBClient

# Read InfluxDB URL and credentials from env
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_USER = os.getenv("INFLUXDB_USER", "admin")
INFLUXDB_PASSWORD = os.getenv("INFLUXDB_PASSWORD", "password")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "your_influxdb_org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "your_influxdb_bucket")

class InfluxStore:
    def __init__(self):
        self.client = InfluxDBClient(url=INFLUXDB_URL, username=INFLUXDB_USER, password=INFLUXDB_PASSWORD)
        self.bucket = INFLUXDB_BUCKET

    def write_data(self, data):
        write_api = self.client.write_api()
        write_api.write(bucket=self.bucket, record=data)

    def query_data(self, query):
        query_api = self.client.query_api()
        return query_api.query(query)
