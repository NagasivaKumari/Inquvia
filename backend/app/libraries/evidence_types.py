from typing import TypedDict, List, Dict, Optional, Literal
from dataclasses import dataclass, field

class ExtractionQuality(TypedDict):
    method: Literal["direct", "ocr", "fallback"]
    success: bool
    features_detected: List[str]  # e.g., ["text", "tables", "images"]
    page_range: Optional[List[int]]

@dataclass
class EvidenceResult:
    id: str
    source_type: str  # "url", "document", "audio", "video", "structured"
    status: Literal["pending", "retrieved", "extracted", "failed"]
    content: Optional[str] = None
    extraction_quality: Optional[ExtractionQuality] = None
    confidence_metrics: Dict[str, float] = field(default_factory=dict)
    
    def is_usable(self) -> bool:
        return self.status == "extracted" and self.extraction_quality is not None and self.extraction_quality["success"]

    def get_confidence_score(self) -> float:
        # Placeholder for structured confidence calculation
        return self.confidence_metrics.get("overall", 0.0)
