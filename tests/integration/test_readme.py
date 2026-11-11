"""The README's install buttons lead to this integration and its repository."""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).parents[2]
README = (REPO / "README.md").read_text()
MANIFEST = json.loads((REPO / "custom_components" / "fork_and_scale" / "manifest.json").read_text())

# A my.home-assistant.io button: its badge, then the redirect it links to.
BUTTON = re.compile(
    r"\[!\[[^\]]*\]\(https://my\.home-assistant\.io/badges/(?P<badge>\w+)\.svg\)\]"
    r"\(https://my\.home-assistant\.io/redirect/(?P<redirect>\w+)/\?(?P<query>[^)]*)\)"
)


def buttons() -> dict[str, dict[str, str]]:
    """Each button's query, by its redirect."""
    found = {}
    for match in BUTTON.finditer(README):
        assert match["badge"] == match["redirect"], match[0]
        found[match["redirect"]] = {k: v for k, [v] in parse_qs(match["query"]).items()}
    return found


def repository() -> str:
    """owner/name of the GitHub repository the manifest documents."""
    url = urlparse(MANIFEST["documentation"])
    assert url.netloc == "github.com"
    return url.path.strip("/")


def test_has_both_install_buttons() -> None:
    assert set(buttons()) == {"hacs_repository", "config_flow_start"}


def test_the_hacs_button_opens_this_repository_as_an_integration() -> None:
    owner, name = repository().split("/")
    assert buttons()["hacs_repository"] == {
        "owner": owner,
        "repository": name,
        "category": "integration",
    }


def test_the_add_integration_button_starts_this_integration_s_setup() -> None:
    assert buttons()["config_flow_start"] == {"domain": MANIFEST["domain"]}


def test_the_custom_repository_named_is_this_one() -> None:
    assert f"add `https://github.com/{repository()}` as a custom repository" in README
    assert MANIFEST["issue_tracker"] == f"https://github.com/{repository()}/issues"

