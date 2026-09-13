"""Evidence requirement planning."""

import json
from typing import List, Optional
from ..libraries import ai as ai_lib

# Executable evidence checks — the catalog the AI plans against. Each maps to a
# check that evidence_checks.py actually runs against the user's submission.
EXECUTABLE_CHECKS = [
    {"capability": "image_provenance", "type": "image", "name": "Image provenance & metadata analysis",
     "desc": "Extracts image format, dimensions, mode and any EXIF/editor-software tags."},
    {"capability": "image_metadata", "type": "image", "name": "Image metadata / EXIF inspection",
     "desc": "Inspects EXIF/JFIF/PNG metadata tags for consistency."},
    {"capability": "video_analysis", "type": "video", "name": "Video container & encoding analysis",
     "desc": "Reads container, brands, dimensions, duration and codec/encoding facts."},
    {"capability": "frame_evidence", "type": "video", "name": "Video track & frame structure probe",
     "desc": "Probes track layout, frame rates and stream counts."},
    {"capability": "audio_transcription", "type": "audio", "name": "Audio container & metadata analysis",
     "desc": "Extracts container, sample rate, channels, bit depth and duration (no transcription)."},
    {"capability": "document_verify", "type": "document", "name": "Document text extraction",
     "desc": "Extracts the document text layer for the answer and for inconsistency checking."},
    {"capability": "data_consistency", "type": "data", "name": "Structured data consistency check",
     "desc": "Profiles CSV rows/columns or JSON records/keys and flags empty cells."},
    {"capability": "content_extract", "type": "url", "name": "URL content inspection",
     "desc": "Live DNS, TLS certificate and page-title/snippet inspection of a URL."},
]

EXECUTABLE_BY_CAP = {c["capability"]: c for c in EXECUTABLE_CHECKS}


class EvidencePlanner:
    """AI-driven evidence planner with deterministic fallback."""

    def __init__(self, executable_checks: List[dict] = EXECUTABLE_CHECKS):
        self.checks = executable_checks
        self.by_cap = {c["capability"]: c for c in executable_checks}

    async def plan(self, question: str, inputs: List[str]) -> List[dict]:
        """Plan evidence requirements based on question objectives."""
        
        # 1. Try AI-driven planning
        try:
            return await self._plan_ai(question, inputs)
        except Exception as e:
            print(f"AI planning failed, falling back: {e}")
            # 2. Fallback to deterministic capability-based selection
            return self._plan_fallback(question, inputs)

    async def _plan_ai(self, question: str, inputs: List[str]) -> List[dict]:
        """Utilize LLM to select evidence services based on capabilities."""
        applicable = [c for c in self.checks if not inputs or c["type"] in inputs or c["type"] == "text"]
        
        catalog = "\n".join(
            f"{c['capability']}: {c['name']} — {c['desc']}"
            for c in applicable
        )
        
        system_prompt = (
            "You are Inquvia's investigation planner. Identify investigation objectives "
            "from the user question and select relevant evidence capability checks.\n"
            "Return ONLY a JSON object: {\"subObjectives\": [string], \"checks\": [capability_id]}\n"
            f"CATALOG:\n{catalog}"
        )
        
        user_text = f"QUESTION: {question}\nINPUT_TYPES: {', '.join(inputs)}"
        raw = await ai_lib.call_ai_with_parts(system_prompt, [{"text": user_text}])
        
        data = json.loads(raw)
        checks = []
        for cap_id in data.get("checks", []):
            if cap_id in self.by_cap:
                checks.append({
                    "id": f"req_{len(checks) + 1}",
                    "type": self.by_cap[cap_id]["type"],
                    "capability": cap_id,
                    "reason": self.by_cap[cap_id]["name"]
                })
        return checks

    def _plan_fallback(self, question: str, inputs: List[str]) -> List[dict]:
        """Deterministic fallback capability selection."""
        checks = []
        # Fallback just selects all applicable checks based on input type
        for c in self.checks:
            if not inputs or c["type"] in inputs or c["type"] == "text":
                checks.append({
                    "id": f"req_{len(checks) + 1}",
                    "type": c["type"],
                    "capability": c["capability"],
                    "reason": c["name"]
                })
        return checks[:4]

# Backward compatibility wrappers for existing tests
def plan_evidence_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)

def plan_claim_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)

def plan_image_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)

def plan_video_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_claim_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_source_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_evidence_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)
