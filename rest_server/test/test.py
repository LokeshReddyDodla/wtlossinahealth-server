from fastapi import APIRouter, HTTPException, Request
import logging

from influxdb_client import Point


router = APIRouter(prefix="/test")

logger = logging.getLogger("mongo_test")


@router.get(path="/mongodb", tags=["Test"])
async def test_api(request: Request):
    try:
        logger.info("Attempting to insert document")
        document = {"initial_key": "initial_value"}
        await request.state.context.mongo_store.insert_document(
            "test_collection", document
        )
        logger.info("Document inserted successfully")
        return {"message": "inserted successfully"}
    except Exception as e:
        logger.error(f"Failed to insert document: {str(e)}")
        return {"message": "failed to insert", "error": str(e)}


@router.get(path="/influxdb", tags=["Test"])
async def test_influxdb(request: Request):
    try:
        # Access InfluxStore from request state context
        influx_store = request.state.context.influx_store

        # Write a test point to InfluxDB
        point = (
            Point("test_measurement")
            .tag("location", "test")
            .field("value", 100)
        )
        influx_store.write_data(point)

        # Query the test point from InfluxDB
        query = f'from(bucket: "{influx_store.bucket}") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "test_measurement")'
        result = influx_store.query_data(query)

        # Check if the point is present in the result
        if result:
            return {
                "status": "success",
                "message": "Test point written and queried successfully.",
            }
        else:
            return {
                "status": "error",
                "message": "Test point not found in query result.",
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
