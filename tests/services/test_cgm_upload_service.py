from lib.services.cgm_upload_service import CGMUploadService


def test_parse_linx_file_parses_expected_columns_and_values():
    service = CGMUploadService(clickhouse_store=None, postgres_store=None)
    csv_data = (
        "device_time,value(mg/dL)\n"
        "2026/03/22 21:33,135\n"
        "2026/03/22 21:34,140\n"
        "2026/03/22 21:35,not-a-number\n"
    ).encode("utf-8")

    df = service._parse_linx_file(csv_data)

    assert len(df) == 2
    assert df["glucose_mgdl"].tolist() == [135, 140]
    assert str(df["timestamp"].iloc[0]) == "2026-03-22 21:33:00"


def test_parse_linx_file_raises_for_missing_required_columns():
    service = CGMUploadService(clickhouse_store=None, postgres_store=None)
    csv_data = (
        "timestamp,glucose\n"
        "2026/03/22 21:33,135\n"
    ).encode("utf-8")

    try:
        service._parse_linx_file(csv_data)
        assert False, "Expected ValueError for missing Linx columns"
    except ValueError as exc:
        assert "Linx file missing required columns" in str(exc)


def test_extract_linx_data_points_marks_source_and_record_type():
    service = CGMUploadService(clickhouse_store=None, postgres_store=None)
    csv_data = (
        "device_time,value(mg/dL)\n"
        "2026/03/22 21:33,135\n"
    ).encode("utf-8")
    df = service._parse_linx_file(csv_data)

    points = service._extract_linx_data_points(df, "patient-1")

    assert len(points) == 1
    assert points[0]["patient_id"] == "patient-1"
    assert points[0]["glucose_level"] == 135
    assert points[0]["record_type"] == "historic"
    assert points[0]["source"] == "linx"
