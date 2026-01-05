import pandas as pd


class SensorLifecycleReportGenerator:
    HARD_GAP_HOURS = 24
    LARGE_GAP_MIN_HOURS = 8
    EDGE_TOL_MINUTES = 90
    MIN_REPORT_HOURS = 48
    MIN_COVERAGE = 0.60
    SENSOR_LIFE_DAYS = 14

    def __init__(self, df: pd.DataFrame):
        # Use only Historic Glucose rows
        hist_df = df.dropna(subset=["Historic Glucose mg/dL"]).copy()
        self.ts = (
            hist_df["Device Timestamp"]
            .sort_values()
            .dropna()
            .reset_index(drop=True)
        )

        # Auto-detect device interval (Libre = 15m, Libre Pro = 5m)
        if len(self.ts) > 1:
            median_gap = (
                pd.to_timedelta(self.ts.diff().median()).total_seconds() / 60
            )
            self.EXPECTED_INTERVAL_MIN = 5 if median_gap <= 7 else 15
        else:
            self.EXPECTED_INTERVAL_MIN = 15

    def generate_reports(self):
        ts = self._trim_edges(self.ts)
        if ts.empty:
            return []

        reports, segment, gaps = [], [ts.iloc[0]], []
        start_time = ts.iloc[0]

        for prev, curr in zip(ts[:-1], ts[1:]):
            gap_h = (curr - prev).total_seconds() / 3600.0
            segment_duration = (curr - start_time).total_seconds() / 3600.0

            # Case 1: Hard gap ≥ 24h → CLOSED report (sensor definitely ended)
            if gap_h >= self.HARD_GAP_HOURS:
                reports.append(self._finalize_segment(segment, gaps, is_closed=True, termination_reason="hard_gap"))
                segment, gaps, start_time = [curr], [], curr

            # Case 2: Sensor max life (14 days) → CLOSED report (sensor lifespan reached)
            elif segment_duration >= self.SENSOR_LIFE_DAYS * 24:
                reports.append(self._finalize_segment(segment, gaps, is_closed=True, termination_reason="sensor_life"))
                segment, gaps, start_time = [curr], [], curr

            else:
                segment.append(curr)
                if gap_h >= self.LARGE_GAP_MIN_HOURS:
                    gaps.append(
                        {"gap_type": "large", "start": prev, "end": curr}
                    )
                elif gap_h >= 0.5:  # ≥30m = small gap
                    gaps.append(
                        {"gap_type": "small", "start": prev, "end": curr}
                    )

        # Last segment: OPEN (more data may arrive) unless we have evidence it's closed
        # Check if last segment reached sensor life
        if segment:
            segment_duration = (segment[-1] - start_time).total_seconds() / 3600.0
            if segment_duration >= self.SENSOR_LIFE_DAYS * 24:
                reports.append(self._finalize_segment(segment, gaps, is_closed=True, termination_reason="sensor_life"))
            else:
                reports.append(self._finalize_segment(segment, gaps, is_closed=False, termination_reason=None))

        # Filter out short or low-coverage reports
        return [
            r
            for r in reports
            if r
            and r["duration_h"] >= self.MIN_REPORT_HOURS
            and r["coverage"] >= self.MIN_COVERAGE
        ]

    def _trim_edges(self, ts):
        if len(ts) < 2:
            return ts

        # Trim leading noise
        while (
            len(ts) > 1
            and (ts.iloc[1] - ts.iloc[0]).total_seconds() / 60
            > self.EDGE_TOL_MINUTES
        ):
            ts = ts.iloc[1:]

        # Trim trailing noise
        while (
            len(ts) > 1
            and (ts.iloc[-1] - ts.iloc[-2]).total_seconds() / 60
            > self.EDGE_TOL_MINUTES
        ):
            ts = ts.iloc[:-1]

        return ts

    def _finalize_segment(self, segment, gaps, is_closed=False, termination_reason=None):
        if not segment:
            return None
        start, end = segment[0], segment[-1]
        duration_h = (end - start).total_seconds() / 3600
        expected_points = duration_h * (60 / self.EXPECTED_INTERVAL_MIN)
        coverage = len(segment) / expected_points if expected_points > 0 else 0
        
        # Determine status: CLOSED if we have strong evidence sensor ended, otherwise OPEN
        status = "CLOSED" if is_closed else "OPEN"
        
        return {
            "start": start,
            "end": end,
            "duration_h": duration_h,
            "coverage": coverage,
            "gaps": gaps,
            "status": status,  # "OPEN" or "CLOSED"
            "termination_reason": termination_reason,  # "hard_gap", "sensor_life", or None
            "qa_flags": {
                "many_small_gaps": self._check_many_small_gaps(
                    gaps, duration_h
                ),
                "coverage_low": coverage < self.MIN_COVERAGE,
            },
        }

    def _check_many_small_gaps(self, gaps, duration_h):
        small_gaps = [g for g in gaps if g["gap_type"] == "small"]
        return (
            len(small_gaps) > 6
            or (len(small_gaps) / max(1, duration_h / 24)) > 3
        )
