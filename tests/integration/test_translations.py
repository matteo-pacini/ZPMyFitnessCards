"""Every language has the same strings as English, with the same placeholders."""

import json
import re
from pathlib import Path

import pytest

FOLDER = Path(__file__).parents[2] / "custom_components" / "metron" / "translations"
LANGUAGES = ["de", "en", "es", "fr", "it", "nl", "pl", "pt", "pt-BR", "sv", "zh-Hans"]


def leaves(tree: dict, path: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            out |= leaves(value, f"{path}{key}.")
        else:
            out[path + key] = value
    return out


ENGLISH = leaves(json.loads((FOLDER / "en.json").read_text()))


def test_all_eleven_languages_are_there() -> None:
    assert sorted(p.stem for p in FOLDER.glob("*.json")) == sorted(LANGUAGES)


@pytest.mark.parametrize("language", LANGUAGES)
def test_matches_english(language: str) -> None:
    strings = leaves(json.loads((FOLDER / f"{language}.json").read_text()))
    assert strings.keys() == ENGLISH.keys()
    for key, text in strings.items():
        assert text.strip(), key
        assert set(re.findall(r"\{\w+\}", text)) == set(re.findall(r"\{\w+\}", ENGLISH[key])), key
