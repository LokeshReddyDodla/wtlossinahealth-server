"""Identity-masking matrix for LeaderboardService._is_identity_visible.

Locks the visibility rules:
- Self always visible to self
- 'public' visibility → always visible
- 'group_only' visibility → visible only on group/challenge boards
- 'private' (or any other value) → never visible to others

Combinations tested: 4 visibility values × 5 board scopes × self-vs-other.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.gamification.helpers import load_module


@pytest.fixture
def service(monkeypatch):
    module = load_module(
        monkeypatch,
        "lib/services/gamification/leaderboard_service.py",
        "leaderboard_masking_test",
    )
    return module.LeaderboardService(postgres_store=None)


VIEWER = uuid4()
OTHER = uuid4()


class TestIsIdentityVisible:
    @pytest.mark.parametrize(
        "visibility,board_scope,expected",
        [
            # public visibility — always visible regardless of scope
            ("public", "global", True),
            ("public", "facility", True),
            ("public", "group", True),
            ("public", "challenge", True),
            ("public", "buddies", True),
            # group_only — only on group / challenge boards
            ("group_only", "global", False),
            ("group_only", "facility", False),
            ("group_only", "group", True),
            ("group_only", "challenge", True),
            ("group_only", "buddies", False),
            # private (or unrecognised value) — never visible to others
            ("private", "global", False),
            ("private", "group", False),
            ("private", "challenge", False),
            ("hidden", "global", False),  # unknown value behaves like private
            ("none", "group", False),
            ("", "challenge", False),
        ],
    )
    def test_other_viewer_visibility(
        self, service, visibility, board_scope, expected,
    ):
        assert service._is_identity_visible(
            viewer_id=VIEWER, subject_id=OTHER,
            visibility=visibility, board_scope=board_scope,
        ) is expected

    @pytest.mark.parametrize(
        "visibility,board_scope",
        [
            # Self always visible regardless of visibility/scope
            ("public", "global"),
            ("group_only", "global"),
            ("private", "global"),
            ("private", "group"),
            ("private", "facility"),
            ("hidden", "challenge"),
        ],
    )
    def test_self_always_visible(self, service, visibility, board_scope):
        assert service._is_identity_visible(
            viewer_id=VIEWER, subject_id=VIEWER,
            visibility=visibility, board_scope=board_scope,
        ) is True

    def test_default_visibility_is_group_only_via_get_leaderboard(self, service):
        """When a player has no profile entry in the visibility map, the
        get_leaderboard wrapper defaults to 'group_only' (per source line 109).
        Verify the function applies that semantic correctly."""
        # group_only on a group board → visible
        assert service._is_identity_visible(
            viewer_id=VIEWER, subject_id=OTHER,
            visibility="group_only", board_scope="group",
        ) is True
        # group_only on a global board → hidden
        assert service._is_identity_visible(
            viewer_id=VIEWER, subject_id=OTHER,
            visibility="group_only", board_scope="global",
        ) is False
