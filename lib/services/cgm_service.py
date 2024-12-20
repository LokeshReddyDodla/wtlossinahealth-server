from io import StringIO
from typing import List

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.http_exceptions import raise_http_exception


class CGMService:
    def __init__(self, clickhouse_store, postgres_session: AsyncSession):
        self.clickhouse_store = clickhouse_store
        self.postgres_session = postgres_session

    async def parse_and_upload_cgm_data(
        self, patient_id: str, file_contents: bytes
    ):
        try:
            # Decode and read the CSV file
            decoded = file_contents.decode("utf-8")
            df = pd.read_csv(StringIO(decoded), skiprows=2)

            # Convert timestamps without changing the timezone
            df["Device Timestamp"] = pd.to_datetime(
                df["Device Timestamp"], format="%d-%m-%Y %I:%M %p"
            )

            # Determine time range for deletion
            start_time = df["Device Timestamp"].min()
            end_time = df["Device Timestamp"].max()

            # Delete existing CGM data in the range
            self.clickhouse_store.delete_existing_cgm_data(
                "aihealth.cgm_data", patient_id, start_time, end_time
            )

            # Prepare new data
            data_points = []
            for _, row in df.iterrows():
                if pd.notna(row["Scan Glucose mg/dL"]):
                    record_type = "scan"
                    glucose_level = int(row["Scan Glucose mg/dL"])
                elif pd.notna(row["Historic Glucose mg/dL"]):
                    record_type = "historic"
                    glucose_level = int(row["Historic Glucose mg/dL"])
                else:
                    continue

                data_points.append(
                    {
                        "patient_id": str(patient_id),
                        "time": row["Device Timestamp"].strftime(
                            "%Y-%m-%dT%H:%M:%S"
                        ),
                        "glucose_level": glucose_level,
                        "record_type": record_type,
                    }
                )

            print("==> data_points: ", data_points)

            cgm_data_utils = CGMDataUtils(self.clickhouse_store)
            print(
                "==> dates: ", cgm_data_utils.generate_all_report_periods(df)
            )
            # Write data to ClickHouse
            # self.clickhouse_store.write_data("aihealth.cgm_data", data_points)

        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload CGM data",
                detail=str(e),
            )
