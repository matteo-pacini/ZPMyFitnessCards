"""Active calories from a sensor: which readings count for today, and today's status.

The readings are Home Assistant states, read in kcal by goals.to_kcal. What
counts is stored by FitnessData.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from . import goals as g

# The source of activity logged with the log_active_calories action. Any
# other source is a sensor's entity ID.
ACTION = "action"


def kcal_of(state: State) -> float | None:
    """The state's reading in kcal, or None unless it is a finite number ≥ 0 in a unit read.

    The unit is the state's own, read again each time, since a sensor's
    unit can change after it was chosen.
    """
    try:
        value = float(state.state)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return g.to_kcal(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))


def counts_today(state: State, kcal: float, yesterday: float | None) -> bool:
    """Whether `state`, which reads `kcal`, is a reading from today.

    It is if it last changed at or after local midnight, any `last_reset` it
    has is at or after local midnight too, and it is not exactly yesterday's
    measured figure, `yesterday`, as a value restored after a restart past
    midnight would be.
    """
    midnight = dt_util.start_of_local_day()
    if state.last_changed < midnight:
        return False
    if (reset := state.attributes.get("last_reset")) is not None:
        when = dt_util.parse_datetime(str(reset))
        if when is None or dt_util.as_local(when) < midnight:
            return False
    return kcal != yesterday


def status(
    sensor: str | None, state: State | None, held: Mapping[str, Any] | None, started: bool
) -> str:
    """Today's status, for a person with the box ticked.

    `sensor` is their sensor's entity ID, if they have one, and `state` its
    state now. `held` is today's stored activity, if any. `started` says
    whether Home Assistant has started: until then, a sensor with no state
    may be one whose integration hasn't set up yet, so it reads as one with
    no reading, not as missing.
    """
    if sensor is not None and state is None and started:
        return "missing"
    if held is None:
        return "waiting"
    if sensor is not None and (state is None or kcal_of(state) is None):
        return "unavailable"
    if held["counted"] <= held["allowed"]:
        return "level"
    if held["measured"] * held["share"] / 100 > held["cap"]:
        return "capped"
    return "counting"
