"""The FCM fan-out worker must count only real sends.

A send that returns "no_permission"/"no_devices" is skipped (not a failure);
any other status — or a raised error — is a failure, never a silent success.
This is the guard against logging deliveries that never happened.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lib.workers.tasks.fcm.notification import process_fcm_notification


@pytest.mark.asyncio
async def test_only_real_sends_are_counted():
    fcm = AsyncMock()
    # one of each outcome, in participant order: sent, skipped, unknown, raises.
    fcm.send_fcm_notification_to_user_devices = AsyncMock(
        side_effect=["sent", "no_permission", "unexpected", RuntimeError("boom")]
    )
    participants = [{"id": i} for i in range(4)]
    info = {"title": "t", "body": "b"}

    with patch(
        "lib.dependencies.service_dependencies.get_fcm_service",
        return_value=fcm,
    ):
        result = await process_fcm_notification({}, participants, info)

    assert result.success is True
    assert result.data["sent"] == 1        # only the real "sent"
    assert result.data["skipped"] == 1     # no_permission is not a failure
    assert result.data["failed"] == 2      # unknown status + raised error
    assert result.data["total_participants"] == 4
