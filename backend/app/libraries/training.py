"""Inference-time training for Inquvia's AI evidence checks.

Free-tier Gemini exposes no fine-tuning API, so accuracy is raised the two
ways that are actually available here:

1. few-shot in-context learning: gold exemplars for each task are appended
   to the system prompt so the model reproduces the exact required JSON shape
   and verdict discipline (no fabricated certainty).
2. self-consistency voting: the same prompt is sampled n times at a higher
   temperature and the answer with the most agreement wins.

The eval harness (backend/eval/) measures the resulting per-task accuracy;
the GOLD_EXAMPLES below double as the first labeled seeds for it.
"""
from typing import Any

from .ai import call_ai_with_parts, parse_ai_json

# Task key -> list of {"input": ..., "output": {...gold JSON}} exemplars.
# Output shapes must match the JSON each prompt already requires.
GOLD_EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "claim": [
        {
            "input": "CLAIM: The attached invoice shows a total of $1,240.00.\nACQUIRED EVIDENCE: [id=1 invoice page total $1,240.00 dated 2024-03-12]",
            "output": {
                "conclusion": "likely_genuine",
                "confidence": 82,
                "answer": "The invoice line items sum to $1,240.00 and match the stated total.",
                "findings": ["Line items sum to $1,240.00", "Date and vendor consistent"],
                "contradictions": [],
                "limitations": ["No third-party verification of issuer"],
                "evidenceSignals": [{"id": "1", "signal": "supporting"}],
                "risk": "low",
            },
        },
        {
            "input": "CLAIM: The report says 300 people attended, but the registry lists 42.\nACQUIRED EVIDENCE: [id=2 registry 42 attendees]",
            "output": {
                "conclusion": "likely_misleading",
                "confidence": 74,
                "answer": "The claim conflicts with the registry entry of 42 attendees.",
                "findings": ["Registry lists 42 attendees"],
                "contradictions": ["Claimed 300 vs registered 42"],
                "limitations": ["Registry may be partial"],
                "evidenceSignals": [{"id": "2", "signal": "contradictory"}],
                "risk": "moderate",
            },
        },
    ],
    "verify": [
        {
            "input": "Claim: The invoice total is $1,240.00.\nEvidence: [invoice page shows total $1,240.00]\nReasoning: sum of line items equals total",
            "output": {
                "verified": True,
                "unsupported_claims": [],
                "contradictions": [],
                "missing_objectives": [],
                "confidence_score": 0.9,
            },
        },
        {
            "input": "Claim: Attendance was 300 people.\nEvidence: [registry lists 42 attendees]\nReasoning: claim much larger than registry",
            "output": {
                "verified": False,
                "unsupported_claims": ["Attendance was 300 people"],
                "contradictions": ["Claimed 300 vs evidence 42"],
                "missing_objectives": [],
                "confidence_score": 0.3,
            },
        },
    ],
    "contradictions": [
        {
            "input": "[{'id':'1','finding':'Total is $1,240.00'},{'id':'2','finding':'Total is $1,240.00'}]",
            "output": [],
        },
        {
            "input": "[{'id':'1','finding':'Attendees: 300'},{'id':'2','finding':'Attendees: 42'}]",
            "output": [
                {"evidence_id1": "1", "evidence_id2": "2", "description": "Stated attendance differs by 258"}
            ],
        },
    ],
    "authenticity": [
        {
            "input": "CLAIM: This image is undoctored. Image metadata shows an editing tool and two stacked compression artifacts.",
            "output": {
                "finding": "Signs of editing present; genuineness cannot be confirmed",
                "observations": ["Editing-software metadata present", "Repeated recompression artifacts"],
                "facts": ["Metadata lists an editing tool"],
                "confidence": 0.4,
                "limitations": ["Authenticity cannot be proven from pixels alone"],
            },
        },
    ],
    "image": [
        {
            "input": "CLAIM: The road is dry. Image shows asphalt with visible darker wet patches and three reflections.",
            "output": {
                "finding": "Visible wet patches and reflections contradict a dry road",
                "observations": ["Darker moisture patches on asphalt", "Three light reflections"],
                "facts": ["Moisture appears on the surface", "Reflections present"],
                "confidence": 0.8,
                "limitations": ["Lighting may alter appearance"],
            },
        },
    ],
    "document": [
        {
            "input": "CLAIM: Page 3 lists the refund policy. Page 3 text: 'No refunds after 14 days.'",
            "output": {
                "finding": "Page 3 contains the refund policy",
                "observations": ["14-day refund window stated"],
                "facts": ["Refund policy present on page 3"],
                "confidence": 0.95,
                "limitations": ["Policy wording may change"],
            },
        },
    ],
    "web source": [
        {
            "input": "CLAIM: The site states doors open at 6pm. Page text: 'Doors: 6:00 PM'",
            "output": {
                "finding": "Page text matches the claimed opening time",
                "observations": ["Doors listed at 6:00 PM"],
                "facts": ["Opening time present in page text"],
                "confidence": 0.9,
                "limitations": ["Page may be outdated"],
            },
        },
    ],
}

_JSON_STRINGS: dict[str, list[str]] = {
    task: [__import__("json").dumps(ex["output"], ensure_ascii=False) for ex in exs]
    for task, exs in GOLD_EXAMPLES.items()
}


def few_shot_block(task: str | None) -> str:
    """Prompt suffix showing the gold exemplars for a task. Empty when none."""
    if not task or task not in GOLD_EXAMPLES:
        return ""
    block = ["\nFOLLOW THESE GOLD EXAMPLES verbatim for structure and verdict discipline "
             "(never claim a conclusion the input cannot support):"]
    for i, ex in enumerate(GOLD_EXAMPLES[task], 1):
        block.append(f"EXAMPLE {i} INPUT:\n{ex['input']}")
        block.append(f"EXAMPLE {i} GOLD OUTPUT (only valid JSON shape):\n{_JSON_STRINGS[task][i - 1]}")
    return "\n" + "\n\n".join(block)


async def call_ai_votes(
    system_prompt: str,
    parts: list[dict],
    task: str | None = None,
    n: int = 3,
    key: str = "conclusion",
    temperature: float = 0.7,
) -> str | None:
    """Sample the task n times at high temperature and return the raw text of
    the answer group that agrees most on ``key``. Falls back to the first
    non-empty response if no sample produced a usable key."""
    results: list[tuple[str | None, dict | None]] = []
    for _ in range(max(1, n)):
        raw = await call_ai_with_parts(system_prompt, parts, temperature=temperature, task=task)
        results.append((raw, parse_ai_json(raw) if raw else None))
    by_vote: dict[str, list[str]] = {}
    for raw, obj in results:
        if isinstance(obj, dict) and obj.get(key) is not None:
            by_vote.setdefault(str(obj[key]), []).append(raw)
    if by_vote:
        best = max(by_vote.values(), key=len)[0]
        if best:
            return best
    for raw, _ in results:
        if raw:
            return raw
    return None