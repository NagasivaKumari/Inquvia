from typing import TypedDict, List, Dict, Optional, Literal, Protocol, Any, Union
from dataclasses import dataclass, field
from enum import Enum

class CheckStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    SKIPPED = "SKIPPED"
    PENDING_MIGRATION = "PENDING_MIGRATION"

class ExtractionStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"

class SourceLocator(TypedDict, total=False):
    section: Optional[str]
    table: Optional[str]
    page: Optional[int]
    anchor: Optional[str]

class Calculation(TypedDict):
    values: Dict[str, float]
    formula: str
    result: float

class EvidenceResult(TypedDict, total=False):
    checkId: str
    status: CheckStatus
    extractionStatus: ExtractionStatus
    sourceLocator: SourceLocator
    calculation: Optional[Calculation]
    evidence: Dict[str, Any]
    findings: List[Dict[str, Any]]
    confidence: float
    limitations: List[str]
    errors: List[str]

class EvidenceCheck(Protocol):
    name: str
    
    def can_run(self, input_data: Dict[str, Any]) -> bool:
        ...

    async def run(self, input_data: Dict[str, Any]) -> EvidenceResult:
        ...

class ExtractionQuality(TypedDict):
    method: Literal["direct", "ocr", "fallback"]
    success: bool
    features_detected: List[str]  # e.g., ["text", "tables", "images"]
    page_range: Optional[List[int]]
    quality: Literal["complete", "partial", "sparse", "empty"]
    metrics: Dict[str, object]

@dataclass
class EvidenceRecord:
    finding: str
    type: Literal["observed", "verified", "inferred", "unknown", "contradiction"]
    source: Dict[str, object]  # {"name": str, "url": str, "type": str, "verified": bool}
    confidence: int  # 0-100
    rationale: str
    sourceLocator: Optional[SourceLocator] = None
    calculation: Optional[Calculation] = None
    
    def to_dict(self) -> Dict:
        return {
            "finding": self.finding,
            "type": self.type,
            "source": self.source,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "sourceLocator": self.sourceLocator,
            "calculation": self.calculation
        }
