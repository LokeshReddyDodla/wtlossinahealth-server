"""Tests for FeedService._is_identity_visible.

Salvaged from the now-deleted tests/test_gamification_unit_logic.py.

Feed visibility differs from leaderboard visibility (covered in
test_leaderboard_masking.py): feed events use a (visibility, context)
pair where context describes where the feed is being rendered.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.gamification.helpers import load_module


@pytest.fixture
def service(monkeypatch):
    module = load_module(
        monkeypatch,
        "lib/services/gamification/feed_service.py",
        "feed_visibility_test",
    )
    return object.__new__(module.FeedService)


VIEWER = uuid4()
ACTOR = uuid4()


class TestFeedIsIdentityVisible:
    @pytest.mark.parametrize(
        "visibility,context,subject,expected",
        [
            # Self always visible regardless of visibility/context
            ("anonymous", "group", VIEWER, True),
            ("anonymous", "buddy", VIEWER, True),
            # 'anonymous' visibility hides others on group/buddy contexts
            ("anonymous", "buddy", ACTOR, True),
            # public visibility — visible everywhere
            ("public", "public", ACTOR, True),
            ("public", "group", ACTOR, True),
            # group_only — only visible in group context
            ("group_only", "group", ACTOR, True),
            ("group_only", "public", ACTOR, False),
        ],
    )
    def test_visibility_matrix(
        self, service, visibility, context, subject, expected,
    ):
        assert service._is_identity_visible(
            viewer_id=VIEWER,
            actor_id=subject,
            visibility=visibility,
            context=context,
        ) is expected
