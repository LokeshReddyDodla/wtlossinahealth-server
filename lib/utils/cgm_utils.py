from datetime import datetime


class CGMDataUtils:
    def __init__(self, clickhouse_store):
        self.clickhouse_store = clickhouse_store

    async def is_data_available_and_continuous(
        self, patient_id: str, from_date: datetime, to_date: datetime
    ) -> bool:
        from_date_date = from_date.date()
        to_date_date = to_date.date()

        query = f"""
        SELECT count() as cnt, min(toDate(time)) as min_date, max(toDate(time)) as max_date
        FROM aihealth.cgm_data
        WHERE patient_id = '{patient_id}' AND toDate(time) BETWEEN toDate('{from_date_date}') AND toDate('{to_date_date}')
        """
        result = self.clickhouse_store.query_data(query)
        if result and len(result) > 0:
            cnt, min_date, max_date = result[0]
            if cnt > 0 and min_date <= from_date_date and max_date >= to_date_date:
                return True
        return False
