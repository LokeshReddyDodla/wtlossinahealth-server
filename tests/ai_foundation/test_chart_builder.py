"""Tests for chart_builder and chart_processor — JSON→mermaid conversion."""

from __future__ import annotations

from lib.ai_foundation.agents.core.chart_builder import build_mermaid
from lib.ai_foundation.agents.core.chart_processor import process_charts


# ---------------------------------------------------------------------------
# chart_builder: bar
# ---------------------------------------------------------------------------

class TestBarChart:
    def test_basic_bar(self):
        result = build_mermaid({
            "type": "bar",
            "title": "Avg Glucose",
            "x": ["Mon", "Tue", "Wed"],
            "y_label": "mg/dL",
            "series": [{"data": [130, 140, 125]}],
        })
        assert result is not None
        assert "xychart-beta" in result
        assert 'title "Avg Glucose"' in result
        assert "x-axis" in result
        assert "y-axis" in result
        assert "bar [130, 140, 125]" in result

    def test_bar_no_data_returns_none(self):
        assert build_mermaid({"type": "bar"}) is None
        assert build_mermaid({"type": "bar", "x": [], "series": []}) is None

    def test_bar_strips_special_chars_from_title(self):
        result = build_mermaid({
            "type": "bar",
            "title": "BMI (Jan 2025) – Overview",
            "x": ["A", "B"],
            "y_label": "Value",
            "series": [{"data": [10, 20]}],
        })
        assert "(" not in result
        assert "–" not in result

    def test_bar_limits_to_10_values(self):
        result = build_mermaid({
            "type": "bar",
            "x": [f"D{i}" for i in range(15)],
            "y_label": "v",
            "series": [{"data": list(range(15))}],
        })
        # x-axis should have at most 10 labels
        assert result.count('"D') <= 10


# ---------------------------------------------------------------------------
# chart_builder: line
# ---------------------------------------------------------------------------

class TestLineChart:
    def test_basic_line(self):
        result = build_mermaid({
            "type": "line",
            "title": "Weight Trend",
            "x": ["W1", "W2", "W3"],
            "y_label": "kg",
            "series": [{"data": [86.5, 85.2, 84.8]}],
        })
        assert "line [86.5, 85.2, 84.8]" in result


# ---------------------------------------------------------------------------
# chart_builder: combo (bar + line)
# ---------------------------------------------------------------------------

class TestComboChart:
    def test_bar_with_line_overlay(self):
        result = build_mermaid({
            "type": "bar",
            "title": "Steps vs Glucose",
            "x": ["Mon", "Tue"],
            "y_label": "Value",
            "series": [
                {"type": "bar", "data": [8000, 3000]},
                {"type": "line", "data": [135, 160]},
            ],
        })
        assert "bar [8000, 3000]" in result
        assert "line [135, 160]" in result


# ---------------------------------------------------------------------------
# chart_builder: pie
# ---------------------------------------------------------------------------

class TestPieChart:
    def test_basic_pie(self):
        result = build_mermaid({
            "type": "pie",
            "title": "Time in Range",
            "segments": [
                {"label": "In Range", "value": 68},
                {"label": "High", "value": 25},
                {"label": "Low", "value": 7},
            ],
        })
        assert "pie title Time in Range" in result
        assert '"In Range" : 68' in result
        assert '"High" : 25' in result

    def test_pie_no_segments_returns_none(self):
        assert build_mermaid({"type": "pie", "segments": []}) is None


# ---------------------------------------------------------------------------
# chart_builder: gantt
# ---------------------------------------------------------------------------

class TestGanttChart:
    def test_basic_gantt(self):
        result = build_mermaid({
            "type": "gantt",
            "title": "Mar 29 Timeline",
            "sections": [{
                "name": "Meals",
                "events": [
                    {"label": "Breakfast", "start": "07:30", "end": "08:00"},
                    {"label": "Lunch", "start": "12:30", "end": "13:00"},
                ],
            }],
        })
        assert "gantt" in result
        assert "section Meals" in result
        assert "Breakfast" in result
        assert "07:30, 08:00" in result

    def test_gantt_with_crit_style(self):
        result = build_mermaid({
            "type": "gantt",
            "title": "Events",
            "sections": [{"name": "Glucose", "events": [
                {"label": "Hyper 294", "start": "22:00", "end": "23:50", "style": "crit"},
            ]}],
        })
        assert ":crit, 22:00, 23:50" in result

    def test_gantt_no_sections_returns_none(self):
        assert build_mermaid({"type": "gantt", "sections": []}) is None


# ---------------------------------------------------------------------------
# chart_builder: unknown/invalid
# ---------------------------------------------------------------------------

class TestInvalidCharts:
    def test_unknown_type(self):
        assert build_mermaid({"type": "radar"}) is None

    def test_missing_type(self):
        assert build_mermaid({}) is None


# ---------------------------------------------------------------------------
# chart_processor: block replacement
# ---------------------------------------------------------------------------

class TestChartProcessor:
    def test_replaces_chart_data_with_mermaid(self):
        text = 'Before\n\n```chart-data\n{"type": "bar", "title": "Test", "x": ["A"], "y_label": "v", "series": [{"data": [10]}]}\n```\n\nAfter'
        result = process_charts(text)
        assert "```mermaid" in result
        assert "```chart-data" not in result
        assert "Before" in result
        assert "After" in result

    def test_invalid_json_removes_block(self):
        text = 'Before\n\n```chart-data\nnot valid json\n```\n\nAfter'
        result = process_charts(text)
        assert "```mermaid" not in result
        assert "chart-data" not in result
        assert "Before" in result
        assert "After" in result

    def test_passthrough_no_charts(self):
        text = "Just text, no charts"
        assert process_charts(text) == text

    def test_multiple_charts(self):
        text = (
            '```chart-data\n{"type": "bar", "x": ["A"], "y_label": "v", "series": [{"data": [1]}]}\n```\n'
            'middle\n'
            '```chart-data\n{"type": "pie", "title": "T", "segments": [{"label": "A", "value": 50}]}\n```'
        )
        result = process_charts(text)
        assert result.count("```mermaid") == 2
        assert "middle" in result
