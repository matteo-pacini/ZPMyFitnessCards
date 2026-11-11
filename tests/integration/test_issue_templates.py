"""The issue forms are well formed, and their links into the README lead somewhere.

GitHub shows a blank issue instead of a form it cannot read, without saying why.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[2]
TEMPLATES = REPO / ".github" / "ISSUE_TEMPLATE"
README = (REPO / "README.md").read_text()
FORMS = sorted(p.name for p in TEMPLATES.glob("*.yml") if p.name != "config.yml")
README_LINK = re.compile(r"https://github\.com/matteo-pacini/fork-and-scale#([\w-]+)")


def form(name: str) -> dict:
    return yaml.safe_load((TEMPLATES / name).read_text())


def readme_anchors() -> set[str]:
    """The README's headings as GitHub links to them."""
    return {
        re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        for heading in re.findall(r"^#{1,6} (.+)$", README, re.MULTILINE)
    }


def test_there_are_forms_for_bugs_ideas_and_translations() -> None:
    assert FORMS == ["bug_report.yml", "feature_request.yml", "translation.yml"]


@pytest.mark.parametrize("name", FORMS)
def test_each_form_names_itself_and_ids_its_fields(name: str) -> None:
    data = form(name)
    assert data["name"] and data["description"] and data["labels"]
    fields = [item for item in data["body"] if item["type"] != "markdown"]
    ids = [field["id"] for field in fields]
    assert len(ids) == len(set(ids))
    for field in fields:
        assert field["attributes"]["label"]
        if field["type"] == "dropdown":
            assert field["attributes"]["options"]


def test_links_into_the_readme_lead_to_its_headings() -> None:
    text = "".join(path.read_text() for path in TEMPLATES.glob("*.yml"))
    links = set(README_LINK.findall(text))
    assert links
    assert links <= readme_anchors()


def test_the_translation_form_lists_every_language() -> None:
    [language] = [item for item in form("translation.yml")["body"] if item.get("id") == "language"]
    translations = REPO / "custom_components" / "fork_and_scale" / "translations"
    assert len(language["attributes"]["options"]) == len(list(translations.glob("*.json")))
