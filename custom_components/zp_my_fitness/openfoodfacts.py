"""Search Open Food Facts by name, through its Search-a-licious service.

Search-a-licious answers no browser from another site (it sends no CORS
headers), so the cards ask the integration, which asks it from the Home
Assistant server. Looking a barcode up stays in the browser.
"""

from __future__ import annotations

import os
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .const import DOMAIN

# The end-to-end tests set this to a fake of their own: their Home Assistant
# has no network in the VM checks. Nothing a person configures reaches it.
SEARCH_URL = os.environ.get("ZP_MY_FITNESS_SEARCH_URL", "https://search.openfoodfacts.org/search")
PAGE_SIZE = 10
TIMEOUT = aiohttp.ClientTimeout(total=15)

# The four values a saved food needs, per 100 g, as Open Food Facts names them.
REQUIRED = ("energy-kcal", "proteins", "carbohydrates", "fat")
# Only products with all four.
COMPLETE = " ".join(f"nutriments.{n}_100g:[0 TO *]" for n in REQUIRED)

# Search-a-licious reads q as Lucene syntax. Text it cannot parse, such as an
# unbalanced "(", makes it search the whole of q as words, COMPLETE included,
# so every special character is escaped and the operators lowercased.
_SPECIAL = re.compile(r'[+\-!(){}\[\]^"~*?:\\/&|<>=]')
_OPERATORS = re.compile(r"\b(AND|OR|NOT)\b")


class SearchError(Exception):
    """Search-a-licious could not be reached, or answered with an error."""


def _complete(hit: dict[str, Any]) -> bool:
    """Whether `hit` has a number for each of REQUIRED.

    COMPLETE asks for that already, but the index is old and the cards' rows
    rely on it, so hits are checked again.
    """
    nutriments = hit.get("nutriments") or {}
    values = [nutriments.get(f"{n}_100g") for n in REQUIRED]
    return all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)


def search_query(text: str) -> str:
    """Search-a-licious's q for the products whose names match `text`."""
    words = _SPECIAL.sub(lambda m: "\\" + m.group(), text.strip())
    words = _OPERATORS.sub(lambda m: m.group().lower(), words)
    return f"{words} {COMPLETE}"


async def async_search(hass: HomeAssistant, text: str, language: str, page: int) -> dict[str, Any]:
    """One page of the products matching `text`: {products, more}.

    `language` is a two- or three-letter code. Each product has its barcode
    (`code`), `brands`, `quantity` and `nutriments` as Open Food Facts gives
    them, and `product_name` in its main language, `product_name_<language>`
    and `product_name_en` where it has them. Every product has a number for
    each of REQUIRED; hits without one are left out, so a page can hold fewer
    than PAGE_SIZE. `more` says whether there is a next page. Raises
    SearchError when Search-a-licious cannot be reached or answers with an
    error.
    """
    integration = await async_get_integration(hass, DOMAIN)
    langs = list(dict.fromkeys([language, "en"]))
    names = ",".join(f"product_name_{lang}" for lang in langs)
    params = {
        "q": search_query(text),
        "langs": ",".join(langs),
        "page": page,
        "page_size": PAGE_SIZE,
        "fields": f"code,product_name,{names},brands,quantity,nutriments",
    }
    headers = {
        "User-Agent": f"{integration.name}/{integration.version} ({integration.documentation})"
    }
    try:
        async with async_get_clientsession(hass).get(
            SEARCH_URL, params=params, headers=headers, timeout=TIMEOUT
        ) as response:
            if response.status != 200:
                raise SearchError(f"HTTP {response.status}")
            body = await response.json()
    except TimeoutError as err:
        raise SearchError("no answer in time") from err
    except (aiohttp.ClientError, ValueError) as err:
        raise SearchError(str(err) or type(err).__name__) from err
    if body.get("errors"):
        raise SearchError(body["errors"][0]["title"])
    products = [hit for hit in body["hits"] if _complete(hit)]
    return {"products": products, "more": page < body["page_count"]}
