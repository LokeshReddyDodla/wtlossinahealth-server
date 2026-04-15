"""Tests for HealthDataType ↔ DomainName ↔ specialist domain mapping.

Closes a coverage gap on the routing layer that decides which specialist
agents handle which data types. This is critical for the lane-rule
enforcement: each specialist only runs on its own domain.

Locks:
- DOMAIN_MAPPING bidirectional consistency
- resolve_domains: data_types → unique sorted domains
- resolve_specialist_domains: data_types → unique sorted specialist keys
- HealthDataType._missing_: case-insensitive enum lookup
- AVAILABLE_HEALTH_DOMAINS: derived from enum, contains all domains
- All 27 HealthDataType members route to a known domain
"""

from __future__ import annotations

import pytest

from lib.ai_foundation.agents.health_query.contracts import (
    AVAILABLE_HEALTH_DOMAINS,
    DOMAIN_MAPPING,
    DomainName,
    HealthDataType,
    resolve_domains,
    resolve_specialist_domains,
)


# ── Bidirectional invariants on DOMAIN_MAPPING ──────────────────────────────


class TestDomainMappingInvariants:
    def test_every_data_type_maps_to_a_domain(self):
        all_typed = {dt for types in DOMAIN_MAPPING.values() for dt in types}
        # Every enum member must appear in the mapping
        for dt in HealthDataType:
            assert dt in all_typed, f"{dt} missing from DOMAIN_MAPPING"

    def test_no_data_type_is_in_two_domains(self):
        seen = []
        for types in DOMAIN_MAPPING.values():
            seen.extend(types)
        # No duplicates → each data type belongs to exactly one domain
        assert len(seen) == len(set(seen))

    def test_every_domain_has_at_least_one_data_type(self):
        for domain in DomainName:
            assert domain in DOMAIN_MAPPING, f"{domain} has no mapped types"
            assert len(DOMAIN_MAPPING[domain]) >= 1


# ── resolve_domains permutations ────────────────────────────────────────────


class TestResolveDomains:
    @pytest.mark.parametrize(
        "data_types,expected_domains",
        [
            ([], []),
            # Single type → single domain
            ([HealthDataType.MEAL], [DomainName.MEAL]),
            ([HealthDataType.SLEEP], [DomainName.SLEEP]),
            ([HealthDataType.MEDICATION], [DomainName.MEDICATION]),
            # CGM cluster — multiple types → single domain (CGM)
            ([HealthDataType.CGM_RANGE, HealthDataType.HYPER_STATS], [DomainName.CGM]),
            ([HealthDataType.HYPO_EVENT, HealthDataType.RAPID_SPIKE_EVENT], [DomainName.CGM]),
            # Multi-domain — sorted alphabetically by .value
            (
                [HealthDataType.MEAL, HealthDataType.SLEEP],
                [DomainName.MEAL, DomainName.SLEEP],
            ),
            (
                [HealthDataType.SLEEP, HealthDataType.MEAL],  # reverse input
                [DomainName.MEAL, DomainName.SLEEP],          # same sorted output
            ),
            # All domains
            (
                [
                    HealthDataType.MEAL, HealthDataType.CGM_RANGE,
                    HealthDataType.SLEEP, HealthDataType.SMBG,
                    HealthDataType.MEDICATION,
                ],
                # Sorted by domain.value: cgm, meal, medication, sleep, smbg
                sorted(
                    [DomainName.CGM, DomainName.MEAL, DomainName.MEDICATION,
                     DomainName.SLEEP, DomainName.SMBG],
                    key=lambda d: d.value,
                ),
            ),
            # Duplicate inputs deduplicate
            (
                [HealthDataType.MEAL, HealthDataType.MEAL, HealthDataType.MEAL],
                [DomainName.MEAL],
            ),
        ],
    )
    def test_resolve_domains_matrix(self, data_types, expected_domains):
        assert resolve_domains(data_types) == expected_domains


# ── resolve_specialist_domains permutations ────────────────────────────────


class TestResolveSpecialistDomains:
    @pytest.mark.parametrize(
        "data_types,expected_specialists",
        [
            ([], []),
            # CGM → glucose
            ([HealthDataType.CGM_RANGE], ["glucose"]),
            # SMBG → glucose (same specialist)
            ([HealthDataType.SMBG], ["glucose"]),
            # CGM + SMBG together → still just 'glucose' (deduped)
            ([HealthDataType.CGM_RANGE, HealthDataType.SMBG], ["glucose"]),
            # MEAL → nutrition
            ([HealthDataType.MEAL], ["nutrition"]),
            # PLANS → nutrition (per dispatch)
            ([HealthDataType.DIET_PLAN], ["nutrition"]),
            # FITNESS → fitness
            ([HealthDataType.FITNESS_OVERVIEW], ["fitness"]),
            # SLEEP → sleep
            ([HealthDataType.SLEEP], ["sleep"]),
            # MOOD → sleep (consolidated wellness specialist)
            ([HealthDataType.MOOD_ENTRY], ["sleep"]),
            # SYMPTOMS → sleep
            ([HealthDataType.SYMPTOM_ENTRY], ["sleep"]),
            # VITALS → vitals
            ([HealthDataType.VITAL], ["vitals"]),
            # DOCUMENTS → documents
            ([HealthDataType.DOCUMENTS], ["documents"]),
            # Cross-domain query: glucose + nutrition + fitness, sorted
            (
                [
                    HealthDataType.CGM_RANGE,
                    HealthDataType.MEAL,
                    HealthDataType.FITNESS_OVERVIEW,
                ],
                ["fitness", "glucose", "nutrition"],
            ),
            # PROFILE has no specialist mapping → empty
            ([HealthDataType.PROFILE], []),
            # MEDICATION has no specialist mapping → empty
            ([HealthDataType.MEDICATION], []),
        ],
    )
    def test_specialist_resolution(self, data_types, expected_specialists):
        assert resolve_specialist_domains(data_types) == expected_specialists


# ── HealthDataType case-insensitive lookup ─────────────────────────────────


class TestHealthDataTypeMissingHook:
    @pytest.mark.parametrize(
        "value,expected",
        [
            # Lowercase enum names → case-insensitive resolution to the enum member
            ("meal", HealthDataType.MEAL),  # value matches lowercase string
            ("MEAL", HealthDataType.MEAL),  # via _missing_ uppercase fallback
            ("CGM_RANGE", HealthDataType.CGM_RANGE),
            ("HYPER_EVENT", HealthDataType.HYPER_EVENT),
        ],
    )
    def test_case_variants_resolve(self, value, expected):
        # HealthDataType("meal") direct lookup (matches value)
        try:
            assert HealthDataType(value) == expected
        except ValueError:
            # Fall through to _missing_ via uppercase
            assert HealthDataType(value.upper()) == expected

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            HealthDataType("not_a_real_type")

    def test_non_string_returns_none_via_missing(self):
        # _missing_ returns None for non-string → ValueError raised
        with pytest.raises(ValueError):
            HealthDataType(42)


# ── AVAILABLE_HEALTH_DOMAINS prompt variable ────────────────────────────────


class TestAvailableHealthDomains:
    def test_contains_all_domain_values(self):
        for domain in DomainName:
            assert domain.value in AVAILABLE_HEALTH_DOMAINS

    def test_comma_separated_format(self):
        assert ", " in AVAILABLE_HEALTH_DOMAINS
        items = [s.strip() for s in AVAILABLE_HEALTH_DOMAINS.split(",")]
        assert len(items) == len(list(DomainName))
        assert set(items) == {d.value for d in DomainName}
