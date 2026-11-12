"""Searching Open Food Facts by name, with Search-a-licious answered here."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.metron.openfoodfacts import COMPLETE, SEARCH_URL, search_query

YOGURT = {
    "code": "8017596079480",
    "brands": ["Land", " Eurospin"],
    "quantity": "150g",
    "product_name": "Yogurt greco bianco",
    "product_name_it": "Yogurt greco bianco",
    "nutriments": {
        "energy-kcal_100g": 70,
        "proteins_100g": 9,
        "carbohydrates_100g": 4,
        "fat_100g": 2,
    },
}


def answer(hits: list[dict], page: int = 1, page_count: int = 1) -> dict[str, Any]:
    """A successful Search-a-licious reply."""
    return {
        "hits": hits,
        "page": page,
        "page_size": 10,
        "page_count": page_count,
        "count": len(hits),
        "debug": {"query": {}},
        "took": 3,
        "timed_out": False,
        "is_count_exact": True,
    }


async def search(ws, **fields: Any) -> dict[str, Any]:
    return await ws("openfoodfacts/search", **{"query": "yogurt greco", "language": "it", **fields})


async def test_finds_a_page_of_complete_products_in_the_language_and_english(
    aioclient_mock: AiohttpClientMocker, ws
) -> None:
    aioclient_mock.get(SEARCH_URL, json=answer([YOGURT], page=2, page_count=3))
    reply = await search(ws, query="  yogurt greco ", page=2)
    assert reply["success"], reply
    assert reply["result"] == {"products": [YOGURT], "more": True}

    _method, url, _data, headers = aioclient_mock.mock_calls[0]
    assert url.query["q"] == f"yogurt greco {COMPLETE}"
    assert url.query["langs"] == "it,en"
    assert url.query["page"] == "2"
    assert url.query["page_size"] == "10"
    assert url.query["fields"] == (
        "code,product_name,product_name_it,product_name_en,brands,quantity,nutriments"
    )
    assert headers["User-Agent"].startswith("Metron/")
    assert headers["User-Agent"].endswith(" (https://github.com/matteo-pacini/metron)")


async def test_the_last_page_has_no_more_and_english_is_asked_once(
    aioclient_mock: AiohttpClientMocker, ws
) -> None:
    aioclient_mock.get(SEARCH_URL, json=answer([], page_count=0))
    reply = await search(ws, language="en")
    assert reply["result"] == {"products": [], "more": False}
    _method, url, _data, _headers = aioclient_mock.mock_calls[0]
    assert url.query["page"] == "1"
    assert url.query["langs"] == "en"
    assert url.query["fields"] == "code,product_name,product_name_en,brands,quantity,nutriments"


async def test_leaves_out_products_without_a_number_for_each_main_value(
    aioclient_mock: AiohttpClientMocker, ws
) -> None:
    def without(key: str, value: Any = None) -> dict[str, Any]:
        nutriments = {k: v for k, v in YOGURT["nutriments"].items() if k != key}
        if value is not None:
            nutriments[key] = value
        return {**YOGURT, "code": f"odd-{key}-{value}", "nutriments": nutriments}

    odd = [
        without("energy-kcal_100g"),
        without("proteins_100g", "9"),
        without("carbohydrates_100g", True),
        without("fat_100g", {}),
        {**YOGURT, "code": "no-nutriments", "nutriments": None},
        {key: value for key, value in YOGURT.items() if key != "nutriments"},
    ]
    whole = {**YOGURT, "nutriments": {**YOGURT["nutriments"], "fat_100g": 0.5}}
    aioclient_mock.get(SEARCH_URL, json=answer([*odd, YOGURT, whole], page_count=2))
    reply = await search(ws)
    assert reply["result"] == {"products": [YOGURT, whole], "more": True}


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"status": 503}, "HTTP 503"),
        ({"exc": TimeoutError()}, "no answer in time"),
        ({"exc": aiohttp.ClientConnectionError("Connection refused")}, "Connection refused"),
        ({"exc": aiohttp.ClientConnectionError()}, "ClientConnectionError"),
        ({"text": "<html>Bad gateway</html>"}, None),
        (
            {"json": {"errors": [{"title": "Index not ready"}], "debug": {"query": {}}}},
            "Index not ready",
        ),
    ],
)
async def test_a_failed_search_is_an_error_the_card_can_show(
    aioclient_mock: AiohttpClientMocker, ws, reply: dict[str, Any], message: str | None
) -> None:
    aioclient_mock.get(SEARCH_URL, **reply)
    result = await search(ws)
    assert not result["success"], result
    assert result["error"]["code"] == "search_failed"
    if message is not None:
        assert result["error"]["message"] == message


@pytest.mark.parametrize(
    "fields",
    [{"query": "  "}, {"language": "en-GB"}, {"language": "EN"}, {"page": 0}],
)
async def test_needs_some_text_a_language_code_and_a_page_from_1(
    aioclient_mock: AiohttpClientMocker, ws, fields: dict[str, Any]
) -> None:
    result = await search(ws, **fields)
    assert result["error"]["code"] == "invalid_format"
    assert aioclient_mock.call_count == 0


def test_the_person_s_text_cannot_change_the_query() -> None:
    text = 'M&M\'s (peanut) -free +1 brands:x 1/2 "50%" a* b? c~ ^2 [x TO y] {z} < > = ! | \\'
    assert search_query(text) == (
        'M\\&M\'s \\(peanut\\) \\-free \\+1 brands\\:x 1\\/2 \\"50%\\" a\\* b\\? c\\~ \\^2 '
        "\\[x TO y\\] \\{z\\} \\< \\> \\= \\! \\| \\\\ " + COMPLETE
    )
    assert search_query("fish AND chips OR NOT peas ANDES") == (
        f"fish and chips or not peas ANDES {COMPLETE}"
    )
