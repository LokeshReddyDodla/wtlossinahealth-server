import pandas as pd
from datetime import datetime


class FitnessUploadUtils:

    @staticmethod
    def flatten_and_extract_dates(fitness_data):
        # Flatten the data into a list of dictionaries
        all_data = [
            {
                "dateFrom": item.dateFrom,
                "dateTo": item.dateTo,
                "source": item.source,
            }
            for data_list in fitness_data.__dict__.values()
            if data_list
            for item in data_list
        ]

        # Create a DataFrame
        df = pd.DataFrame(all_data)
        df["dateFrom"] = pd.to_datetime(
            df["dateFrom"].str.replace("Z", "+00:00")
        )
        df["dateTo"] = pd.to_datetime(df["dateTo"].str.replace("Z", "+00:00"))

        dateFrom = df["dateFrom"].min().replace(tzinfo=None)
        dateTo = df["dateTo"].max().replace(tzinfo=None)
        source = df["source"].iloc[0]

        return dateFrom, dateTo, source
