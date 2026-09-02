"""Service Discovery for the Evidence Gateway (mirrors gateway/discovery.ts).

Only returns real, externally-described services: from a live discovery URL or
an inline env catalog. NEVER fabricates providers. When no real service is
found, returns an empty list so the investigation enters evidence_unavailable.
"""
import asyncio

import httpx

from .. import config

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS


def _ev_type_from_capability(cap: str) -> str:
    if "image" in cap or ("provenance" in cap and "image" in cap):
        return "image"
    if "video" in cap:
        return "video"
    if "document" in cap:
        return "document"
    if any(k in cap for k in ("url", "domain", "web")):
        return "url"
    if any(k in cap for k in ("data", "consistent")):
        return "data"
    return "text"


def _parse_inline_catalog(catalog: str) -> list[dict]:
    services = []
    for raw_line in catalog.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        name = parts[0]
        url = parts[1]
        caps_raw = parts[2]
        price_raw = parts[3]
        description = parts[4] if len(parts) > 4 else ""
        capabilities = [c.strip() for c in caps_raw.split(",") if c.strip()]
        try:
            price_unit = float(price_raw)
        except ValueError:
            continue
        if not name or not url or not capabilities or not url.lower().startswith("https://"):
            continue
        services.append({
            "id": f"svc_{capabilities[0]}_{len(services) + 1}",
            "name": name,
            "capabilities": capabilities,
            "evidenceTypes": [_ev_type_from_capability(c) for c in capabilities],
            "resourceUrl": url,
            "network": config.ALGORAND_NETWORK_CAIP2,
            "priceMicro": round(price_unit * USDC_DECIMALS),
            "assetId": config.ALGORAND_USDC_ASA,
            "description": description or f"External evidence service: {name}",
            "discoveredAt": _now_iso(),
        })
    return services


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _discover_from_url() -> list[dict]:
    url = config.EXTERNAL_EVIDENCE_SERVICES_URL
    if not url:
        return []
    try:
        async with httpx.Client(timeout=6.0) as client:
            res = await client.get(url)
        if res.status_code != 200:
            return []
        data = res.json()
        tag = config.X402_CHALLENGE_TAG
        services = []
        for s in data.get("services") or []:
            if tag and s.get("tags") and tag not in s.get("tags", []):
                continue
            resource_url = s.get("resourceUrl") or s.get("url") or ""
            if not resource_url.lower().startswith("https://"):
                continue
            capabilities = [c for c in (s.get("capabilities") or []) if c]
            if not capabilities:
                continue
            if isinstance(s.get("priceMicro"), (int, float)):
                price_micro = int(s["priceMicro"])
            elif isinstance(s.get("price"), (int, float)):
                price_micro = round(float(s["price"]) * USDC_DECIMALS)
            elif isinstance(s.get("price"), str):
                try:
                    price_micro = round(float(s["price"]) * USDC_DECIMALS)
                except ValueError:
                    continue
            else:
                continue
            services.append({
                "id": f"svc_disc_{len(services) + 1}",
                "name": s.get("name") or resource_url,
                "capabilities": capabilities,
                "evidenceTypes": [_ev_type_from_capability(c) for c in capabilities],
                "resourceUrl": resource_url,
                "network": config.ALGORAND_NETWORK_CAIP2,
                "priceMicro": price_micro,
                "assetId": s.get("assetId") or config.ALGORAND_USDC_ASA,
                "description": s.get("description") or f"External evidence service: {s.get('name')}",
                "discoveredAt": _now_iso(),
            })
        return services
    except Exception:
        return []


def _capability_matches(need: str, service_caps: list[str]) -> bool:
    return any(c == need or need in c or c in need for c in service_caps)


async def discover_services(requirements: list[dict]) -> dict:
    inline = config.EXTERNAL_EVIDENCE_SERVICES_JSON
    if inline:
        all_svc = _parse_inline_catalog(inline)
    else:
        all_svc = await _discover_from_url()
    source = "configured" if (inline and all_svc) else ("bazaar" if all_svc else "none")
    return {
        "requirements": requirements,
        "services": all_svc,
        "source": source,
        "discoveredAt": _now_iso(),
    }


def select_service_for_requirement(requirement: dict, services: list[dict]) -> dict | None:
    matches = [
        s for s in services
        if requirement["type"] in s["evidenceTypes"]
        or _capability_matches(requirement["capability"], s["capabilities"])
    ]
    if not matches:
        return None
    return min(matches, key=lambda s: s["priceMicro"])