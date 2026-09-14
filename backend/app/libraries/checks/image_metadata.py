import logging
from typing import Dict, Any
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS
import exifread
from ..evidence_types import EvidenceCheck, EvidenceResult, CheckStatus

logger = logging.getLogger(__name__)

class ImageMetadataCheck:
    name = "Image Metadata / EXIF inspection"

    def can_run(self, input_data: Dict[str, Any]) -> bool:
        return input_data.get("type") == "image" and "filePath" in input_data

    async def run(self, input_data: Dict[str, Any]) -> EvidenceResult:
        file_path = Path(input_data["filePath"])
        logger.info(f"Running real ImageMetadataCheck on {file_path}")
        
        evidence = {}
        findings = []
        errors = []

        try:
            with Image.open(file_path) as img:
                evidence["format"] = img.format
                evidence["dimensions"] = {"width": img.width, "height": img.height}
                evidence["mode"] = img.mode

            # Extract EXIF using exifread
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                if tags:
                    exif_data = {}
                    for k, v in tags.items():
                        # Exclude thumbnail data
                        if k not in ('JPEGThumbnail', 'TIFFThumbnail', 'Filename', 'EXIF MakerNote'):
                            exif_data[str(k)] = str(v)
                    evidence["exif"] = exif_data
                    findings.append({"description": f"Extracted {len(exif_data)} EXIF tags"})
                else:
                    evidence["exif"] = None
                    findings.append({"description": "No EXIF data found"})

        except Exception as e:
            logger.exception(f"Metadata extraction failed: {e}")
            return {
                "checkId": "image_metadata",
                "status": CheckStatus.FAILED,
                "evidence": {},
                "findings": [],
                "confidence": 0.0,
                "limitations": [],
                "errors": [str(e)]
            }

        return {
            "checkId": "image_metadata",
            "status": CheckStatus.COMPLETED,
            "evidence": evidence,
            "findings": findings,
            "confidence": 1.0,
            "limitations": [],
            "errors": errors
        }
