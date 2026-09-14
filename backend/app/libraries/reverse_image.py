"""Reverse-image / near-duplicate search (image layer 2) and earliest-source
dating (layer 3).

Grounded in SerpAPI's `google_reverse_image` engine when SERPAPI_API_KEY is
configured. When no key is set the layer reports honestly that it is
unavailable — it never fabricates matches. Match snippets are structured
observations the analyzer reasons over for provenance and context.

ponytail: single provider (Google via SerpAPI); TinEye/Bing/Yandex adapters
and per-image thumbnail downloads are the known ceiling — the SerpAPI results
already provide page-level provenance and dates.
"""
import io
import re
from datetime import datetime

import httpx

from .. import config


def provisioned() -> bool:
    return bool(config.SERPAPI_API_KEY)


def _parse_date(raw: object) -> str | None:
    """Best-effort ISO-8601 date normalization (YYYY-MM-DD)."""
    if not isinstance(raw, str):
        return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    try:
        return datetime.fromisoformat(raw.split("T")[0]).date().isoformat()
    except Exception:
        return None


def earliest_source(matches: list[dict]) -> dict | None:
    """The match with the earliest usable publication date (layer 3)."""
    dated = [m for m in matches if m.get("publishedDate")]
    if not dated:
        return None
    first = min(dated, key=lambda m: m["publishedDate"])
    return {
        "title": first.get("title"),
        "link": first.get("link"),
        "source": first.get("source"),
        "publishedDate": first.get("publishedDate"),
        "dateKind": "published",
    }


async def _run_serpapi(data: bytes, mime: str, filename: str) -> dict | None:
    """POST the image to SerpAPI reverse-image search, return normalized hits.

    Returns None on any upstream failure so callers degrade to an honest
    "search failed" record instead of an empty "no matches" verdict.
    """
    provider_notes = []
    try:
        files = {"image_file": (filename or "image", io.BytesIO(data), mime or "image/jpeg")}
        params = {"engine": "google_reverse_image", "api_key": config.SERPAPI_API_KEY}
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                "https://serpapi.com/search.json", params=params, files=files
            )
        if res.status_code != 200:
            return {"error": f"Reverse-image search failed (HTTP {res.status_code})."}
        payload = res.json()
    except Exception:
        return {"error": "Reverse-image search failed upstream (network or provider error)."}

    matches = []
    raw_matches = (
        payload.get("image_results")
        or payload.get("inline_images")
        or payload.get("images_results")
        or []
    )
    for i, item in enumerate(raw_matches):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("name") or "").strip()
        link = (item.get("link") or item.get("original") or item.get("url") or "").strip()
        source = (item.get("source") or item.get("website_name") or "").strip()
        snippet = (item.get("snippet") or item.get("description") or "").strip()
        if not link and not title:
            continue
        matches.append({
            "position": int(item.get("position") or i + 1),
            "title": title[:300],
            "link": link[:1000],
            "source": source[:200] or "unknown",
            "snippet": snippet[:500],
            "publishedDate": _parse_date(
                item.get("image_date") or item.get("date") or item.get("published_date")
            ),
            "via": "google",
        })
    return {"matches": matches}


async def search(data: bytes, mime: str = "image/jpeg", filename: str = "image") -> dict:
    """Public entrypoint: always returns a structured result, never raises.

    - not provisioned  -> {"provisioned": False, "matches": [], "reason": ...}
    - search failed    -> {"provisioned": True, "matches": [], "error": ...}
    - success          -> {"provisioned": True, "providers": ["serpapi"],
                           "matches": [...], "earliestSource": {...}}
    """
    if not provisioned():
        return {
            "provisioned": False,
            "matches": [],
            "matchCount": 0,
            "reason": "Reverse-image search is not provisioned (no SERPAPI_API_KEY).",
        }
    payload = await _run_serpapi(data, mime, filename)
    if not payload or payload.get("error"):
        return {
            "provisioned": True,
            "providers": ["serpapi"],
            "matches": [],
            "matchCount": 0,
            "error": (payload or {}).get("error") or "Reverse-image search failed upstream.",
        }
    matches = payload.get("matches") or []
    return {
        "provisioned": True,
        "providers": ["serpapi"],
        "matches": matches,
        "matchCount": len(matches),
        "earliestSource": earliest_source(matches),
    }


if __name__ == "__main__":  # self-check: earliest-source ordering (no network)
    a = {"link": "https://a.example/1", "title": "A", "publishedDate": "2020-05-01", "via": "google"}
    b = {"link": "https://b.example/2", "title": "B", "publishedDate": "2019-11-03", "via": "google"}
    assert _parse_date("2021-02-14") == "2021-02-14"
    first = earliest_source([a, b])
    assert first["link"] == "https://b.example/2" and first["publishedDate"] == "2019-11-03", first
    assert first["dateKind"] == "published", first
    assert earliest_source([]) is None

    c = {"link": "https://c.example/3", "title": "C", "publishedDate": "n/a", "via": "google"}
    assert earliest_source([a, b, c])["link"] == "https://b.example/2"
    print("reverse_image self-check OK")