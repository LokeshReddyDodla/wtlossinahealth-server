from influxdb_client import InfluxDBClient
from decouple import config


# Read InfluxDB URL and credentials from env
INFLUXDB_URL = config("INFLUXDB_URL", default="http://localhost:8086")
INFLUXDB_USER = config("INFLUXDB_USER", default="admin")
INFLUXDB_PASSWORD = config("INFLUXDB_PASSWORD", default="password")
INFLUXDB_ORG = config("INFLUXDB_ORG", default="aihealth")
INFLUXDB_BUCKET = config("INFLUXDB_BUCKET", default="your_influxdb_bucket")


class InfluxStore:
    def __init__(self):
        self.client = InfluxDBClient(
            url=INFLUXDB_URL,
            username=INFLUXDB_USER,
            password=INFLUXDB_PASSWORD,
            org=INFLUXDB_ORG,
        )
        self.bucket = INFLUXDB_BUCKET

    def write_data(self, data):
        write_api = self.client.write_api()
        write_api.write(bucket=self.bucket, record=data)

    def query_data(self, query):
        query_api = self.client.query_api()
        return query_api.query(query)


def get_influx_store() -> InfluxStore:
    return InfluxStore()
