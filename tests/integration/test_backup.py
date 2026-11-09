"""Backups see a complete database file, with no writes in progress."""

import asyncio
import os
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness import backup


async def test_writes_wait_while_a_backup_runs(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    db = entry.runtime_data.data.db
    await backup.async_pre_backup(hass)
    if db.is_sqlite:
        # The write-ahead log is folded into the file and emptied.
        wal = db.url.removeprefix("sqlite:///") + "-wal"
        assert not os.path.exists(wal) or os.path.getsize(wal) == 0

    write = asyncio.ensure_future(ws("weight/set", person="debora", day="2026-11-09", kg=69))
    # Time is frozen in these tests, so yield to the loop instead of sleeping.
    for _ in range(50):
        await asyncio.sleep(0)
    assert not write.done()

    await backup.async_post_backup(hass)
    assert (await write)["success"]


async def test_a_failed_checkpoint_lets_writes_continue(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    data = entry.runtime_data.data
    with (
        patch.object(data.db, "checkpoint", side_effect=OSError("disk")),
        pytest.raises(OSError, match="disk"),
    ):
        await backup.async_pre_backup(hass)
    assert (await ws("weight/set", person="debora", day="2026-11-09", kg=69))["success"]


async def test_resuming_without_a_backup_does_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    await backup.async_post_backup(hass)
    assert (await ws("weight/set", person="debora", day="2026-11-09", kg=69))["success"]
