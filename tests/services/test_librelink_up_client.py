"""Pure-function tests for LibreLinkUpClient.

Network-touching paths (login/connections/graph) are not exercised here —
they're covered by an integration smoke run against a real account. These
tests pin the parsing + normalization that the rest of the pipeline relies
on (timestamp = naive UTC, dedup by time, source label, record_type
mapping).
"""

import datetime as dt
import os

# Required by decouple at import time.
os.environ.setdefault("LIBREVIEW_EMAIL", "test@example.com")
os.environ.setdefault("LIBREVIEW_PASSWORD", "test-password")
os.environ.setdefault("LIBREVIEW_ACCOUNT_ID", "unused-for-llu")
os.environ.setdefault("LIBREVIEW_SITE_KEY", "unused")
os.environ.setdefault("TWOCAPTCHA_API_KEY", "unused")
os.environ.setdefault("LIBREVIEW_TRUSTED_DEVICE_TOKEN", "unused")

from lib.services.librelink_up_client import LibreLinkUpClient  # noqa: E402


def _make_client():
    # Bypass __init__'s CacheStore (Redis) — we only test pure helpers.
    client = LibreLinkUpClient.__new__(LibreLinkUpClient)
    return client


def test_parse_factory_ts_naive_utc_am_pm():
    ts = LibreLinkUpClient._parse_factory_ts("5/1/2026 1:31:31 AM")
    assert ts == dt.datetime(2026, 5, 1, 1, 31, 31)
    # Must be naive (TIMESTAMP WITHOUT TIME ZONE).
    assert ts.tzinfo is None


def test_parse_factory_ts_24h_fallback():
    ts = LibreLinkUpClient._parse_factory_ts("12/31/2025 23:00:00")
    assert ts == dt.datetime(2025, 12, 31, 23, 0, 0)
    assert ts.tzinfo is None


def test_parse_factory_ts_garbage_returns_none():
    assert LibreLinkUpClient._parse_factory_ts("") is None
    assert LibreLinkUpClient._parse_factory_ts("not a date") is None


def test_normalize_graph_dedups_latest_against_history_tail():
    client = _make_client()
    same_ts = "5/1/2026 1:31:31 AM"
    payload = {
        "graphData": [
            {"FactoryTimestamp": "5/1/2026 1:16:31 AM", "ValueInMgPerDl": 90},
            {"FactoryTimestamp": same_ts, "ValueInMgPerDl": 95},
        ],
        "connection": {
            "glucoseMeasurement": {
                "FactoryTimestamp": same_ts,
                "ValueInMgPerDl": 95,
            }
        },
    }

    rows = client.normalize_graph(payload, "patient-1")

    assert len(rows) == 2
    # Sorted ascending by time.
    assert rows[0]["time"] < rows[1]["time"]
    # Latest measurement wins → record_type == "scan" at the tail.
    assert rows[-1]["record_type"] == "scan"
    assert rows[0]["record_type"] == "historic"


def test_normalize_graph_skips_invalid_entries():
    client = _make_client()
    payload = {
        "graphData": [
            {"FactoryTimestamp": "", "ValueInMgPerDl": 90},  # bad ts
            {"FactoryTimestamp": "5/1/2026 1:00:00 AM", "ValueInMgPerDl": None},  # no val
            {"FactoryTimestamp": "5/1/2026 1:15:00 AM", "ValueInMgPerDl": 110},
        ],
        "connection": {},
    }

    rows = client.normalize_graph(payload, "p")

    assert len(rows) == 1
    assert rows[0]["glucose_level"] == 110
    assert rows[0]["source"] == "librelinkup"
    assert rows[0]["record_type"] == "historic"
    assert rows[0]["patient_id"] == "p"


def test_normalize_graph_rounds_float_values():
    client = _make_client()
    payload = {
        "graphData": [
            {"FactoryTimestamp": "5/1/2026 1:00:00 AM", "ValueInMgPerDl": 95.6}
        ],
        "connection": {},
    }
    rows = client.normalize_graph(payload, "p")
    assert rows[0]["glucose_level"] == 96
    assert isinstance(rows[0]["glucose_level"], int)


def test_normalize_graph_empty_payload():
    client = _make_client()
    assert client.normalize_graph({}, "p") == []
    assert client.normalize_graph({"graphData": []}, "p") == []
