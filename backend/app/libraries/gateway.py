"""Investigation record helpers (previously the Evidence Acquisition Gateway).

Core no longer acquires external evidence: the submitted input is analyzed
in-house via the AI providers (Gemini/Groq). This module only shapes the
investigation record.
"""
import secrets

from .. import db, config

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS


def _nanoid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)[:8]}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def create_investigation_record(input_: dict) -> dict:
    now = _now_iso()
    return {
        "id": input_["id"], "userId": input_.get("userId"), "title": input_["title"],
        "capability": input_.get("capability"), "capabilityPriceUsdc": input_.get("capabilityPriceUsdc"),
        "idempotencyKey": input_.get("idempotencyKey"), "question": input_["question"],
        "inputs": input_.get("inputs") or [], "inputType": input_.get("inputType"),
        "investigationPlan": [], "selectedCapabilities": [], "evidence": [],
        "contradictions": [], "conclusion": "inconclusive", "conclusionText": "",
        "confidence": 0, "risk": "unknown", "limitations": [],
        "economicSummary": {"totalSpend": 0, "checksPurchased": 0, "providerCategories": [], "settlementStatus": "Pending"},
        "status": input_.get("status"), "stages": [], "createdAt": now, "updatedAt": now,
        "findings": [], "supportingEvidenceIds": [], "contradictoryEvidenceIds": [],
        "evidenceRequirements": [], "acquisitions": [], "activity": [],
        "evidenceGraph": {"nodes": [], "edges": []},
    }