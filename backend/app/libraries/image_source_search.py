"""Authoritative / historical web source search for image investigations.

Uses SerpAPI Google web search when SERPAPI_API_KEY is configured. Returns
structured hits the analyzer can reason over — never fabricates results when
the provider is unavailable or the search fails.
"""
import re

import httpx

from .. import config

# Domains treated as higher-tier sources in relevance scoring (not proof of truth).
_TIER1_DOMAINS = (
    "nasa.gov", "loc.gov", "archives.gov", "si.edu", "gov.uk", "europa.eu",
    "reuters.com", "apnews.com", "bbc.com", "nytimes.com", "gettyimages.com",
    "wikimedia.org", "wikipedia.org", "britannica.com", "smithsonianmag.com",
)


def provisioned() -> bool:
    return bool(config.SERPAPI_API_KEY)


def _source_tier(link: str) -> str:
    link_l = (link or "").lower()
    for dom in _TIER1_DOMAINS:
        if dom in link_l:
            return "primary_official_or_archive"
    if any(x in link_l for x in (".gov", ".edu", ".mil", "museum", "archive")):
        return "institutional_or_archive"
    if any(x in link_l for x in ("news", "reuters", "ap.org", "bbc.")):
        return "reputable_news"
    return "independent_web"


def build_queries(question: str, *, filename: str | None = None) -> list[str]:
    """Derive 1–2 focused search queries from the user's question."""
    q = (question or "").strip()
    if not q:
        return []
    queries = [q[:220]]
    lower = q.lower()

    # Historical / mission-specific enrichment without hard-coding answers.
    if "apollo" in lower and "11" in lower:
        queries.append("Apollo 11 photograph NASA official archive")
    elif "apollo" in lower:
        queries.append("Apollo mission photograph NASA archive")

    if filename and len(queries) < 2:
        stem = re.sub(r"\.[a-z0-9]{2,5}$", "", filename, flags=re.I)
        stem = re.sub(r"[_\-]+", " ", stem).strip()
        if stem and stem.lower() not in lower:
            queries.append(f"{q[:120]} {stem}"[:220])

    # Dedupe while preserving order.
    seen = set()
    out = []
    for item in queries:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:2]


async def _run_serpapi(query: str, *, num: int = 8) -> dict | None:
    try:
        params = {
            "engine": "google",
            "q": query,
            "api_key": config.SERPAPI_API_KEY,
            "num": num,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.get("https://serpapi.com/search.json", params=params)
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
        return None


def _normalize_hits(payload: dict, query: str) -> list[dict]:
    hits = []
    for i, item in enumerate(payload.get("organic_results") or []):
        if not isinstance(item, dict):
            continue
        link = (item.get("link") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or item.get("description") or "").strip()
        if not link and not title:
            continue
        hits.append({
            "position": int(item.get("position") or i + 1),
            "title": title[:300],
            "link": link[:1000],
            "snippet": snippet[:600],
            "sourceTier": _source_tier(link),
            "query": query,
        })
    return hits[:10]


async def search(query: str) -> dict:
    """Run a single web search query. Never raises."""
    if not provisioned():
        return {
            "provisioned": False,
            "query": query,
            "results": [],
            "resultCount": 0,
            "reason": "Authoritative web search is not provisioned (no SERPAPI_API_KEY).",
        }
    payload = await _run_serpapi(query)
    if payload is None:
        return {
            "provisioned": True,
            "query": query,
            "results": [],
            "resultCount": 0,
            "error": "Web search failed upstream (network or provider error).",
        }
    results = _normalize_hits(payload, query)
    return {
        "provisioned": True,
        "query": query,
        "results": results,
        "resultCount": len(results),
    }


async def search_for_question(question: str, *, filename: str | None = None) -> dict:
    """Run up to two queries derived from the investigation question."""
    queries = build_queries(question, filename=filename)
    if not queries:
        return {
            "provisioned": provisioned(),
            "queries": [],
            "results": [],
            "resultCount": 0,
            "reason": "No search query could be derived from the question.",
        }
    if not provisioned():
        return {
            "provisioned": False,
            "queries": queries,
            "results": [],
            "resultCount": 0,
            "reason": "Authoritative web search is not provisioned (no SERPAPI_API_KEY).",
        }

    all_results = []
    errors = []
    for q in queries:
        batch = await search(q)
        if batch.get("error"):
            errors.append(batch["error"])
        for hit in batch.get("results") or []:
            if not any(h.get("link") == hit.get("link") for h in all_results):
                all_results.append(hit)

    return {
        "provisioned": True,
        "queries": queries,
        "results": all_results[:15],
        "resultCount": len(all_results),
        "errors": errors or None,
    }
