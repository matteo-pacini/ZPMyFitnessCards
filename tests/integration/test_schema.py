"""The schema library follows the running Home Assistant."""

import importlib
import sys

import probatio
import pytest
import voluptuous

from custom_components.metron import schema


def test_uses_probatio_when_home_assistant_has_it() -> None:
    assert schema.vol is probatio


def test_falls_back_to_voluptuous_on_older_home_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "probatio", None)
    try:
        assert importlib.reload(schema).vol is voluptuous
    finally:
        monkeypatch.undo()
        importlib.reload(schema)
