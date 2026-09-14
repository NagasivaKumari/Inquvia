"""Deterministic AI-generation indicator assessment for image investigations.

Combines reproducible file/forensics signals with an optional multimodal
assessment labeled as model output — never treated as proof.
"""
from __future__ import annotations

import re

from ..libraries import image_forensics

# Software/metadata strings sometimes associated with generative tools.
_AI_SOFTWARE_MARKERS = (
    "midjourney", "dall-e", "dalle", "stable diffusion", "stablediffusion",
    "firefly", "generative fill", "adobe firefly", "leonardo.ai", "ideogram",
    "comfyui", "automatic1111",
)


def analyze(buf: bytes, mime: str | None = None, forensics: dict | None = None) -> dict:
    """Return structured AI-generation indicators (observations, not verdicts)."""
    sig = forensics or image_forensics.analyze_image(buf, mime)
    tamper = sig.get("tamperSignals") or {}
    indicators: list[str] = []
    score = 0  # internal weighting only; surfaced as band, not probability

    if tamper.get("exifAbsent") and sig.get("format") in ("PNG", "WEBP", "JPEG"):
        indicators.append("No EXIF/camera metadata present (common but not exclusive to AI)")
        score += 1

    soft = (tamper.get("software") or "").lower()
    if soft and any(m in soft for m in _AI_SOFTWARE_MARKERS):
        indicators.append(f"Metadata software tag mentions generative tooling: {tamper.get('software')}")
        score += 3

    if tamper.get("editorIdentified") and not tamper.get("cameraMake"):
        indicators.append("Editor software tag present without camera make/model")
        score += 1

    ela = sig.get("ela") or {}
    if ela.get("uniform") and ela.get("meanErrorPct", 99) < 1.5:
        indicators.append("Very uniform ELA error distribution (can occur on synthetic or heavily compressed images)")
        score += 1

    # PNG without tIME/camera and large dimensions — weak signal only.
    if sig.get("format") == "PNG" and tamper.get("exifAbsent"):
        indicators.append("PNG without embedded capture metadata")
        score += 1

    if score >= 4:
        band = "possible_ai_indicators"
    elif score >= 2:
        band = "weak_ai_indicators"
    elif indicators:
        band = "inconclusive"
    else:
        band = "no_strong_ai_indicators"

    return {
        "indicatorBand": band,
        "indicatorCount": len(indicators),
        "indicators": indicators,
        "forensicsRef": {
            "format": sig.get("format"),
            "perceptualHash": sig.get("perceptualHash"),
            "elaSummary": ela.get("estimate") if ela else None,
        },
        "disclaimer": (
            "These are heuristic file/forensics observations only — not a certified AI detector. "
            "Use probabilistic language in conclusions."
        ),
    }


def describe(result: dict) -> dict:
    """Structured AI detection block compliant with EvidenceRecord schema."""
    if not result:
        return {
            "finding": "AI detection: analysis unavailable.",
            "type": "unknown",
            "source": {"name": "AI Detection Engine", "url": "internal", "type": "primary", "verified": True},
            "confidence": 0,
            "rationale": "No results returned."
        }
        
    indicators = result.get("indicators") or []
    finding_text = f"Assessment: {result.get('indicatorBand')}. Indicators found: {'; '.join(indicators) if indicators else 'none'}."
    
    return {
        "finding": finding_text,
        "type": "observed" if indicators else "inferred",
        "source": {"name": "AI Detection Engine", "url": "internal", "type": "primary", "verified": True},
        "confidence": 70 if result.get("indicatorBand") == "possible_ai_indicators" else 50,
        "rationale": "Heuristic analysis of file metadata, software tags, and ELA patterns.",
    }


async def multimodal_assessment(buf: bytes, mime: str | None) -> dict | None:
    """Optional multimodal artifact assessment — labeled as model output."""
    try:
        import base64
        from ..libraries import ai as ai_lib

        prompt = (
            "You are an image forensics assistant. Assess ONLY visible AI-generation indicators "
            "(anatomy errors, impossible geometry, synthetic textures, garbled text, unnatural "
            "reflections). Do NOT identify people. Return ONLY JSON: "
            '{"band":"likely_ai"|"possible_ai"|"no_strong_indicators"|"inconclusive",'
            '"observations":[string],"confidence":number}. '
            "This is advisory model output, not proof."
        )
        parts = [{"file": {"mimeType": mime or "image/jpeg",
                           "base64": base64.b64encode(buf).decode("ascii")}}]
        raw = await ai_lib.call_ai_with_parts(prompt, parts)
        payload = ai_lib.parse_ai_json(raw)
        if isinstance(payload, dict) and payload.get("band"):
            payload["source"] = "multimodal_model_assessment"
            payload["disclaimer"] = "Model assessment only — not a certified AI detector."
            return payload
    except Exception:
        return None
    return None
