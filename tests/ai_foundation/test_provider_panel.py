from lib.ai_foundation.agents.health_query.provider_panel_utils import has_partial_access


def test_has_partial_access_when_some_patients_filtered():
    assert has_partial_access(2, 1) is True


def test_has_partial_access_when_all_patients_accessible():
    assert has_partial_access(2, 2) is False
