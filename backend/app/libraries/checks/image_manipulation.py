import logging
from typing import Dict, Any
from pathlib import Path
from ..evidence_types import EvidenceCheck, EvidenceResult, CheckStatus
from ..image_forensics import error_level_analysis, load_bytes

logger = logging.getLogger(__name__)

class ImageManipulationCheck:
    name = "Image manipulation & integrity analysis (ELA)"

    def can_run(self, input_data: Dict[str, Any]) -> bool:
        # ELA only works on lossy formats (JPEG/WEBP)
        return input_data.get("type") == "image" and "filePath" in input_data

    async def run(self, input_data: Dict[str, Any]) -> EvidenceResult:
        file_path = Path(input_data["filePath"])
        logger.info(f"Running ImageManipulationCheck on {file_path}")
        
        data = load_bytes(str(file_path))
        if not data:
            return {
                "checkId": "image_manipulation",
                "status": CheckStatus.FAILED,
                "evidence": {},
                "findings": [],
                "confidence": 0.0,
                "limitations": ["Could not read file"],
                "errors": ["File not found or unreadable"]
            }

        ela_result = error_level_analysis(data)
        
        if ela_result is None:
            return {
                "checkId": "image_manipulation",
                "status": CheckStatus.NOT_AVAILABLE,
                "evidence": {"reason": "ELA not applicable (likely lossless format)"},
                "findings": [],
                "confidence": 0.0,
                "limitations": ["ELA only meaningful for lossy formats (JPEG/WEBP)"],
                "errors": []
            }

        return {
            "checkId": "image_manipulation",
            "status": CheckStatus.COMPLETED,
            "evidence": {
                "meanErrorPct": ela_result.get("meanErrorPct"),
                "blockCount": ela_result.get("blockCount"),
                "elevatedRegionsCount": len(ela_result.get("elevatedRegions", [])),
            },
            "findings": [{"description": f"ELA analysis completed. Mean error: {ela_result.get('meanErrorPct')}%"}],
            "confidence": 0.7,
            "limitations": ["ELA analysis suggests potential inconsistencies but does not localize forgery."],
            "errors": []
        }
