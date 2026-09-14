"""Meme / viral media context timeline from reverse-image search hits."""
from __future__ import annotations

import re
from datetime import datetime


def _extract_caption(match: dict) -> str:
    parts = []
    for key in ("title", "snippet"):
        val = (match.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    return " — ".join(parts)[:400]


def build_timeline(reverse_result: dict | None) -> dict:
    """Build event/date → evidence → confidence timeline from reverse-image hits."""
    if not reverse_result or not reverse_result.get("provisioned"):
        return {
            "available": False,
            "reason": reverse_result.get("reason") if reverse_result else "no_reverse_search_data",
            "entries": [],
        }

    matches = reverse_result.get("matches") or []
    if not matches:
        return {
            "available": True,
            "entryCount": 0,
            "entries": [],
            "note": "Reverse-image search ran but returned no matches for timeline construction.",
        }

    entries = []
    for m in matches:
        date = m.get("publishedDate")
        caption = _extract_caption(m)
        entries.append({
            "date": date,
            "source": m.get("source") or "unknown",
            "link": m.get("link"),
            "captionOrContext": caption,
            "confidence": "medium" if date else "low",
            "position": m.get("position"),
        })

    # Sort: dated entries first (oldest first), then undated.
    def sort_key(e):
        d = e.get("date")
        if d:
            try:
                return (0, datetime.fromisoformat(d))
            except Exception:
                return (0, datetime.max)
        return (1, datetime.max)

    entries.sort(key=sort_key)

    # Detect caption/context drift across entries.
    captions = [e["captionOrContext"] for e in entries if e.get("captionOrContext")]
    unique_captions = len(set(c.lower()[:80] for c in captions))
    contextDrift = unique_captions > 1 and len(captions) > 1

    earliest = reverse_result.get("earliestSource")
    return {
        "available": True,
        "entryCount": len(entries),
        "entries": entries[:15],
        "earliestSource": earliest,
        "contextDriftDetected": contextDrift,
        "uniqueCaptionVariants": unique_captions,
        "note": (
            "Timeline is derived from reverse-image match metadata — not a complete "
            "social-media posting history."
        ),
    }


def describe(timeline: dict) -> str:
    if not timeline or not timeline.get("available"):
        return f"MEME/CONTEXT TIMELINE: unavailable ({timeline.get('reason') if timeline else 'no data'})"
    lines = ["MEME / CONTEXT TIMELINE (from reverse-image hits):"]
    if timeline.get("contextDriftDetected"):
        lines.append(
            f"- context drift detected: {timeline.get('uniqueCaptionVariants')} distinct caption/context variants"
        )
    for e in timeline.get("entries") or []:
        date = e.get("date") or "date unknown"
        lines.append(f"- {date}: {e.get('captionOrContext', '')[:120]} ({e.get('source')})")
    if timeline.get("earliestSource"):
        es = timeline["earliestSource"]
        lines.append(
            f"- earliest dated source: {es.get('publishedDate')} — {es.get('link', '')[:80]}"
        )
    return "\n".join(lines)
