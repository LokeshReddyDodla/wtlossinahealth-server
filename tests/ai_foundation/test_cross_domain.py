"""Tests for cross-domain connection detector — positive, negative, and edge cases."""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.ai_foundation.agents.health_query.coordinator import Coordinator


# ── Helpers ──────────────────────────────────────────────────────────────


@dataclass
class MockFindings:
    domain: str
    findings: str = ""
    tool_calls_used: int = 1
    data_gathered: list[str] = field(default_factory=list)
    cost: float = 0.0


def _detect(findings: list[MockFindings]) -> str:
    return Coordinator._detect_cross_domain_connections(findings)


# ── Positive: connections detected ───────────────────────────────────────


class TestConnectionsDetected:
    def test_glucose_spike_and_nutrition_carbs(self):
        findings = [
            MockFindings(domain="glucose", findings="Patient had a glucose spike to 220 mg/dL at 2pm."),
            MockFindings(domain="nutrition", findings="Lunch had 95g carbs with rice and naan."),
        ]
        result = _detect(findings)
        assert "glucose + nutrition" in result
        assert "spike" in result.lower() or "meal" in result.lower()

    def test_glucose_variability_and_poor_sleep(self):
        findings = [
            MockFindings(domain="glucose", findings="High glucose variability this week, CV% above 36%."),
            MockFindings(domain="sleep", findings="Poor sleep quality — under 5 hours on 3 nights."),
        ]
        result = _detect(findings)
        assert "glucose + sleep" in result
        assert "insulin sensitivity" in result.lower() or "sleep" in result.lower()

    def test_glucose_elevated_and_low_fitness(self):
        findings = [
            MockFindings(domain="glucose", findings="Elevated glucose averages this week."),
            MockFindings(domain="fitness", findings="Very low activity — sedentary most days, under 2000 steps."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" in result

    def test_glucose_elevated_and_minimal_activity(self):
        findings = [
            MockFindings(domain="glucose", findings="Elevated glucose averages this week."),
            MockFindings(domain="fitness", findings="Minimal activity — 1,800 steps/day, barely moved."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" in result

    def test_glucose_improved_and_high_activity(self):
        findings = [
            MockFindings(domain="glucose", findings="TIR improved to 75%, better control."),
            MockFindings(domain="fitness", findings="High activity week — 10,000 steps daily, 3 workouts."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" in result

    def test_glucose_improved_and_active(self):
        findings = [
            MockFindings(domain="glucose", findings="TIR improved to 75%, better control than last week."),
            MockFindings(domain="fitness", findings="Active week — 10,000 steps daily, 3 workouts."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" in result
        assert "exercise" in result.lower() or "activity" in result.lower()

    def test_multiple_connections(self):
        findings = [
            MockFindings(domain="glucose", findings="Glucose spike to 250, high variability."),
            MockFindings(domain="nutrition", findings="High-carb meals — average 80g carbs per meal."),
            MockFindings(domain="sleep", findings="Disrupted sleep, under 5 hours most nights."),
        ]
        result = _detect(findings)
        assert "glucose + nutrition" in result
        assert "glucose + sleep" in result

    def test_output_includes_domains_and_cues(self):
        findings = [
            MockFindings(domain="glucose", findings="Spike to 200 at 3pm."),
            MockFindings(domain="nutrition", findings="Lunch had 90g carbs."),
        ]
        result = _detect(findings)
        # Should include domain names and actionable language
        assert "glucose" in result
        assert "nutrition" in result
        assert "timing" in result.lower() or "check" in result.lower()


# ── Negative: no connections ─────────────────────────────────────────────


class TestNoConnections:
    def test_single_domain_only(self):
        findings = [
            MockFindings(domain="glucose", findings="TIR was 72% this week."),
        ]
        assert _detect(findings) == ""

    def test_multi_domain_no_matching_cues(self):
        """Both domains present but findings don't contain matching patterns."""
        findings = [
            MockFindings(domain="glucose", findings="TIR was 72% this week. Stable readings."),
            MockFindings(domain="nutrition", findings="Ate 3 meals per day. Good variety."),
        ]
        # "TIR" and "stable" don't match spike cues
        # "3 meals" and "variety" don't strongly match carb/high-carb cues
        # But "meal" DOES match _NUTRITION_MEAL_CUES...
        # glucose side needs spike/hyper/elevated cues which "stable" doesn't match
        result = _detect(findings)
        assert "glucose + nutrition" not in result

    def test_same_domain_repeated_cues_no_false_cross(self):
        """Same domain mentioned twice shouldn't create cross-domain link."""
        findings = [
            MockFindings(domain="glucose", findings="Spike at 2pm. Another spike at 8pm."),
        ]
        assert _detect(findings) == ""

    def test_empty_findings(self):
        assert _detect([]) == ""

    def test_empty_findings_text(self):
        findings = [
            MockFindings(domain="glucose", findings=""),
            MockFindings(domain="nutrition", findings=""),
        ]
        assert _detect(findings) == ""


# ── Edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_negation_no_spikes_doesnt_trigger(self):
        """'no spikes found' should not trigger spike detection."""
        findings = [
            MockFindings(domain="glucose", findings="Good week — no spikes found, TIR 82%."),
            MockFindings(domain="nutrition", findings="Balanced meals with moderate carbs."),
        ]
        result = _detect(findings)
        assert "glucose + nutrition" not in result

    def test_negation_then_valid_cue_still_triggers(self):
        """'No spikes overnight, but elevated glucose after lunch' should trigger."""
        findings = [
            MockFindings(domain="glucose", findings="No spikes overnight, but elevated glucose after lunch."),
            MockFindings(domain="nutrition", findings="Lunch had 90g carbs."),
        ]
        result = _detect(findings)
        assert "glucose + nutrition" in result

    def test_negation_not_elevated(self):
        """'not elevated' should not trigger elevated detection."""
        findings = [
            MockFindings(domain="glucose", findings="Glucose was not elevated this week."),
            MockFindings(domain="fitness", findings="Sedentary most days, low activity."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" not in result

    def test_negation_on_secondary_side_sleep(self):
        """'sleep was not disrupted' should not trigger sleep connection."""
        findings = [
            MockFindings(domain="glucose", findings="High glucose variability this week."),
            MockFindings(domain="sleep", findings="Sleep was not disrupted. Good quality, 8 hours average."),
        ]
        result = _detect(findings)
        assert "glucose + sleep" not in result

    def test_negation_on_secondary_side_fitness(self):
        """'not sedentary' should not trigger low-fitness connection."""
        findings = [
            MockFindings(domain="glucose", findings="Elevated glucose averages."),
            MockFindings(domain="fitness", findings="Patient was not sedentary. Active week overall."),
        ]
        result = _detect(findings)
        assert "glucose + fitness" not in result

    def test_negation_on_secondary_side_nutrition(self):
        """'no meal data found' should not trigger nutrition connection."""
        findings = [
            MockFindings(domain="glucose", findings="Glucose spike to 220 at 2pm."),
            MockFindings(domain="nutrition", findings="No meal data found for this period."),
        ]
        result = _detect(findings)
        assert "glucose + nutrition" not in result

    def test_wording_never_says_caused(self):
        """All connection text should use non-causal language."""
        findings = [
            MockFindings(domain="glucose", findings="Spike to 200."),
            MockFindings(domain="nutrition", findings="High carb meal."),
            MockFindings(domain="fitness", findings="Sedentary day, low activity."),
            MockFindings(domain="sleep", findings="Poor sleep, under 5 hours."),
        ]
        # Trigger all possible connections
        findings_for_var = [
            MockFindings(domain="glucose", findings="High variability, unstable."),
            MockFindings(domain="sleep", findings="Disrupted sleep."),
        ]

        for test_findings in [findings, findings_for_var]:
            result = _detect(test_findings)
            assert "caused" not in result.lower()
            assert "because" not in result.lower()
            assert "due to" not in result.lower()

    def test_nutrition_fitness_high_cal_low_activity(self):
        findings = [
            MockFindings(domain="nutrition", findings="High calorie intake — averaging 2800 kcal/day."),
            MockFindings(domain="fitness", findings="Very low activity this week, mostly sedentary."),
        ]
        result = _detect(findings)
        assert "nutrition + fitness" in result


# ── Integration: _combine_findings includes connections ──────────────────


class TestCombineFindings:
    def test_connections_appended_to_combined(self):
        findings = [
            MockFindings(domain="glucose", findings="Spike to 220 at 3pm."),
            MockFindings(domain="nutrition", findings="Lunch had 85g carbs."),
        ]
        combined, connections = Coordinator._combine_findings(findings)
        assert "## GLUCOSE FINDINGS" in combined
        assert "## NUTRITION FINDINGS" in combined
        assert "## POSSIBLE CROSS-DOMAIN CONNECTIONS" in combined
        assert "glucose + nutrition" in connections

    def test_no_connections_section_when_none(self):
        findings = [
            MockFindings(domain="glucose", findings="TIR was 72%."),
        ]
        combined, connections = Coordinator._combine_findings(findings)
        assert "CROSS-DOMAIN" not in combined
        assert connections == ""
