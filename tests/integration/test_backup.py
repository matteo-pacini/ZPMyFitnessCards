"""Backups see a complete database file, with no writes in progress."""

import asyncio

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zp_my_fitness import backup


async def test_writes_wait_while_a_backup_runs(
    hass: HomeAssistant, entry: MockConfigEntry, ws
) -> None:
    db_file = entry.runtime_data.data.db.path
    await backup.async_pre_backup(hass)
    # The write-ahead log is folded into the file and emptied.
    wal = db_file.with_name(db_file.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0

    write = asyncio.ensure_future(ws("weight/set", person="debora", day="2026-11-09", kg=69))
    # Time is frozen in these tests, so yield to the loop instead of sleeping.
    for _ in range(50):
        await asyncio.sleep(0)
    assert not write.done()

    await backup.async_post_backup(hass)
    assert (await write)["success"]
